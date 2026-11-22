"""Using a team (specs/teams.md, "Using a team"): wherever several people
are picked on the web (the people picker, the ``@`` list), staff find teams
among the people. Picking one adds its members at once, only those who'd be
offered and available there, as if picked one by one; the entry says
beforehand how many are left out and why (the reasons of greyed-out
people). A team never adds anyone to a project. Clients never see teams;
partners see only the members they may know (``known_people()``), as on
the People page."""

from collections import Counter

from django.db.models.functions import Lower
from django.utils.translation import gettext as _, ngettext

from biwak.activity.notify import people_who_see
from biwak.teams.models import Team, TeamMember
from biwak.teams.operations import can_see


def inactive():
    return _("inactive")


def not_a_member():
    return _("not a member of this project")


def internal():
    return _("can't see internal items")


def visible_teams(viewer, query=""):
    """``[(team, [members])]`` the viewer sees, by name, the members by name;
    teams whose name has every word of ``query``. Nothing for clients;
    partners get the members they may know."""
    if not can_see(viewer):
        return []
    teams = Team.objects.order_by(Lower("name"))
    for word in query.split():
        teams = teams.filter(name__icontains=word)
    teams = list(teams)
    if not teams:
        return []
    memberships = (
        TeamMember.objects
        .filter(team__in=teams)
        .select_related("user", "user__organization")
        .order_by(Lower("user__full_name"), "user__email")
    )
    if not viewer.sees_all_access:
        from biwak.organizations.people import known_people

        memberships = memberships.filter(user__in=known_people(viewer).values("pk"))
    members = {}
    for membership in memberships:
        members.setdefault(membership.team_id, []).append(membership.user)
    return [(team, members.get(team.pk, [])) for team in teams]


def reason(user, *, project_members, visible):
    """Why a member who isn't offered is left out"""
    if not user.is_active:
        return inactive()
    if user.is_client and user.pk in project_members and not visible:
        return internal()
    return not_a_member()


def summary(count, total, left_out):
    """ "5 members", or "3 of 5: 2 can't see internal items" (``left_out``:
    ``{reason: count}``)"""
    if not left_out:
        return ngettext("%(count)s member", "%(count)s members", total) % {
            "count": total
        }
    return _("%(count)s of %(total)s: %(reasons)s") % {
        "count": count,
        "total": total,
        "reasons": ", ".join(f"{n} {why}" for why, n in left_out.items()),
    }


def _project_members(project):
    return set(project.memberships.values_list("user", flat=True))


def picker_teams(viewer, offered, *, project, visible, already=()):
    """The teams for the people picker (``frontend/people-picker.js``,
    ``data-teams``): ``[{id, name, members: [{id, reason, already}]}]``.
    ``offered`` is ``{person's ID: is_member}`` of the picker's options
    (``None`` where it doesn't say): those offered who aren't members yet
    are left out, a team never adds anyone to a project. ``already`` are
    those in already (subscribed, told), not left out and not added (IDs,
    or a function returning them). The
    script leaves out the options it finds disabled (clients while the
    post is internal) and adds the others."""
    teams = [(team, people) for team, people in visible_teams(viewer) if people]
    if not teams:
        return []
    already = set(already() if callable(already) else already)
    members = _project_members(project) if project is not None else set()
    result = []
    for team, people in teams:
        entries = []
        for user in people:
            entry = {"id": user.pk, "reason": "", "already": user.pk in already}
            if entry["already"]:
                pass
            elif user.pk in offered:
                if offered[user.pk] is False:
                    entry["reason"] = not_a_member()
            elif project is None:
                entry["reason"] = (
                    inactive()
                    if not user.is_active
                    else _("can't be assigned to all of them")
                )
            else:
                entry["reason"] = reason(user, project_members=members, visible=visible)
            entries.append(entry)
        result.append({"id": team.pk, "name": team.name, "members": entries})
    return result


def picker_texts():
    """The texts the picker shows for teams"""
    return {
        "data-team": _("team"),
        "data-team-one": ngettext("%(count)s member", "%(count)s members", 1),
        "data-team-many": ngettext("%(count)s member", "%(count)s members", 2),
        "data-team-partial": _("%(count)s of %(total)s: %(reasons)s"),
        "data-team-internal": internal(),
    }


def mention_teams(project, visible, query, *, for_user, names):
    """The teams for the ``@`` list (``frontend/mentions.js``), before the
    people: ``[{team: true, id, name, available, detail, members: [{id,
    short_name}]}]``, the members who can see the item (and whom the
    viewer may know); ``available`` while there's somebody to mention.
    ``names`` are the short names the viewer sees (``display_names()``)."""
    teams = [
        (team, people) for team, people in visible_teams(for_user, query) if people
    ]
    if not teams:
        return []
    seeing = set(
        people_who_see(project, visible)
        .filter(pk__in={user.pk for _team, people in teams for user in people})
        .values_list("pk", flat=True)
    )
    members = _project_members(project)
    result = []
    for team, people in teams:
        available = [user for user in people if user.pk in seeing]
        left_out = Counter(
            reason(user, project_members=members, visible=visible)
            for user in people
            if user.pk not in seeing
        )
        result.append({
            "team": True,
            "id": team.pk,
            "name": team.name,
            "available": bool(available),
            "detail": summary(len(available), len(people), left_out),
            "members": [
                {
                    "id": user.pk,
                    "short_name": names.get(user.pk) or user.get_short_name(),
                }
                for user in available
            ],
        })
    return result
