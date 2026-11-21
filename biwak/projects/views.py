from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models.functions import Lower
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_POST

from biwak import schedules
from biwak.accounts.models import Color, User, own_staff
from biwak.activity import feed
from biwak.activity.models import Action, Event
from biwak.files import queries as file_queries
from biwak.forms import Form, ModelForm
from biwak.items import glance, operations as ops
from biwak.items.models import Item, Kind, Status
from biwak.modals import form_response
from biwak.organizations import operations as org_ops
from biwak.organizations.forms import OrganizationFieldMixin, organization_field
from biwak.organizations.models import Organization
from biwak.projects import operations as project_ops
from biwak.projects.models import Project
from biwak.projects.overview import overview


def project_for(request, pk):
    """The project if the person may open it, else 404 (limited projects
    don't reveal that they exist)"""
    return get_object_or_404(Project.objects.accessible_to(request.user), pk=pk)


def _list_context(request, archived):
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
            others = project_ops.joinable_projects(request.user)
    return {
        "projects": projects,
        "others": others,
        "archived": archived,
        "can_manage": project_ops.can_manage_project(request.user),
        "can_create": project_ops.can_create_project(request.user),
        "order": request.user.project_order,
        "orders": User.ProjectOrder.choices,
    }


def project_list(request):
    return render(
        request,
        "projects/project_list.html",
        _list_context(request, bool(request.GET.get("archived"))),
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
        fields = ["name", "description", "is_all_access", "color"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["color"].choices = [("", _("None")), *Color.choices]
        if not self.instance.pk:
            self.fields["color"].initial = project_ops.suggested_color()


ORGANIZATIONS, PEOPLE = "organizations", "people"


class NewProjectForm(ProjectForm):
    """The new project with the organizations involved (specs/organizations.md):
    first the project and its organizations; with organizations, then their
    people to pick from (all at first), the installation's own staff, and
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
        if data.get("email") and not data.get("organization"):
            # The domain's, else the only one involved
            found = org_ops.for_new_person(data["email"])
            if found is None and len(self.chosen) == 1:
                found = self.chosen[0]
            data["organization"] = found
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
    "nothing": _("No mails"),
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
            "Only when tagged: mails about posts to everybody are held back"
            " unless the person is mentioned or assigned."
        ),
    )


class AddMemberForm(Form):
    user = forms.ModelChoiceField(label=_("Person"), queryset=User.objects.none())
    notify = notify_field()


class InviteForm(OrganizationFieldMixin, Form):
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
    notify = notify_field()
    organization = organization_field(
        help_text=_(
            "For new people; left empty, the organization of the address's"
            " domain. Shown beside the names of clients and partners. No"
            " organization: staff see only the projects they're added to."
        ),
    )

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        if not actor.is_admin:
            # Only admins create staff (specs/access.md)
            del self.fields["is_client"]


def notify_row(actor, project, user):
    """How the person is in the project, for staff and the person themselves"""
    if not project_ops.can_change_notify_choice(actor, user):
        return None
    choice = project_ops.notify_choice(user, project)
    return {"value": choice, "label": NOTIFY_LABELS[choice]}


@require_POST
def member_notify(request, pk, user_pk):
    """Staff change anybody's choice, a client only their own"""
    project = project_for(request, pk)
    user = get_object_or_404(User, pk=user_pk, memberships__project=project)
    if not project_ops.can_change_notify_choice(request.user, user):
        raise PermissionDenied
    notify = request.POST.get("notify")
    if notify not in project_ops.NOTIFY_CHOICES:
        return HttpResponse(status=400)
    project_ops.set_notify_choice(project, user, notify, actor=request.user)
    messages.success(request, _("The choice has been saved."))
    return redirect("project_people", pk=project.pk)


def project_people(request, pk):
    """Members; staff add, invite (modals) and remove people"""
    project = project_for(request, pk)
    return render(
        request,
        "projects/people.html",
        {
            "project": project,
            "memberships": [
                (m, notify_row(request.user, project, m.user))
                for m in project.memberships.select_related(
                    "user__organization"
                ).order_by("user__is_client", "user__full_name")
            ],
            "notify_choices": [
                (value, NOTIFY_LABELS[value]) for value in project_ops.NOTIFY_CHOICES
            ],
            "can_manage": project_ops.can_manage_members(request.user),
            "can_add": project_ops.can_manage_members(request.user)
            and project_ops.addable_people(project).exists(),
        },
    )


def member_add(request, pk):
    """Adds somebody who has an account: a modal, also a page"""
    project = project_for(request, pk)
    if not project_ops.can_manage_members(request.user):
        raise PermissionDenied
    form = AddMemberForm(request.POST or None)
    form.fields["user"].queryset = project_ops.addable_people(project)
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
        title=_("Add someone"),
        project=project,
        cancel_url=reverse("project_people", args=[project.pk]),
        submit_label=_("Add"),
    )


def member_invite(request, pk):
    """Invites by email: a modal, also a page"""
    project = project_for(request, pk)
    if not project_ops.can_manage_members(request.user):
        raise PermissionDenied
    form = InviteForm(request.POST or None, actor=request.user)
    if form.is_valid():
        data = form.cleaned_data
        try:
            # A new organization only with the invitation
            with transaction.atomic():
                user, _changed = project_ops.invite(
                    project,
                    email=data["email"],
                    full_name=data["full_name"],
                    is_client=data.get("is_client", True),
                    organization=form.organization(request.user),
                    notify=data["notify"],
                    actor=request.user,
                )
        except project_ops.InvitationError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(
                request,
                _("%(name)s has been invited.") % {"name": user.display_name},
            )
            return redirect("project_people", pk=project.pk)
    return form_response(
        request,
        form,
        title=_("Invite by email"),
        intro=_(
            "New people get a mail and log in with a code sent to their address."
            " Adding someone subscribes them to nothing that exists already."
        ),
        project=project,
        cancel_url=reverse("project_people", args=[project.pk]),
        submit_label=_("Invite"),
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
    )


@require_POST
def project_archive(request, pk):
    """Archives or (``unarchive``) brings the project back.

    From the projects page (``list`` is ``active`` or ``archived``: which of
    the two it shows) htmx gets the page's content again, with "Archived. Undo"
    (``undo`` marks the Undo itself, which says nothing); without htmx the
    projects page loads again. From the project's page it's a redirect."""
    project = project_for(request, pk)
    if not project_ops.can_manage_project(request.user):
        raise PermissionDenied
    unarchive = bool(request.POST.get("unarchive"))
    if unarchive:
        project_ops.unarchive_project(project, actor=request.user)
    else:
        project_ops.archive_project(project, actor=request.user)
    shown = request.POST.get("list")
    if shown not in {"active", "archived"}:
        return redirect(project)
    archived = shown == "archived"
    if not request.headers.get("HX-Request"):
        return redirect(reverse("projects") + ("?archived=1" if archived else ""))
    context = _list_context(request, archived)
    if not request.POST.get("undo"):
        context["message"] = {
            "text": _("Brought back.") if unarchive else _("Archived."),
            "project": project,
            "unarchive": not unarchive,
        }
    return render(request, "projects/_page.html", context)


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
            "archived_lists": all_lists.filter(status=Status.ARCHIVED),
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
