from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models.functions import Lower
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from biwak import schedules
from biwak.accounts.models import Color, User, own_staff
from biwak.activity import feed
from biwak.activity.models import Action, Event
from biwak.files import queries as file_queries
from biwak.forms import ColorSwatches, Form, ModelForm, PersonChoiceField
from biwak.items import glance, operations as ops
from biwak.items.models import Item, Kind, Status
from biwak.modals import form_response
from biwak.organizations import operations as org_ops
from biwak.organizations.models import Organization
from biwak.organizations.people import project_groups
from biwak.projects import operations as project_ops
from biwak.projects.models import Project
from biwak.projects.overview import ProjectOrder, overview


def project_for(request, pk):
    """The project if the person may open it, else 404 (limited projects
    don't reveal that they exist)"""
    return get_object_or_404(Project.objects.accessible_to(request.user), pk=pk)


def _list_context(request, archived):
    order = request.GET.get("order")
    if order not in ProjectOrder.values:
        order = ProjectOrder.ACTIVITY
    if archived:
        # A plain alphabetical list, without cards
        projects = Project.objects.accessible_to(request.user).filter(
            archived_at__isnull=False
        )
    else:
        projects = overview(request.user, order)
    return {
        "projects": projects,
        # Admins find every project there, limited ones to join too
        # (specs/handover.md)
        "all_projects": not archived and request.user.is_admin,
        "archived": archived,
        "can_create": project_ops.can_create_project(request.user),
        "order": order,
        "orders": ProjectOrder.choices,
    }


def project_list(request):
    context = _list_context(request, bool(request.GET.get("archived")))
    # Archiving from a project's menu comes here, with the message and Undo
    pk = request.session.pop("archived_project", None)
    if pk:
        context["archived_project"] = (
            Project.objects
            .accessible_to(request.user)
            .filter(pk=pk, archived_at__isnull=False)
            .first()
        )
    return render(request, "projects/project_list.html", context)


class ProjectForm(ModelForm):
    class Meta:
        model = Project
        fields = ["name", "description", "is_all_access", "color"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "color": ColorSwatches,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["color"].choices = [("", _("None")), *Color.choices]
        if not self.instance.pk:
            self.fields["color"].initial = project_ops.suggested_color()


ORGANIZATIONS, PEOPLE = "organizations", "people"


class NewProjectForm(ProjectForm):
    """The new project with the organizations involved (specs/organizations.md):
    first the project and its organizations; with organizations, then their
    people to pick from (all at first), own staff, and
    people without an account to invite (``invites``)."""

    organizations = forms.ModelMultipleChoiceField(
        label=_("Organizations involved"),
        queryset=Organization.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text=_("Next, you pick their people."),
    )
    step = forms.CharField(
        widget=forms.HiddenInput, initial=ORGANIZATIONS, required=False
    )

    def __init__(self, *args, actor, step=None, organizations=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        self.stage = step or self.data.get("step") or ORGANIZATIONS
        self.fields["organizations"].queryset = Organization.objects.filter(
            is_own=False
        )
        if self.stage != PEOPLE:
            return
        if organizations is None:
            organizations = self.fields["organizations"].queryset.filter(
                pk__in=[pk for pk in self.data.getlist("organizations") if pk.isdigit()]
            )
        self.chosen = list(organizations)
        self.fields["organizations"].widget = forms.MultipleHiddenInput()
        people = (
            User.objects
            .active()
            .filter(organization__in=self.chosen)
            .exclude(pk=actor.pk)
            .select_related("organization")
            .order_by(Lower("organization__name"), Lower("full_name"), "email")
        )
        self.fields["people"] = forms.ModelMultipleChoiceField(
            label=_("People of %(organizations)s")
            % {"organizations": ", ".join(str(org) for org in self.chosen)},
            queryset=people,
            required=False,
            widget=forms.CheckboxSelectMultiple,
            initial=list(people),
        )
        self.fields["people"].label_from_instance = lambda user: user.display_name
        self.fields["staff"] = forms.ModelMultipleChoiceField(
            label=_("Staff"),
            queryset=User.objects
            .active()
            .filter(own_staff())
            .exclude(pk=actor.pk)
            .order_by(Lower("full_name"), "email"),
            required=False,
            widget=forms.CheckboxSelectMultiple,
            help_text=_("You're a member anyway."),
        )
        self.invites = InviteRows(
            self.data or None,
            prefix="invite",
            form_kwargs={"organizations": self.chosen},
        )

    def is_valid(self):
        valid = super().is_valid()
        if self.stage == PEOPLE:
            return self.invites.is_valid() and valid
        return valid


class InviteRow(Form):
    """Somebody without an account, invited as a client"""

    email = forms.EmailField(
        label=_("Email"),
        required=False,
        widget=forms.EmailInput(attrs={"placeholder": _("Email")}),
    )
    full_name = forms.CharField(
        label=_("Name"),
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": _("Name")}),
    )
    organization = forms.ModelChoiceField(
        label=_("Organization"),
        queryset=Organization.objects.none(),
        required=False,
        empty_label=_("By the address's domain"),
    )

    def __init__(self, *args, organizations, **kwargs):
        super().__init__(*args, **kwargs)
        self.chosen = organizations
        self.fields["organization"].queryset = Organization.objects.filter(
            pk__in=[org.pk for org in organizations]
        )

    def clean(self):
        data = super().clean()
        if (
            data.get("email")
            and not data.get("organization")
            and org_ops.for_new_person(data["email"]) is None
            and len(self.chosen) == 1
        ):
            # No domain matching: the only one involved. The domain's is
            # ``invite()``'s, which drops it where the actor may not put
            # people (the own or an external organization, for staff), as on
            # the invite page and in the API
            data["organization"] = self.chosen[0]
        return data


InviteRows = forms.formset_factory(InviteRow, extra=3)


def project_create(request):
    """A modal in two steps (specs/organizations.md), also a page: without
    organizations involved, the project is added at once"""
    if not project_ops.can_create_project(request.user):
        raise PermissionDenied
    form = NewProjectForm(request.POST or None, actor=request.user)
    if form.is_valid():
        data = form.cleaned_data
        if form.stage == ORGANIZATIONS and data["organizations"]:
            form = NewProjectForm(
                initial={**dict(data.items()), "step": PEOPLE},
                actor=request.user,
                step=PEOPLE,
                organizations=data["organizations"],
            )
        else:
            try:
                with transaction.atomic():
                    project = project_ops.create_project(
                        actor=request.user,
                        **{
                            field: data[field]
                            for field in [
                                "name",
                                "description",
                                "is_all_access",
                                "color",
                            ]
                        },
                    )
                    for user in [*data.get("people", []), *data.get("staff", [])]:
                        project_ops.add_member(project, user, actor=request.user)
                    for row in (
                        form.invites.cleaned_data if form.stage == PEOPLE else []
                    ):
                        if row.get("email"):
                            project_ops.invite(
                                project,
                                email=row["email"],
                                full_name=row["full_name"],
                                organization=row["organization"],
                                actor=request.user,
                            )
            except project_ops.InvitationError as exc:
                form.add_error(None, str(exc))
            else:
                return redirect(project)
    return form_response(
        request,
        form,
        title=_("New project"),
        cancel_url=reverse("projects"),
        submit_label=_("Continue") if form.stage == ORGANIZATIONS else _("Add project"),
        template="projects/project_new.html",
    )


@require_POST
def project_join(request, pk):
    """Staff join all-access projects, admins also limited ones (recorded:
    specs/access.md); joining subscribes to nothing that exists already"""
    if request.user.is_client:
        raise PermissionDenied
    project = get_object_or_404(project_ops.projects_to_join(request.user), pk=pk)
    project_ops.add_member(project, request.user, actor=request.user)
    return redirect(project)


NOTIFY_LABELS = {
    project_ops.NOTIFY_DEFAULT: _("Notified by default"),
    project_ops.NOTIFY_TAGGED: _("Only when tagged"),
}


def notify_field():
    """How the person is in the project (specs/notifications.md)"""
    return forms.ChoiceField(
        label=_("Notifications"),
        choices=[
            (project_ops.NOTIFY_DEFAULT, NOTIFY_LABELS[project_ops.NOTIFY_DEFAULT]),
            (project_ops.NOTIFY_TAGGED, NOTIFY_LABELS[project_ops.NOTIFY_TAGGED]),
        ],
        initial=project_ops.NOTIFY_DEFAULT,
        widget=forms.RadioSelect,
        help_text=_(
            "Only when tagged: posts to everybody don't subscribe the person;"
            " mentions and assignments still reach them."
        ),
    )


class AddMemberForm(Form):
    user = PersonChoiceField(
        label=_("Person"), queryset=User.objects.none(), with_address=True
    )
    notify = notify_field()


def notify_row(actor, project, user):
    """How the person is in the project, for staff and the person themselves"""
    if not project_ops.can_change_notify_choice(actor, user):
        return None
    choice = project_ops.notify_choice(user, project)
    return {"value": choice, "label": NOTIFY_LABELS[choice]}


class NotifyForm(Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["notify"] = notify_field()


def member_notify(request, pk, user_pk):
    """Notified by default or only when tagged: a modal from the row's "…"
    menu (decided 2026-11-22). Staff change anybody's choice, a client only
    their own"""
    project = project_for(request, pk)
    user = get_object_or_404(User, pk=user_pk, memberships__project=project)
    if not project_ops.can_change_notify_choice(request.user, user):
        raise PermissionDenied
    choice = project_ops.notify_choice(user, project)
    form = NotifyForm(request.POST or None, initial={"notify": choice})
    if form.is_valid():
        project_ops.set_notify_choice(
            project, user, form.cleaned_data["notify"], actor=request.user
        )
        messages.success(request, _("The choice has been saved."))
        return redirect("project_people", pk=project.pk)
    if user == request.user:
        title = _("Your notifications")
    else:
        title = _("Notifications of %(name)s") % {"name": user.display_name}
    return form_response(
        request,
        form,
        title=title,
        project=project,
        cancel_url=reverse("project_people", args=[project.pk]),
        submit_label=_("Save"),
        help_page="notifications",
    )


def project_people(request, pk):
    """Members by organization (``project_groups()``); staff add (also from
    an organization), invite (modals) and remove people, and see who
    hasn't signed in yet (specs/activation.md, "Invitations")"""
    project = project_for(request, pk)
    can_manage = project_ops.can_manage_members(request.user)
    memberships = list(
        project.memberships.select_related(
            "user__organization", "user__invited_by"
        ).order_by(Lower("user__full_name"), "user__email")
    )
    for m in memberships:
        m.user.show_invitation = can_manage and m.user.is_invited
        m.user.manage_invitation = project_ops.can_manage_invitation(
            request.user, m.user
        )
    rows = [(m, notify_row(request.user, project, m.user)) for m in memberships]
    return render(
        request,
        "projects/people.html",
        {
            "project": project,
            "groups": project_groups(
                project, rows, can_add=can_manage, viewer=request.user
            ),
            "notify_choices": [
                (value, NOTIFY_LABELS[value]) for value in project_ops.NOTIFY_CHOICES
            ],
            "can_manage": project_ops.can_manage_members(request.user),
            "can_add": project_ops.can_manage_members(request.user)
            and project_ops.addable_people(project).exists(),
        },
    )


def member_add(request, pk):
    """Adds somebody who has an account: a modal, also a page; with
    ``?organization=ID`` somebody of that organization ("Add people from
    …" on the people page), preselected when they're the only one"""
    project = project_for(request, pk)
    if not project_ops.can_manage_members(request.user):
        raise PermissionDenied
    people = project_ops.addable_people(project)
    title = _("Add someone")
    if organization := request.GET.get("organization"):
        if not organization.isdigit():
            raise Http404
        organization = get_object_or_404(Organization, pk=organization)
        people = people.filter(organization=organization)
        title = _("Add people from %(organization)s") % {"organization": organization}
    initial = {}
    if organization and len(found := list(people[:2])) == 1:
        initial["user"] = found[0]
    form = AddMemberForm(request.POST or None, initial=initial)
    form.fields["user"].queryset = people
    if form.is_valid():
        user = form.cleaned_data["user"]
        project_ops.add_member(
            project, user, actor=request.user, notify=form.cleaned_data["notify"]
        )
        messages.success(
            request, _("%(name)s has been added.") % {"name": user.display_name}
        )
        return redirect("project_people", pk=project.pk)
    return form_response(
        request,
        form,
        title=title,
        project=project,
        cancel_url=reverse("project_people", args=[project.pk]),
        submit_label=_("Add"),
    )


def member_remove(request, pk, user_pk):
    """Own staff remove anybody, themselves included; clients and externals
    nobody, not even themselves (decided 2026-11-22: notifications cover
    not hearing about a project, and the organization decides who works
    on it). GET asks, POST removes. Non-members are 404 like IDs nobody
    has (as in the API): nothing said about who exists"""
    project = project_for(request, pk)
    user = get_object_or_404(User, pk=user_pk, memberships__project=project)
    if not project_ops.can_manage_members(request.user):
        raise PermissionDenied
    if request.method == "POST":
        project_ops.remove_member(project, user, actor=request.user)
        if user == request.user:
            return redirect("projects")
        return redirect("project_people", pk=project.pk)
    # Own staff see all-access projects without being members
    keeps_access = project.is_all_access and user.sees_all_access
    if user == request.user:
        title = _("Remove yourself from %(project)s?") % {"project": project.name}
        intro = (
            _("You still see it, as all staff see all-access projects.")
            if keeps_access
            else _("You won't see it any more.")
        )
        intro += " " + _("Open to-dos in it assigned to you lose you as assignee.")
    else:
        name = user.full_name or user.email
        title = _("Remove %(name)s from %(project)s?") % {
            "name": name,
            "project": project.name,
        }
        intro = (
            _("%(name)s still sees the project, as all staff see all-access projects.")
            if keeps_access
            else _("%(name)s won't see the project or hear about it any more.")
        ) % {"name": name}
        intro += " " + _(
            "Open to-dos in it assigned to %(name)s lose %(name)s as assignee."
        ) % {"name": name}
    return form_response(
        request,
        None,
        title=title,
        intro=intro,
        project=project,
        cancel_url=reverse("project_people", args=[project.pk]),
        submit_label=_("Remove"),
        destructive=True,
    )


class ListForm(Form):
    title = forms.CharField(label=_("title"), max_length=500)
    visible = forms.BooleanField(label=_("Visible to clients"), required=False)


def project_edit(request, pk):
    project = project_for(request, pk)
    if not project_ops.can_manage_project(request.user):
        raise PermissionDenied
    # The form validates a copy: update_project() compares with the project
    form = ProjectForm(request.POST or None, instance=Project.objects.get(pk=pk))
    if form.is_valid():
        project_ops.update_project(project, actor=request.user, **form.cleaned_data)
        return redirect(project)
    return form_response(
        request,
        form,
        title=_("Edit the project"),
        project=project,
        cancel_url=project.get_absolute_url(),
        # Its name and description are what the project's clients see too
        extra={
            "clients_see": project.memberships.filter(
                user__is_client=True, user__is_active=True
            ).exists()
        },
    )


@require_POST
def project_archive(request, pk):
    """Archives or (``unarchive``) brings the project back, from the
    project's "More" menu. Archiving goes to the projects page, which says
    "Archived Website." with an Undo (``undo`` marks the Undo itself, which
    says nothing); bringing back goes to the project."""
    project = project_for(request, pk)
    if not project_ops.can_manage_project(request.user):
        raise PermissionDenied
    if request.POST.get("unarchive"):
        project_ops.unarchive_project(project, actor=request.user)
        if request.POST.get("undo"):
            return redirect("projects")
        return redirect(project)
    project_ops.archive_project(project, actor=request.user)
    request.session["archived_project"] = project.pk
    return redirect("projects")


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


def list_new(request, pk):
    """A new list: a modal on the project's page, also a page of its own"""
    project = project_for(request, pk)
    if not ops.can_create(request.user, Kind.LIST):
        raise PermissionDenied
    form = ListForm(request.POST or None)
    if form.is_valid():
        item = ops.create_list(
            project=project,
            title=form.cleaned_data["title"],
            creator=request.user,
            visible=form.cleaned_data["visible"],
        )
        return redirect(item)
    return form_response(
        request,
        form,
        title=_("New list"),
        project=project,
        cancel_url=project.get_absolute_url(),
        submit_label=_("Add list"),
    )


def project_detail(request, pk):
    project = project_for(request, pk)
    items = Item.objects.visible_to(request.user).filter(project=project)
    all_lists = items.filter(kind=Kind.LIST, parent=None)
    lists = all_lists.filter(status=Status.ACTIVE).select_related("project")
    lists = list(lists)
    archived_lists = list(all_lists.filter(status=Status.ARCHIVED))
    counts = glance.list_counts(request.user, lists, schedules.today())
    for todolist in lists:
        todolist.open_count, todolist.overdue_count = counts.get(todolist.pk, (0, 0))
    events = list(
        Event.objects
        .visible_to(request.user)
        .filter(project=project)
        .exclude(action=Action.REACTED)
        .select_related("actor", "project", "item__answer")[:20]
    )
    feed.attach(events, request.user)
    return render(
        request,
        "projects/project_detail.html",
        {
            "project": project,
            "lists": lists,
            "archived_lists": archived_lists,
            "can_manage": project_ops.can_manage_project(request.user),
            "can_create_lists": ops.can_create(request.user, Kind.LIST),
            "members": project.memberships.select_related("user"),
            "front_messages": file_queries.front_messages(project, request.user),
            "front_files": file_queries.front_files(project, request.user),
            "root_counts": file_queries.root_counts(project, request.user),
            "is_member": project.is_member(request.user),
            "events": events,
        },
    )
