from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from biwak import schedules
from biwak.accounts.models import User
from biwak.activity import feed
from biwak.activity.models import Action, Event
from biwak.activity.operations import record
from biwak.files import queries as file_queries
from biwak.forms import Form, ModelForm
from biwak.items import glance, operations as ops
from biwak.items.models import Item, Kind, Status
from biwak.projects import operations as project_ops
from biwak.projects.models import Membership, Project
from biwak.projects.overview import overview


def project_for(request, pk):
    """The project if the person may open it, else 404 (limited projects
    don't reveal that they exist)"""
    return get_object_or_404(Project.objects.accessible_to(request.user), pk=pk)


def project_list(request):
    archived = bool(request.GET.get("archived"))
    others = Project.objects.none()
    if archived:
        # A plain alphabetical list, without cards
        projects = Project.objects.accessible_to(request.user).filter(
            archived_at__isnull=False
        )
    else:
        projects = overview(request.user)
        if request.user.is_admin:
            # Admins see that limited projects exist and can join them
            others = Project.objects.active().exclude(
                pk__in=Project.objects.accessible_to(request.user)
            )
    return render(
        request,
        "projects/project_list.html",
        {
            "projects": projects,
            "others": others,
            "archived": archived,
            "order": request.user.project_order,
            "orders": User.ProjectOrder.choices,
        },
    )


@require_POST
def project_order(request):
    """The switch on the projects page, remembered per person"""
    try:
        project_ops.set_project_order(request.user, request.POST.get("order"))
    except ValueError:
        return HttpResponse(status=400)
    return redirect("projects")


class ProjectForm(ModelForm):
    class Meta:
        model = Project
        fields = ["name", "description", "is_all_access"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}


def project_create(request):
    if request.user.is_client:
        raise PermissionDenied
    form = ProjectForm(request.POST or None)
    if form.is_valid():
        project = form.save()
        Membership.objects.create(project=project, user=request.user)
        return redirect(project)
    return render(
        request,
        "generic/form.html",
        {"form": form, "title": _("New project"), "cancel": "/"},
    )


@require_POST
def project_join(request, pk):
    """Staff join all-access projects, admins also limited ones (recorded:
    specs/access.md); joining subscribes to nothing that exists already"""
    if request.user.is_client:
        raise PermissionDenied
    if request.user.is_admin:
        project = get_object_or_404(Project, pk=pk)
    else:
        project = project_for(request, pk)
    project_ops.add_member(project, request.user, actor=request.user)
    return redirect(project)


class AddMemberForm(Form):
    user = forms.ModelChoiceField(label=_("Person"), queryset=User.objects.none())


class InviteForm(Form):
    email = forms.EmailField(label=_("Email"))
    full_name = forms.CharField(label=_("Name"), max_length=200, required=False)
    is_client = forms.TypedChoiceField(
        label=_("Staff or client"),
        choices=[("1", _("Client")), ("", _("Staff"))],
        coerce=bool,
        empty_value=False,
        initial="1",
        widget=forms.RadioSelect,
        required=False,
    )
    organization = forms.CharField(
        label=_("Organization"),
        max_length=200,
        required=False,
        help_text=_("Shown beside clients' names."),
    )

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        if not actor.is_admin:
            # Only admins create staff (specs/access.md)
            del self.fields["is_client"]


def project_people(request, pk):
    """Members; staff add, invite and remove people"""
    project = project_for(request, pk)
    can_manage = project_ops.can_manage_members(request.user)
    add_form = invite_form = None
    if can_manage:
        which = request.POST.get("form")
        add_form = AddMemberForm(request.POST if which == "add" else None)
        add_form.fields["user"].queryset = project_ops.addable_people(project)
        invite_form = InviteForm(
            request.POST if which == "invite" else None, actor=request.user
        )
        if add_form.is_valid():
            user = add_form.cleaned_data["user"]
            project_ops.add_member(project, user, actor=request.user)
            messages.success(
                request, _("%(name)s has been added.") % {"name": user.display_name}
            )
            return redirect("project_people", pk=project.pk)
        if invite_form.is_valid():
            data = invite_form.cleaned_data
            try:
                user, _changed = project_ops.invite(
                    project,
                    email=data["email"],
                    full_name=data["full_name"],
                    is_client=data.get("is_client", True),
                    organization=data["organization"],
                    actor=request.user,
                )
            except project_ops.InvitationError as exc:
                invite_form.add_error(None, str(exc))
            else:
                messages.success(
                    request,
                    _("%(name)s has been invited.") % {"name": user.display_name},
                )
                return redirect("project_people", pk=project.pk)
    return render(
        request,
        "projects/people.html",
        {
            "project": project,
            "memberships": project.memberships.select_related("user").order_by(
                "user__is_client", "user__full_name"
            ),
            "can_manage": can_manage,
            "add_form": add_form,
            "invite_form": invite_form,
        },
    )


@require_POST
def member_remove(request, pk, user_pk):
    """Staff remove anybody; everybody can leave"""
    project = project_for(request, pk)
    user = get_object_or_404(User, pk=user_pk)
    if user != request.user and not project_ops.can_manage_members(request.user):
        raise PermissionDenied
    project_ops.remove_member(project, user, actor=request.user)
    if user == request.user:
        return redirect("projects")
    return redirect("project_people", pk=project.pk)


class ListForm(Form):
    title = forms.CharField(label=_("title"), max_length=500)
    visible = forms.BooleanField(label=_("Visible to clients"), required=False)


def project_edit(request, pk):
    project = project_for(request, pk)
    if not project_ops.can_manage_project(request.user):
        raise PermissionDenied
    form = ProjectForm(request.POST or None, instance=project)
    if form.is_valid():
        form.save()
        record(actor=request.user, action=Action.EDITED_PROJECT, project=project)
        return redirect(project)
    return render(
        request,
        "projects/project_edit.html",
        {"form": form, "project": project},
    )


@require_POST
def project_archive(request, pk):
    """Archives or (``unarchive``) brings the project back"""
    project = project_for(request, pk)
    if not project_ops.can_manage_project(request.user):
        raise PermissionDenied
    if request.POST.get("unarchive"):
        project_ops.unarchive_project(project, actor=request.user)
    else:
        project_ops.archive_project(project, actor=request.user)
    return redirect(project)


@require_POST
def list_order(request, pk):
    """The lists in the dragged order (frontend/todos.js); ``lists`` are
    the IDs of all active lists the person sees"""
    project = project_for(request, pk)
    if request.user.is_client:
        raise PermissionDenied
    lists = {
        item.pk: item
        for item in Item.objects.visible_to(request.user).filter(
            project=project, kind=Kind.LIST, parent=None, status=Status.ACTIVE
        )
    }
    try:
        ids = [int(pk) for pk in request.POST.getlist("lists")]
    except ValueError:
        ids = []
    if sorted(ids) != sorted(lists):
        return HttpResponse(status=400)
    ops.reorder([lists[pk] for pk in ids])
    return HttpResponse(status=204)


def project_trash(request, pk):
    """What was trashed in the project, restorable for TRASH_DAYS days;
    staff only"""
    project = project_for(request, pk)
    if request.user.is_client:
        raise PermissionDenied
    items = ops.trashed_roots(
        Item.objects.visible_to(request.user, with_trashed=True).filter(project=project)
    ).select_related("parent")
    return render(
        request,
        "projects/trash.html",
        {"project": project, "items": items, "days": ops.TRASH_DAYS},
    )


def project_detail(request, pk):
    project = project_for(request, pk)
    items = Item.objects.visible_to(request.user).filter(project=project)
    all_lists = items.filter(kind=Kind.LIST, parent=None)
    lists = all_lists.filter(status=Status.ACTIVE).select_related("project")
    form = ListForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        item = ops.create_list(
            project=project,
            title=form.cleaned_data["title"],
            creator=request.user,
            # What clients create is visible to clients (specs/access.md)
            visible=form.cleaned_data["visible"] or request.user.is_client,
        )
        return redirect(item)
    lists = list(lists)
    counts = glance.list_counts(request.user, lists, schedules.today())
    for todolist in lists:
        todolist.open_count, todolist.overdue_count = counts.get(todolist.pk, (0, 0))
    events = list(
        Event.objects
        .visible_to(request.user)
        .filter(project=project)
        .exclude(action=Action.REACTED)
        .select_related("actor", "item")[:20]
    )
    feed.attach(events)
    return render(
        request,
        "projects/project_detail.html",
        {
            "project": project,
            "lists": lists,
            "archived_lists": all_lists.filter(status=Status.ARCHIVED),
            "can_manage": project_ops.can_manage_project(request.user),
            "form": form,
            "members": project.memberships.select_related("user"),
            "front_messages": file_queries.front_messages(project, request.user),
            "root_counts": file_queries.root_counts(project, request.user),
            "is_member": project.is_member(request.user),
            "events": events,
        },
    )
