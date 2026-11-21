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

from biwak.accounts.models import User
from biwak.api_conventions import PersonOut, absolute, html, person_out
from biwak.bookmarks.models import Bookmark
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
    bookmarked ones first, then by ``order`` (the person's setting by
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


@router.post("projects/", response={201: ProjectOut})
def project_create(request, data: ProjectIn):
    """Creates the project (staff); the creator becomes a member"""
    if not project_ops.can_manage_project(request.user):
        raise HttpError(403, _("Only staff can create projects."))
    project = project_ops.create_project(
        name=data.name,
        description=data.description,
        is_all_access=data.is_all_access,
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
        for m in project.memberships.select_related("user").order_by(
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
    organization: str = ""
    notify: Notify = "default"


@router.post("projects/{project_id}/members/invite/", response={201: MemberOut})
def member_invite(request, project_id: int, data: InviteIn):
    """Adds a person by address, creating and mailing them if they're new
    (staff)"""
    project = project_for(request, project_id)
    staff_only(request)
    try:
        validate_email(data.email)
    except ValidationError as exc:
        raise HttpError(400, _("Enter a valid email address.")) from exc
    try:
        user, _changed = project_ops.invite(
            project,
            email=data.email,
            full_name=data.name,
            is_client=data.is_client,
            organization=data.organization,
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
        for field in ["name", "description", "is_all_access"]
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
