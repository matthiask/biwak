"""Teams (``biwak teams``, specs/teams.md): staff list and read them
(externals with the members they may know), own staff create, change and
delete them; clients get 404. Teams aren't expanded through the API: an
agent reads a team's members and sends the people."""

from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _
from ninja import Router, Schema, Status
from ninja.errors import HttpError

from biwak.api_conventions import PersonOut, absolute, person_out
from biwak.teams import operations as team_ops
from biwak.teams.models import Team
from biwak.teams.picking import visible_teams


router = Router(tags=["teams"])


class TeamOut(Schema):
    id: int
    name: str
    # Externals get those they may know
    members: list[PersonOut]
    url: str


def team_out(team, members):
    return {
        "id": team.pk,
        "name": team.name,
        "members": [person_out(user) for user in members],
        "url": absolute(team.get_absolute_url()),
    }


def seeing(request):
    if not team_ops.can_see(request.user):
        raise HttpError(404, _("Not found."))


def managing(request):
    seeing(request)
    if not team_ops.can_manage(request.user):
        raise HttpError(403, _("Only your own staff manage teams."))


def team_for(request, pk):
    seeing(request)
    team = get_object_or_404(Team, pk=pk)
    [members] = [people for t, people in visible_teams(request.user) if t.pk == pk]
    return team, members


def changing(function, *args, **kwargs):
    """The operation, a refusal (a taken name, unknown people) a 400"""
    try:
        return function(*args, **kwargs)
    except ValidationError as exc:
        raise HttpError(400, " ".join(exc.messages)) from exc


@router.get("teams/", response=list[TeamOut])
def team_list(request):
    """All teams by name, with their members (staff)"""
    seeing(request)
    return [team_out(team, members) for team, members in visible_teams(request.user)]


class TeamIn(Schema):
    name: str
    # The people's IDs: anyone, active or not, staff, externals and clients
    members: list[int] = []


@router.post("teams/", response={201: TeamOut})
def team_create(request, data: TeamIn):
    managing(request)
    team = changing(
        team_ops.create_team, name=data.name, members=data.members, actor=request.user
    )
    return Status(201, team_out(*team_for(request, team.pk)))


@router.get("teams/{team_id}/", response=TeamOut)
def team_detail(request, team_id: int):
    return team_out(*team_for(request, team_id))


class TeamPatch(Schema):
    name: str | None = None
    # Replaces the members
    members: list[int] | None = None


@router.patch("teams/{team_id}/", response=TeamOut)
def team_update(request, team_id: int, data: TeamPatch):
    """Renames and replaces the members; what was picked with the team
    before stays as it is"""
    managing(request)
    team, _members = team_for(request, team_id)
    changing(
        team_ops.update_team,
        team,
        name=data.name,
        members=data.members,
        actor=request.user,
    )
    return team_out(*team_for(request, team_id))


@router.delete("teams/{team_id}/", response=TeamOut)
def team_delete(request, team_id: int):
    """Deletes the team; returns it. Assignees, subscribers and mentions
    picked with it stay."""
    managing(request)
    out = team_out(*team_for(request, team_id))
    team_ops.delete_team(Team.objects.get(pk=team_id), actor=request.user)
    return out
