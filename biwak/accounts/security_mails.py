"""Mails telling somebody that how they sign in changed (specs/two-factor.md,
decided 2026-11-21): a passkey added or removed, the authenticator app turned
on or off. allauth's notification hook
(``AccountAdapter.send_notification_mail``) calls ``send()``; a change they
didn't make is noticed."""

from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import formats, timezone, translation
from django.utils.translation import gettext_lazy

from biwak.accounts.languages import language_for


SUBJECTS = {
    "webauthn_added": gettext_lazy("A passkey was added to your Biwak account"),
    "webauthn_removed": gettext_lazy("A passkey was removed from your Biwak account"),
    "totp_activated": gettext_lazy(
        "The authenticator app of your Biwak account was turned on"
    ),
    "totp_deactivated": gettext_lazy(
        "The authenticator app of your Biwak account was turned off"
    ),
}

CHANGES = {
    "webauthn_added": gettext_lazy("A passkey was added to your Biwak account"),
    "webauthn_removed": gettext_lazy("A passkey was removed from your Biwak account"),
    "totp_activated": gettext_lazy(
        "An authenticator app was turned on for your Biwak account"
    ),
    "totp_deactivated": gettext_lazy(
        "The authenticator app was turned off for your Biwak account"
    ),
}


def send(change, user, *, now=None):
    """Mails the person what changed and when, through the outbox after the
    commit; not to inactive people, bounced addresses, nor about passkeys of
    people whose organization requires single sign-on (they're removed at
    once, ``passkeys.passkey_added``). Unknown changes are ignored."""
    from biwak.accounts import sso
    from biwak.activity.mails import sender
    from biwak.api_conventions import absolute
    from biwak.outbox import sending as outbox
    from biwak.outbox.models import Kind

    if change not in SUBJECTS or not user.is_active or not user.email:
        return
    if user.mail_undeliverable_at is not None:
        return
    if change == "webauthn_added" and sso.requires_sso(user):
        return
    when = timezone.localtime(now or timezone.now())
    with translation.override(language_for(user)):
        message = EmailMessage(
            str(SUBJECTS[change]),
            render_to_string(
                "accounts/security_change.txt",
                {
                    "user": user,
                    "change": CHANGES[change],
                    "when": formats.date_format(when, "DATETIME_FORMAT"),
                    "url": absolute(reverse("settings")) + "#sign-in",
                },
            ),
            sender("Biwak"),
            [user.email],
        )
    outbox.send(message, Kind.ACCOUNT)
