"""Projects and their members (biwak projects)"""

import datetime as dt
from typing import Literal

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
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
        "url": absolute(project.get_absolute_url()),
    }


@router.get("projects/", response=list[ProjectOut])
def project_list(
    request,
    *,
    archived: bool = False,
    order: Literal["activity", "name"] | None = None,
):
    """The projects the person can open, active ones unless ``archived``:
    bookmarked ones first, then by ``order`` (activity by
    default), the latest activity first or by name. Archived ones by name,
    bookmarked ones first."""
    if archived:
        projects = Project.objects.accessible_to(request.user).filter(
            archived_at__isnull=False
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


class ProjectIn(Schema):
    name: str
    description: str = ""
    is_all_access: bool = True
    # Left out: a suggested color no other active project has; "": none
    color: Color | Literal[""] | None = None


@router.post("projects/", response={201: ProjectOut})
def project_create(request, data: ProjectIn):
    """Creates the project (staff); the creator becomes a member"""
    if not project_ops.can_create_project(request.user):
        raise HttpError(403, _("Only staff can create projects."))
    project = project_ops.create_project(
        name=data.name,
        description=data.description,
        is_all_access=data.is_all_access,
        color=data.color,
        actor=request.user,
    )
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
    # How the person is in the project: "default" (notified by default),
    # "tagged" (only when tagged) or "nothing" (no mails). Only for staff
    # and for yourself, else null.
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


class MemberIn(Schema):
    person_id: int
    notify: Notify = "default"


@router.post("projects/{project_id}/members/", response={201: MemberOut})
def member_add(request, project_id: int, data: MemberIn):
    """Adds an active person (staff). ``notify`` is stored as their choice
    unless they have one already."""
    project = project_for(request, project_id)
    staff_only(request)
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
    """Staff remove anybody, everybody can leave (403 otherwise); returns
    the person removed"""
    project = project_for(request, project_id)
    user = get_object_or_404(User, pk=person_id, memberships__project=project)
    if user != request.user and not project_ops.can_manage_members(request.user):
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
    project_ops.update_project(project, actor=request.user, **changes)
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
