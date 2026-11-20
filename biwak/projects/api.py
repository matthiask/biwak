"""Projects and their members (biwak projects)"""

import datetime as dt

from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _
from ninja import Router, Schema
from ninja.errors import HttpError

from biwak.activity.models import Action
from biwak.activity.operations import record
from biwak.api_conventions import PersonOut, absolute, html, person_out
from biwak.projects import operations as project_ops
from biwak.projects.models import Project


router = Router(tags=["projects"])


class ProjectOut(Schema):
    id: int
    name: str
    description: str
    description_html: str
    is_all_access: bool
    is_member: bool
    archived_at: dt.datetime | None
    url: str


def project_for(request, pk):
    """The project if the person may open it, else 404, like the web"""
    return get_object_or_404(Project.objects.accessible_to(request.user), pk=pk)


def project_out(project, user):
    return {
        "id": project.pk,
        "name": project.name,
        "description": project.description,
        "description_html": html(project.description),
        "is_all_access": project.is_all_access,
        "is_member": project.is_member(user),
        "archived_at": project.archived_at,
        "url": absolute(project.get_absolute_url()),
    }


@router.get("projects/", response=list[ProjectOut])
def project_list(request, *, archived: bool = False):
    """The projects the person can open, active ones unless ``archived``"""
    projects = Project.objects.accessible_to(request.user)
    projects = (
        projects.filter(archived_at__isnull=False) if archived else projects.active()
    )
    return [project_out(project, request.user) for project in projects]


@router.get("projects/{project_id}/", response=ProjectOut)
def project_detail(request, project_id: int):
    return project_out(project_for(request, project_id), request.user)


class MemberOut(PersonOut):
    email: str | None


@router.get("projects/{project_id}/members/", response=list[MemberOut])
def project_members(request, project_id: int):
    """Members; addresses only for staff, like on the people page"""
    project = project_for(request, project_id)
    return [
        person_out(m.user) | {"email": None if request.user.is_client else m.user.email}
        for m in project.memberships.select_related("user").order_by(
            "user__is_client", "user__full_name"
        )
    ]


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
    fields = [f for f in ["name", "description", "is_all_access"] if f in given]
    for field in fields:
        value = getattr(data, field)
        if value is None or (field == "name" and not value.strip()):
            raise HttpError(400, _("%(field)s can't be empty.") % {"field": field})
        setattr(project, field, value)
    if fields:
        project.full_clean()
        project.save(update_fields=fields)
        record(actor=request.user, action=Action.EDITED_PROJECT, project=project)
    if "archived" in given and data.archived != bool(project.archived_at):
        if data.archived:
            project_ops.archive_project(project, actor=request.user)
        else:
            project_ops.unarchive_project(project, actor=request.user)
    return project_out(project, request.user)
