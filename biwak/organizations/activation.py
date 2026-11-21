"""Activating and deactivating people (specs/activation.md): the importer
creates people without an account inactive on purpose; deactivating ends
the access of somebody who left. Own staff change clients, admins also own
staff and partners (decided 2026-11-21); clients never. Both are all or
nothing for several people."""

from allauth.usersessions.models import UserSession
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from biwak.accounts.models import APIToken, CalendarToken, User
from biwak.projects import operations as project_ops


class ActivationError(ValueError):
    """Refused for a reason of the case (oneself, the last admin)"""


def can_change(actor, user):
    """Whether the actor may activate or deactivate this person: own staff
    clients, admins everybody; the same split as inviting"""
    if not actor.is_authenticated or not project_ops.can_manage_members(actor):
        return False
    return actor.is_admin or user.is_client


def can_deactivate(actor, user):
    """``can_change()``, and not oneself"""
    return can_change(actor, user) and actor.pk != user.pk


def _check(actor, users):
    refused = [user for user in users if not can_change(actor, user)]
    if refused:
        raise PermissionError(
            _("You may not change %(names)s: only admins change staff.")
            % {"names": ", ".join(sorted(str(user) for user in refused))}
        )


@transaction.atomic
def activate(users, *, actor, mail=False):
    """Sets ``is_active``; nothing else changes. With ``mail`` the
    invitation mail (naming the projects the person is in) goes out through
    the outbox and the person counts as invited until they sign in, except
    to addresses that bounced. People who are active already stay as they
    are. All or nothing (``PermissionError``). Returns ``[(user, mailed)]``
    of the people activated."""
    users = list(User.objects.select_for_update().filter(pk__in=[u.pk for u in users]))
    _check(actor, users)
    done = []
    for user in users:
        if user.is_active:
            continue
        user.is_active = True
        fields = ["is_active"]
        mailed = mail and user.mail_undeliverable_at is None
        if mailed:
            user.invited_by, user.invited_at = actor, timezone.now()
            fields += ["invited_by", "invited_at"]
        user.save(update_fields=fields)
        if mailed:
            project_ops.send_invitation(
                list(project_ops.invitation_projects(user)), user, actor=actor
            )
        done.append((user, mailed))
    return done


@transaction.atomic
def deactivate(users, *, actor):
    """Clears ``is_active`` and ends the access at once: sessions, API
    tokens and calendar links go, open websockets close at their next check.
    Everything else stays. Refused (``ActivationError``) for oneself and
    when no active admin would be left; all or nothing. Returns the people
    deactivated."""
    from biwak.collab import live

    users = list(User.objects.select_for_update().filter(pk__in=[u.pk for u in users]))
    _check(actor, users)
    if any(user.pk == actor.pk for user in users):
        raise ActivationError(_("You can't deactivate yourself."))
    leaving = {user.pk for user in users if user.is_active}
    if (
        any(user.is_admin for user in users if user.pk in leaving)
        and not User.objects
        .filter(is_active=True, is_admin=True)
        .exclude(pk__in=leaving)
        .exists()
    ):
        raise ActivationError(_("The last active admin can't be deactivated."))
    done = []
    for user in users:
        if user.pk not in leaving:
            continue
        user.is_active = False
        user.save(update_fields=["is_active"])
        for session in UserSession.objects.filter(user=user):
            session.end()
        APIToken.objects.filter(user=user).delete()
        CalendarToken.objects.filter(user=user).delete()
        live.check_access(user=user.pk)
        done.append(user)
    return done
