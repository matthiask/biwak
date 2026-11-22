"""Managing teams (specs/teams.md): any own staff creates, renames, changes
and deletes them; partners and clients don't. The audit log records it
(the trigger on the tables). Teams aren't items: no events, nobody is
told."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from biwak.accounts.models import User
from biwak.organizations.models import normalize_name
from biwak.teams.models import Team, TeamMember


NAME_LENGTH = Team._meta.get_field("name").max_length


def can_manage(user):
    """Own staff (``User.sees_all_access``)"""
    return user.is_authenticated and user.is_active and user.sees_all_access


def can_see(user):
    """Staff, own staff and partners; clients never see a team's name"""
    return user is not None and user.is_authenticated and not user.is_client


def _check_manage(actor):
    if not can_manage(actor):
        raise PermissionError(_("Only your own staff manage teams."))


def clean_name(name, *, instance=None):
    """The normalized name, ``ValidationError`` when empty, too long or
    taken (ignoring case and spaces)"""
    name = normalize_name(name)
    if not name:
        raise ValidationError(_("Enter a name."))
    if len(name) > NAME_LENGTH:
        raise ValidationError(
            _("At most %(count)s characters.") % {"count": NAME_LENGTH}
        )
    taken = Team.objects.filter(name__iexact=name)
    if instance is not None:
        taken = taken.exclude(pk=instance.pk)
    if taken.exists():
        raise ValidationError(
            _("There is a team called “%(name)s” already.") % {"name": name}
        )
    return name


def _people(members):
    """Users from users or IDs; ``ValidationError`` for unknown IDs"""
    ids = {getattr(member, "pk", member) for member in members}
    found = set(User.objects.filter(pk__in=ids).values_list("pk", flat=True))
    if missing := ids - found:
        raise ValidationError(
            _("Nobody with the ID %(ids)s.")
            % {"ids": ", ".join(str(pk) for pk in sorted(missing))}
        )
    return found


@transaction.atomic
def create_team(*, name, members=(), actor):
    _check_manage(actor)
    team = Team.objects.create(name=clean_name(name))
    TeamMember.objects.bulk_create([
        TeamMember(team=team, user_id=pk) for pk in _people(members)
    ])
    return team


@transaction.atomic
def update_team(team, *, name=None, members=None, actor):
    """Renames and replaces the members (``None`` leaves either alone)"""
    _check_manage(actor)
    if name is not None:
        team.name = clean_name(name, instance=team)
        team.save(update_fields=["name"])
    if members is not None:
        wanted = _people(members)
        team.memberships.exclude(user__in=wanted).delete()
        have = set(team.memberships.values_list("user", flat=True))
        TeamMember.objects.bulk_create([
            TeamMember(team=team, user_id=pk) for pk in wanted - have
        ])
    return team


@transaction.atomic
def delete_team(team, *, actor):
    """What was picked with it stays: only people were stored"""
    _check_manage(actor)
    team.delete()
