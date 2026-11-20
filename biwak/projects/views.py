from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from biwak.accounts.models import User
from biwak.activity.models import Event
from biwak.forms import Form, ModelForm
from biwak.items import operations as ops
from biwak.items.models import Item, Kind
from biwak.projects import operations as members
from biwak.projects.models import Membership, Project


def project_for(request, pk):
    """The project if the person may open it, else 404 (limited projects
    don't reveal that they exist)"""
    return get_object_or_404(Project.objects.accessible_to(request.user), pk=pk)


def project_list(request):
    projects = Project.objects.accessible_to(request.user).active()
    others = Project.objects.none()
    if request.user.is_admin:
        # Admins see that limited projects exist and can join them
        others = Project.objects.active().exclude(pk__in=projects)
    return render(
        request,
        "projects/project_list.html",
        {"projects": projects, "others": others},
    )


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
    members.add_member(project, request.user, actor=request.user)
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
    can_manage = members.can_manage_members(request.user)
    add_form = invite_form = None
    if can_manage:
        which = request.POST.get("form")
        add_form = AddMemberForm(request.POST if which == "add" else None)
        add_form.fields["user"].queryset = members.addable_people(project)
        invite_form = InviteForm(
            request.POST if which == "invite" else None, actor=request.user
        )
        if add_form.is_valid():
            user = add_form.cleaned_data["user"]
            members.add_member(project, user, actor=request.user)
            messages.success(
                request, _("%(name)s has been added.") % {"name": user.display_name}
            )
            return redirect("project_people", pk=project.pk)
        if invite_form.is_valid():
            data = invite_form.cleaned_data
            try:
                user, _changed = members.invite(
                    project,
                    email=data["email"],
                    full_name=data["full_name"],
                    is_client=data.get("is_client", True),
                    organization=data["organization"],
                    actor=request.user,
                )
            except members.InvitationError as exc:
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
    if user != request.user and not members.can_manage_members(request.user):
        raise PermissionDenied
    members.remove_member(project, user, actor=request.user)
    if user == request.user:
        return redirect("projects")
    return redirect("project_people", pk=project.pk)


class ListForm(Form):
    title = forms.CharField(label=_("title"), max_length=500)
    visible = forms.BooleanField(label=_("Visible to clients"), required=False)


def project_detail(request, pk):
    project = project_for(request, pk)
    items = Item.objects.visible_to(request.user).filter(project=project)
    lists = items.filter(kind=Kind.LIST, parent=None).exclude(status="archived")
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
    return render(
        request,
        "projects/project_detail.html",
        {
            "project": project,
            "lists": lists,
            "form": form,
            "members": project.memberships.select_related("user"),
            "is_member": project.is_member(request.user),
            "events": Event.objects
            .visible_to(request.user)
            .filter(project=project)
            .select_related("actor", "item")[:20],
        },
    )
