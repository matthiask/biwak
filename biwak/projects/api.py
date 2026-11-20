"""Projects and their members (biwak projects)"""

import datetime as dt

from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from biwak.api_conventions import PersonOut, absolute, html, person_out
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
