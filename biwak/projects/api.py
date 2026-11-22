"""Projects and their members (biwak projects)"""

import datetime as dt
from typing import Literal

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Exists, OuterRef
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _
from ninja import Router, Schema, Status
from ninja.errors import HttpError

from biwak.accounts.models import Color, User
from biwak.api_conventions import PersonOut, absolute, html, person_out
from biwak.bookmarks.models import Bookmark
from biwak.organizations.models import Organization
from biwak.projects import operations as project_ops
from biwak.projects.models import Project
from biwak.projects.overview import activity_column, overview
from biwak.projects.views import project_for


router = Router(tags=["projects"])


class ProjectOut(Schema):
    id: int
    name: str
    description: str
    description_html: str
    is_all_access: bool
    is_member: bool
    is_bookmarked: bool
    # A name of the palette (heather, lake, ...) or empty, with its label
    color: Color | Literal[""]
    color_name: str
    # When something last happened in the project: what the person can see
    # of it, so for clients only the activity on items visible to clients
    last_activity_at: dt.datetime | None
    archived_at: dt.datetime | None
    # A template (specs/templates.md): new projects start as a copy of it
    is_template: bool
    url: str


def project_out(project, user):
    """``project`` from ``overview()`` brings its annotations, otherwise
    they cost a query each"""
    is_bookmarked = getattr(project, "is_bookmarked", None)
    if is_bookmarked is None:
        is_bookmarked = Bookmark.objects.filter(user=user, project=project).exists()
    is_member = getattr(project, "user_is_member", None)
    if is_member is None:
        is_member = project.is_member(user)
    return {
        "id": project.pk,
        "name": project.name,
        "description": project.description,
        "description_html": html(project.description),
        "is_all_access": project.is_all_access,
        "is_member": is_member,
        "is_bookmarked": is_bookmarked,
        "color": project.color,
        "color_name": project.color_label,
        "last_activity_at": getattr(
            project, "activity", getattr(project, activity_column(user))
        ),
        "archived_at": project.archived_at,
        "is_template": project.is_template,
        "url": absolute(project.get_absolute_url()),
    }


@router.get("projects/", response=list[ProjectOut])
def project_list(
    request,
    *,
    archived: bool = False,
    order: Literal["activity", "name"] | None = None,
    templates: bool = False,
):
    """The projects the person can open, active ones unless ``archived``:
    bookmarked ones first, then by ``order`` (activity by
    default), the latest activity first or by name. Archived ones by name,
    bookmarked ones first. ``templates``: the templates instead (own staff;
    the archived ones with ``archived``), by name."""
    if templates:
        projects = (
            Project.objects
            .accessible_to(request.user)
            .templates()
            .filter(archived_at__isnull=not archived)
            .order_by(Lower("name"), "pk")
        )
        if not project_ops.can_use_templates(request.user):
            projects = projects.none()
    elif archived:
        projects = Project.objects.accessible_to(request.user).filter(
            archived_at__isnull=False, is_template=False
        )
        projects = projects.annotate(
            is_bookmarked=Exists(
                Bookmark.objects.filter(user=request.user, project=OuterRef("pk"))
            )
        ).order_by("-is_bookmarked", Lower("name"), "pk")
    else:
        projects = overview(request.user, order)
    return [project_out(project, request.user) for project in projects]


class JoinableOut(Schema):
    id: int
    name: str


@router.get("projects/joinable/", response=list[JoinableOut])
def project_joinable(request):
    """Limited projects the person isn't in, which only admins see exist and
    can join, as on the projects page; empty for everybody else"""
    return [
        {"id": p.pk, "name": p.name}
        for p in project_ops.joinable_projects(request.user).order_by(Lower("name"))
    ]


class AllProjectOut(Schema):
    id: int
    name: str
    is_all_access: bool
    archived: bool
    # Whether the admin can open it, and whether they can join it
    can_open: bool
    joinable: bool
    active_staff: int
    client_organizations: list[str]
    open_todos: int
    # Open to-dos whose assignees are all inactive
    inactive_todos: int
    last_activity_at: dt.datetime | None
    # Only for projects the admin can open
    url: str | None


@router.get("projects/all/", response=list[AllProjectOut])
def project_all(
    request,
    *,
    no_staff: bool = False,
    limited: bool = False,
    inactive: bool = False,
    archived: bool = False,
):
    """Every project, for admins (specs/handover.md), by name: counts only,
    the filters of the page; 403 for everybody else"""
    from biwak.projects.all_projects import all_projects, can_see

    if not can_see(request.user):
        raise HttpError(403, _("Only admins see all projects."))
    return [
        {
            "id": p.pk,
            "name": p.name,
            "is_all_access": p.is_all_access,
            "archived": p.archived_at is not None,
            "can_open": p.can_open,
            "joinable": p.joinable,
            "active_staff": p.active_staff,
            "client_organizations": p.client_organizations,
            "open_todos": p.open_todos,
            "inactive_todos": p.inactive_todos,
            "last_activity_at": p.last_activity_at,
            "url": absolute(p.get_absolute_url()) if p.can_open else None,
        }
        for p in all_projects(
            request.user,
            no_staff=no_staff,
            limited=limited,
            inactive=inactive,
            archived=archived,
        )
    ]


class ProjectIn(Schema):
    name: str
    description: str = ""
    is_all_access: bool = True
    # Left out: a suggested color no other active project has; "": none
    color: Color | Literal[""] | None = None
    # A template's ID: the new project gets a copy of it (specs/templates.md)
    template: int | None = None
    # People added as members before the template is copied: its assignees
    # who don't see the new project are left out
    member_ids: list[int] = []
    # A new template instead of a project (all-access, without members)
    is_template: bool = False


@router.post("projects/", response={201: ProjectOut})
def project_create(request, data: ProjectIn):
    """Creates the project (staff); the creator becomes a member, and so
    do ``member_ids``. With ``template``, a copy of the template's lists,
    messages, folders, docs and files; with ``is_template``, a template"""
    if not project_ops.can_create_project(request.user):
        raise HttpError(403, _("Only staff can create projects."))
    if data.is_template:
        if data.template is not None or data.member_ids:
            raise HttpError(400, _("Templates have no members."))
        project = project_ops.create_template(
            name=data.name,
            description=data.description,
            color=data.color or "",
            actor=request.user,
        )
        return Status(201, project_out(project, request.user))
    template = None
    if data.template is not None:
        template = get_object_or_404(
            Project.objects.accessible_to(request.user).templates(),
            pk=data.template,
            archived_at__isnull=True,
        )
    members = list(User.objects.active().filter(pk__in=data.member_ids))
    if len(members) != len(set(data.member_ids)):
        raise HttpError(400, _("Only active people can be added."))
    with transaction.atomic():
        project = project_ops.create_project(
            name=data.name,
            description=data.description,
            is_all_access=data.is_all_access,
            color=data.color,
            actor=request.user,
        )
        for user in members:
            project_ops.add_member(project, user, actor=request.user)
        if template is not None:
            project_ops.fill_from_template(project, template, actor=request.user)
    return Status(201, project_out(project, request.user))


@router.post("projects/{project_id}/join/", response=ProjectOut)
def project_join(request, project_id: int):
    """Staff join the projects they can open, admins also limited ones
    (recorded as ``joined``); joining twice changes nothing"""
    if request.user.is_client:
        raise HttpError(403, _("Only staff can join projects."))
    project = get_object_or_404(
        project_ops.projects_to_join(request.user), pk=project_id
    )
    project_ops.add_member(project, request.user, actor=request.user)
    return project_out(project, request.user)


@router.get("projects/{project_id}/", response=ProjectOut)
def project_detail(request, project_id: int):
    return project_out(project_for(request, project_id), request.user)


class MemberOut(PersonOut):
    email: str | None
    # How the person is in the project: "default" (notified by default) or
    # "tagged" (only when tagged). Only for staff and for yourself, else null.
    notify: str | None


Notify = Literal["default", "tagged"]


def member_out(project, user, actor):
    notify = None
    if project_ops.can_change_notify_choice(actor, user):
        notify = project_ops.notify_choice(user, project)
    return person_out(user) | {
        "email": None if actor.is_client else user.email,
        "notify": notify,
    }


@router.get("projects/{project_id}/members/", response=list[MemberOut])
def project_members(request, project_id: int):
    """Members; addresses and everybody's choice only for staff, like on the
    people page"""
    project = project_for(request, project_id)
    return [
        member_out(project, m.user, request.user)
        for m in project.memberships.select_related("user__organization").order_by(
            "user__is_client", "user__full_name"
        )
    ]


def staff_only(request):
    if not project_ops.can_manage_members(request.user):
        raise HttpError(403, _("Only staff can add people."))


def no_template(project):
    if project.is_template:
        raise HttpError(400, _("Templates have no members."))


class MemberIn(Schema):
    person_id: int
    notify: Notify = "default"


@router.post("projects/{project_id}/members/", response={201: MemberOut})
def member_add(request, project_id: int, data: MemberIn):
    """Adds an active person (staff). ``notify`` is stored as their choice
    unless they have one already."""
    project = project_for(request, project_id)
    staff_only(request)
    no_template(project)
    user = User.objects.active().filter(pk=data.person_id).first()
    if user is None:
        raise HttpError(404, _("Not found."))
    project_ops.add_member(project, user, actor=request.user, notify=data.notify)
    return Status(201, member_out(project, user, request.user))


class InviteIn(Schema):
    email: str
    name: str = ""
    # Only admins create staff
    is_client: bool = True
    # For new people: the organization by ID or by name (existing ones,
    # ignoring case and spaces); neither: the one of the address's domain
    organization_id: int | None = None
    organization: str = ""
    notify: Notify = "default"


def invitee_organization(data):
    """The organization an invitation names (``organization_id`` or an
    existing ``organization`` by name), else None; ``ValueError`` for an
    invalid address or an unknown organization"""
    try:
        validate_email(data.email)
    except ValidationError as exc:
        raise ValueError(_("Enter a valid email address.")) from exc
    organization = None
    if data.organization_id is not None:
        organization = Organization.objects.filter(pk=data.organization_id).first()
    elif data.organization.strip():
        organization = Organization.objects.named(data.organization)
    if organization is None and (
        data.organization_id is not None or data.organization.strip()
    ):
        raise ValueError(_("No such organization."))
    return organization


@router.post("projects/{project_id}/members/invite/", response={201: MemberOut})
def member_invite(request, project_id: int, data: InviteIn):
    """Adds a person by address, creating and mailing them if they're new
    (staff)"""
    project = project_for(request, project_id)
    staff_only(request)
    no_template(project)
    try:
        organization = invitee_organization(data)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    try:
        user, _changed = project_ops.invite(
            project,
            email=data.email,
            full_name=data.name,
            is_client=data.is_client,
            organization=organization,
            notify=data.notify,
            actor=request.user,
        )
    except project_ops.InvitationError as exc:
        raise HttpError(400, str(exc)) from exc
    return Status(201, member_out(project, user, request.user))


@router.delete("projects/{project_id}/members/{person_id}/", response=MemberOut)
def member_remove(request, project_id: int, person_id: int):
    """Own staff remove anybody, themselves included; clients and externals
    get 403, for themselves too (decided 2026-11-22); returns the person
    removed"""
    project = project_for(request, project_id)
    user = get_object_or_404(User, pk=person_id, memberships__project=project)
    if not project_ops.can_manage_members(request.user):
        raise HttpError(403, _("Only staff can remove people."))
    out = member_out(project, user, request.user)
    project_ops.remove_member(project, user, actor=request.user)
    return out


class MemberPatch(Schema):
    notify: Notify


@router.patch("projects/{project_id}/members/{person_id}/", response=MemberOut)
def member_update(request, project_id: int, person_id: int, data: MemberPatch):
    """Changes how the person is in the project: staff anybody's, clients
    only their own (403 for others)"""
    project = project_for(request, project_id)
    user = get_object_or_404(User, pk=person_id, memberships__project=project)
    if not project_ops.can_change_notify_choice(request.user, user):
        raise HttpError(403, _("You can only change your own choice."))
    project_ops.set_notify_choice(project, user, data.notify, actor=request.user)
    return member_out(project, user, request.user)


class ProjectPatch(Schema):
    name: str | None = None
    description: str | None = None
    is_all_access: bool | None = None
    color: Color | Literal[""] | None = None
    archived: bool | None = None


@router.patch("projects/{project_id}/", response=ProjectOut)
def project_update(request, project_id: int, data: ProjectPatch):
    """Staff change the fields given; ``archived`` archives the project or
    brings it back"""
    project = project_for(request, project_id)
    if not project_ops.can_manage_project(request.user):
        raise HttpError(403, _("Only staff can change projects."))
    given = data.model_fields_set
    changes = {
        field: getattr(data, field)
        for field in ["name", "description", "is_all_access", "color"]
        if field in given
    }
    for field, value in changes.items():
        if value is None or (field == "name" and not value.strip()):
            raise HttpError(400, _("%(field)s can't be empty.") % {"field": field})
    try:
        project_ops.update_project(project, actor=request.user, **changes)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    if "archived" in given and data.archived != bool(project.archived_at):
        if data.archived:
            project_ops.archive_project(project, actor=request.user)
        else:
            project_ops.unarchive_project(project, actor=request.user)
    return project_out(project, request.user)


# Inviting several people at once, and the invitations (specs/activation.md, "Inviting")


class InvitationPersonIn(Schema):
    email: str
    name: str = ""
    # Only admins create staff
    is_client: bool = True
    # For new people: the organization by ID or by name (existing ones);
    # neither: the one of the address's domain
    organization_id: int | None = None
    organization: str = ""


class InvitationsIn(Schema):
    people: list[InvitationPersonIn]
    projects: list[int]
    # The choice for every project
    notify: Notify = "default"


class InvitedOut(Schema):
    person: PersonOut
    email: str
    # A new person, mailed the invitation; else they had an account
    created: bool
    # The projects they weren't in yet
    added_to: list[int]


class RowError(Schema):
    index: int
    detail: str


class InvitationErrorsOut(Schema):
    detail: str
    errors: list[RowError]


def _row_errors(errors, data):
    """400 with each row's error; ``detail`` names the addresses too (the
    CLI shows it)"""
    rows = "; ".join(
        f"{data.people[index].email}: {message}"
        for index, message in sorted(errors.items())
    )
    return Status(
        400,
        {
            "detail": _("Nobody has been invited. %(errors)s") % {"errors": rows},
            "errors": [
                {"index": index, "detail": message}
                for index, message in sorted(errors.items())
            ],
        },
    )


@router.post("invitations/", response={201: list[InvitedOut], 400: InvitationErrorsOut})
def invitations_create(request, data: InvitationsIn):
    """Invites several people to several projects at once (own staff): new
    people get one mail naming the projects, people with an account are
    added. All or nothing: 400 with each refused row's ``index``."""
    staff_only(request)
    if not data.people:
        raise HttpError(400, _("Nobody to invite."))
    projects = list(
        Project.objects
        .accessible_to(request.user)
        .active()
        .filter(pk__in=data.projects)
    )
    # In the order given
    projects.sort(key=lambda project: data.projects.index(project.pk))
    if not data.projects or len(projects) != len(set(data.projects)):
        raise HttpError(404, _("Not found."))
    people, errors = [], {}
    for index, row in enumerate(data.people):
        try:
            organization = invitee_organization(row)
        except ValueError as exc:
            errors[index] = str(exc)
            organization = None
        people.append({
            "email": row.email,
            "full_name": row.name,
            "is_client": row.is_client,
            "organization": organization,
        })
    if errors:
        return _row_errors(errors, data)
    try:
        invited = project_ops.invite_people(
            projects, people, actor=request.user, notify=data.notify
        )
    except project_ops.InvitationErrors as exc:
        return _row_errors(exc.errors, data)
    return Status(
        201,
        [
            {
                "person": person_out(person.user),
                "email": person.user.email,
                "created": person.created,
                "added_to": [project.pk for project in person.added_to],
            }
            for person in invited
        ],
    )


class InvitationOut(Schema):
    person: PersonOut
    email: str
    invited_by: PersonOut | None
    invited_at: dt.datetime
    # The projects they're in now, which a resent invitation names
    project_ids: list[int]


def invitation_out(user):
    return {
        "person": person_out(user),
        "email": user.email,
        "invited_by": person_out(user.invited_by),
        "invited_at": user.invited_at,
        "project_ids": [p.pk for p in project_ops.invitation_projects(user)],
    }


def invitation_for(request, person_id):
    if not project_ops.can_manage_members(request.user):
        raise HttpError(403, _("Only staff manage invitations."))
    user = get_object_or_404(
        User.objects.invited().select_related("organization", "invited_by"),
        pk=person_id,
    )
    if not project_ops.can_manage_invitation(request.user, user):
        raise HttpError(403, _("Only admins manage invitations of staff."))
    return user


@router.get("invitations/", response=list[InvitationOut])
def invitations_list(request):
    """Everybody invited who hasn't signed in yet, the oldest invitation
    first (own staff)"""
    if not project_ops.can_manage_members(request.user):
        raise HttpError(403, _("Only staff manage invitations."))
    return [
        invitation_out(user)
        for user in User.objects.invited().select_related("organization", "invited_by")
    ]


@router.post("invitations/{person_id}/resend/", response=InvitationOut)
def invitation_resend(request, person_id: int):
    """Sends the invitation mail again, naming the projects the person is
    in now"""
    user = invitation_for(request, person_id)
    project_ops.resend_invitation(user, actor=request.user)
    return invitation_out(user)


class WithdrawnOut(Schema):
    # Removed from all their projects (decided 2026-11-21): these are the
    # ones the withdrawing person can open,
    removed_from: list[int]
    # and this many others, not named
    removed_from_others: int
    # The account went too: nothing else referred to it
    deleted: bool
    # The account stays deactivated: something referred to it
    deactivated: bool


@router.delete("invitations/{person_id}/", response=WithdrawnOut)
def invitation_withdraw(request, person_id: int):
    """Withdraws the invitation while the person hasn't signed in: removed
    from all their projects, the account deleted or deactivated"""
    user = invitation_for(request, person_id)
    withdrawn = project_ops.withdraw_invitation(user, actor=request.user)
    removed_from, others = withdrawn.for_actor(request.user)
    return {
        "removed_from": [p.pk for p in removed_from],
        "removed_from_others": others,
        "deleted": withdrawn.deleted,
        "deactivated": withdrawn.deactivated,
    }
