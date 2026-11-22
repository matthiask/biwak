"""Replying by mail (specs/notifications.md, stage 2)

Every notification mail about something one can comment on, and every
check-in question mail, carries a ``ReplyToken`` in its ``Reply-To``
(``r-<token>@REPLY_DOMAIN``). Mails coming back are recorded as
``InboundMessage``, once per provider and ID, whatever became of them.
"""

import secrets
import string

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from biwak.items.models import Item


# Lowercase letters and digits: local parts are limited to 64 characters
# and some servers lowercase them (decided 2026-11-20)
TOKEN_CHARS = string.ascii_lowercase + string.digits
TOKEN_LENGTH = 20
# Valid 6 months (decided 2026-11-20)
TOKEN_VALIDITY = relativedelta(months=6)
# Received mails, and tokens expired or revoked, are deleted after 90 days
# (decided 2026-11-20)
RETENTION_DAYS = 90


def new_token():
    return "".join(secrets.choice(TOKEN_CHARS) for _i in range(TOKEN_LENGTH))


def default_expires_at():
    return timezone.now() + TOKEN_VALIDITY


class ReplyToken(models.Model):
    """One per mail: replying to it posts as ``user`` on ``item`` (a
    comment), or answers ``occurrence`` of the check-in question ``item``"""

    token = models.CharField(
        _("token"), max_length=TOKEN_LENGTH, unique=True, default=new_token
    )
    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name="+",
        verbose_name=_("item"),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reply_tokens",
        verbose_name=_("person"),
    )
    occurrence = models.ForeignKey(
        "checkins.Occurrence",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("check-in occurrence"),
    )
    created_at = models.DateTimeField(_("created at"), default=timezone.now)
    expires_at = models.DateTimeField(_("expires at"), default=default_expires_at)
    revoked_at = models.DateTimeField(_("revoked at"), null=True, blank=True)
    # The one answer saying why a reply wasn't posted (at most one)
    error_sent_at = models.DateTimeField(_("error sent at"), null=True, blank=True)

    class Meta:
        verbose_name = _("reply token")
        verbose_name_plural = _("reply tokens")

    def __str__(self):
        return f"{self.user} → {self.item}"

    def is_valid(self, now=None):
        now = now or timezone.now()
        return self.revoked_at is None and self.expires_at > now


class InboundStatus(models.TextChoices):
    RECEIVED = "received", _("received")
    POSTED = "posted", _("posted")
    # Kept in the forwarder's list (specs/forwarding.md)
    FORWARDED = "forwarded", _("forwarded")
    # Dropped without an answer
    LOOP = "loop", _("auto-reply or bounce")
    UNKNOWN_TOKEN = "unknown_token", _("no reply address")
    RATE_LIMITED = "rate_limited", _("too many replies")
    EMPTY = "empty", _("empty")
    # Answered (once per token) with why
    WRONG_SENDER = "wrong_sender", _("wrong sender")
    UNAUTHENTICATED = "unauthenticated", _("authentication failed")
    EXPIRED = "expired", _("expired or revoked")
    NO_ACCESS = "no_access", _("no access")


class InboundMessage(models.Model):
    """A mail received, once per provider and ID: providers retry
    webhooks, so the second delivery finds the first"""

    provider = models.CharField(_("provider"), max_length=20)
    provider_id = models.CharField(_("provider ID"), max_length=200)
    received_at = models.DateTimeField(_("received at"), default=timezone.now)
    status = models.CharField(
        _("status"),
        max_length=20,
        choices=InboundStatus,
        default=InboundStatus.RECEIVED,
    )
    error = models.TextField(_("error"), blank=True)
    token = models.ForeignKey(
        ReplyToken,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="messages",
        verbose_name=_("reply token"),
    )
    sender = models.CharField(_("sender"), max_length=300, blank=True)
    # What was posted
    comment = models.ForeignKey(
        "items.Comment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("comment"),
    )
    answer = models.ForeignKey(
        Item,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("answer"),
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "provider_id"], name="unique_inbound_message"
            )
        ]
        indexes = [models.Index(fields=["token", "received_at"])]
        ordering = ["-received_at", "-pk"]
        verbose_name = _("inbound message")
        verbose_name_plural = _("inbound messages")

    def __str__(self):
        return f"{self.provider} {self.provider_id}: {self.status}"
