"""Activating and deactivating people (specs/activation.md): the importer
creates people without an account inactive on purpose; deactivating ends
the access of somebody who left. Own staff change clients, admins also own
staff and partners (decided 2026-11-21); clients never. Both are all or
nothing for several people."""

from allauth.mfa.models import Authenticator
from allauth.usersessions.models import UserSession
from django.db import transaction
from django.db.models import Q
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


def lock_with_admins(user_ids):
    """Locks the rows of these people and of every active admin, in the
    order of their IDs (no deadlocks between requests locking several), so
    two requests can't each take away an admin the other counted on;
    returns these people"""
    user_ids = set(user_ids)
    rows = (
        User.objects
        .select_for_update()
        .filter(Q(pk__in=user_ids) | Q(is_active=True, is_admin=True))
        .order_by("pk")
    )
    return [user for user in rows if user.pk in user_ids]


def check_admins_left(leaving):
    """``ActivationError`` when no active admin would be left without the
    people ``leaving`` (IDs); after ``lock_with_admins()``"""
    if (
        not User.objects
        .filter(is_active=True, is_admin=True)
        .exclude(pk__in=leaving)
        .exists()
    ):
        raise ActivationError(_("The last active admin can't be deactivated."))


@transaction.atomic
def deactivate(users, *, actor):
    """Clears ``is_active`` and ends the access at once: sessions, API
    tokens and calendar links go, open websockets close at their next check.
    Everything else stays. Refused (``ActivationError``) for oneself and
    when no active admin would be left; all or nothing. Returns the people
    deactivated."""
    from biwak.collab import live

    users = lock_with_admins([u.pk for u in users])
    _check(actor, users)
    if any(user.pk == actor.pk for user in users):
        raise ActivationError(_("You can't deactivate yourself."))
    leaving = {user.pk for user in users if user.is_active}
    if any(user.is_admin for user in users if user.pk in leaving):
        check_admins_left(leaving)
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


# Resetting someone's second factor (specs/two-factor.md): the same split


def can_reset_two_factor(actor, user):
    """``can_change()``, and not oneself: people turn their own app off in
    the settings, with its code"""
    return can_change(actor, user) and actor.pk != user.pk


@transaction.atomic
def reset_two_factor(user, *, actor):
    """Deletes the person's authenticator app, ends their sessions and mails
    them (through the outbox, after the commit) so a reset they didn't ask
    for is noticed; the audit log has the deleted row. Passkeys stay: they
    are a way in, not a second factor. ``PermissionError`` for people the
    actor may not change, ``ActivationError`` for oneself. Returns whether
    there was an app; without one nothing happens."""
    from biwak.collab import live

    user = User.objects.select_for_update().get(pk=user.pk)
    _check(actor, [user])
    if actor.pk == user.pk:
        raise ActivationError(
            _("Turn your own authenticator app off in your settings.")
        )
    deleted, _rows = Authenticator.objects.filter(
        user=user,
        type__in=[Authenticator.Type.TOTP, Authenticator.Type.RECOVERY_CODES],
    ).delete()
    if not deleted:
        return False
    for session in UserSession.objects.filter(user=user):
        session.end()
    live.check_access(user=user.pk)
    if user.is_active and user.mail_undeliverable_at is None:
        send_two_factor_reset(user, actor=actor)
    return True


def send_two_factor_reset(user, *, actor):
    """ "Ada removed your authenticator app", from the person who did"""
    from django.core.mail import EmailMessage
    from django.template.loader import render_to_string
    from django.urls import reverse
    from django.utils import translation

    from biwak.activity.mails import sender
    from biwak.api_conventions import absolute
    from biwak.outbox import sending as outbox
    from biwak.outbox.models import Kind

    with translation.override(user.language or translation.get_language()):
        message = EmailMessage(
            _("%(actor)s removed your authenticator app") % {"actor": actor},
            render_to_string(
                "accounts/two_factor_reset.txt",
                {
                    "user": user,
                    "actor": actor,
                    "url": absolute(reverse("settings")) + "#sign-in",
                },
            ),
            sender(_("%(name)s (Biwak)") % {"name": actor}),
            [user.email],
        )
    outbox.send(message, Kind.ACCOUNT)
