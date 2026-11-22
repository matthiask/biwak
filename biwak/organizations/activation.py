"""Activating and deactivating people (specs/activation.md): the importer
creates people without an account inactive on purpose; deactivating ends
the access of somebody who left. Own staff change clients, admins also own
staff and partners (decided 2026-11-21); clients never. Both are all or
nothing for several people."""

from typing import NamedTuple

from allauth.mfa.models import Authenticator
from allauth.usersessions.models import UserSession
from django.db import transaction
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone
from django.utils.translation import gettext as _, ngettext

from biwak.accounts.languages import language_for
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
    Everything else stays, assignments too (decided 2026-11-22,
    specs/handover.md). Refused (``ActivationError``) for oneself and
    when no active admin would be left; all or nothing. Returns the people
    deactivated."""
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
        # Their assignments stay (decided 2026-11-22, specs/handover.md)
        done.append(user)
    end_access_now_and_after_commit([user.pk for user in done])
    return done


class Left(NamedTuple):
    """What somebody leaving leaves behind, as far as the viewer may know
    (specs/handover.md)"""

    open_todos: int
    # Projects they're the only active staff member of
    only_staff_in: list


def what_is_left(user, *, viewer):
    """``Left``: the person's open to-dos and the projects (not archived)
    they're the only active staff member of, counting only projects the
    viewer can open (decided 2026-11-22: nothing about the others, not even
    their titles or counts). Two queries."""
    from django.db.models import Exists, OuterRef

    from biwak.items import due
    from biwak.projects.models import Membership, Project

    open_todos = due.todos(viewer, assignee=user.pk).count()
    only = []
    if not user.is_client:
        others = Membership.objects.filter(
            project=OuterRef("pk"), user__is_active=True, user__is_client=False
        ).exclude(user=user)
        only = list(
            Project.objects
            .accessible_to(viewer)
            .active()
            .filter(memberships__user=user)
            .filter(~Exists(others))
            .order_by(Lower("name"))
        )
    return Left(open_todos, only)


def end_access(users):
    """Ends the access of these (inactive) people: sessions, API tokens and
    calendar links go, open websockets check again (``sso.session_alive()``)"""
    from biwak.collab import live

    for user in users:
        for session in UserSession.objects.filter(user=user):
            session.end()
        APIToken.objects.filter(user=user).delete()
        CalendarToken.objects.filter(user=user).delete()
        live.check_access(user=user.pk)


def end_access_now_and_after_commit(user_ids):
    """``end_access()`` now, and again once the transaction committed for
    those still inactive then: what other requests made meanwhile (they
    didn't see the change yet) goes too, like
    ``sso.enforce_required_now_and_after_commit()``"""
    user_ids = list(user_ids)
    if not user_ids:
        return

    def run():
        end_access(User.objects.filter(pk__in=user_ids, is_active=False))

    run()
    transaction.on_commit(run)


# Resetting someone's sign-in (specs/two-factor.md): the same split


class SignIn(NamedTuple):
    """What a person set up for signing in that a reset removes"""

    app: bool  # An authenticator app
    passkeys: int
    api_tokens: int

    def __bool__(self):
        return self.app or bool(self.passkeys) or bool(self.api_tokens)


def sign_in(user):
    """``SignIn``: what the person has that a reset would remove"""
    types = list(Authenticator.objects.filter(user=user).values_list("type", flat=True))
    return SignIn(
        app=Authenticator.Type.TOTP in types,
        passkeys=types.count(Authenticator.Type.WEBAUTHN),
        api_tokens=APIToken.objects.filter(user=user).count(),
    )


def can_reset_sign_in(actor, user):
    """``can_change()``, and not oneself: people change their own in the
    settings"""
    return can_change(actor, user) and actor.pk != user.pk


@transaction.atomic
def reset_sign_in(user, *, actor):
    """One recovery and incident action (decided 2026-11-21: "lost my phone
    or laptop", "someone else may have had access"): deletes the person's
    authenticator app, passkeys and API tokens, ends their sessions and
    mails them what was removed and by whom (through the outbox, after the
    commit); the audit log has the deleted rows. They sign in by code or
    through their organization's identity provider then. ``PermissionError``
    for people the actor may not change, ``ActivationError`` for oneself.
    Returns the ``SignIn`` removed, false when there was none of them; then
    nothing happens."""
    from biwak.collab import live

    user = User.objects.select_for_update().get(pk=user.pk)
    _check(actor, [user])
    if actor.pk == user.pk:
        raise ActivationError(_("Change your own sign-in in your settings."))
    removed = sign_in(user)
    if not removed:
        return removed
    Authenticator.objects.filter(user=user).delete()
    APIToken.objects.filter(user=user).delete()
    for session in UserSession.objects.filter(user=user):
        session.end()
    live.check_access(user=user.pk)
    if gets_reset_mail(user):
        send_sign_in_reset(user, removed, actor=actor)
    return removed


def gets_reset_mail(user):
    """Whether ``reset_sign_in()`` mails the person: not inactive people or
    bounced addresses"""
    return user.is_active and user.mail_undeliverable_at is None


def removed_list(removed, *, theirs=False):
    """What ``reset_sign_in()`` removed, as words: ["your authenticator app",
    "2 passkeys", …]; ``theirs`` for telling somebody else ("their
    authenticator app")"""
    words = []
    if removed.app:
        words.append(
            _("their authenticator app") if theirs else _("your authenticator app")
        )
    if removed.passkeys:
        words.append(
            ngettext("%(count)s passkey", "%(count)s passkeys", removed.passkeys)
            % {"count": removed.passkeys}
        )
    if removed.api_tokens:
        words.append(
            ngettext("%(count)s API token", "%(count)s API tokens", removed.api_tokens)
            % {"count": removed.api_tokens}
        )
    return words


def send_sign_in_reset(user, removed, *, actor):
    """ "Ada reset your sign-in to Biwak", from the person who did, naming
    what was removed"""
    from django.core.mail import EmailMessage
    from django.template.loader import render_to_string
    from django.urls import reverse
    from django.utils import translation

    from biwak.activity.mails import sender
    from biwak.api_conventions import absolute
    from biwak.outbox import sending as outbox
    from biwak.outbox.models import Kind

    with translation.override(language_for(user)):
        message = EmailMessage(
            _("%(actor)s reset your sign-in to Biwak") % {"actor": actor},
            render_to_string(
                "accounts/sign_in_reset.txt",
                {
                    "user": user,
                    "actor": actor,
                    "removed": removed_list(removed),
                    "url": absolute(reverse("settings")) + "#sign-in",
                },
            ),
            sender(_("%(name)s (Biwak)") % {"name": actor}),
            [user.email],
        )
    outbox.send(message, Kind.ACCOUNT)
