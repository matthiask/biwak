"""The outbox (specs/mail-sending.md): every mail the app sends is a row
first, written in the transaction of the change it's about, sent once that
commits and retried until the transport accepted it. ``mail_admins`` goes
around it, through the plain mailer."""

import base64

from django.contrib.postgres.fields import ArrayField
from django.core.mail import EmailMultiAlternatives
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Kind(models.TextChoices):
    """Also the tag in Resend's dashboard"""

    NOTIFICATION = "notification", _("notification")
    DIGEST = "digest", _("digest")
    CHECKIN = "checkin", _("check-in")
    LOGIN_CODE = "login-code", _("login code")
    # allauth's other mails (none are on today)
    ACCOUNT = "account", _("account")
    INVITATION = "invitation", _("invitation")
    REPLY_REFUSED = "reply-refused", _("refused reply")
    # Only as a tag: mail_admins doesn't go through the outbox
    ADMIN = "admin", _("admin")


class Delivery(models.TextChoices):
    """What Resend's webhooks reported, the worst so far"""

    DELIVERED = "delivered", _("delivered")
    BOUNCED = "bounced", _("bounced")
    COMPLAINED = "complained", _("marked as spam")


class OutgoingMailQuerySet(models.QuerySet):
    def pending(self):
        """Neither accepted nor given up"""
        return self.filter(next_attempt_at__isnull=False)


class OutgoingMail(models.Model):
    kind = models.CharField(_("kind"), max_length=20, choices=Kind)
    # The bare addresses of To, Cc and Bcc, kept for the delivery events
    recipients = ArrayField(models.CharField(max_length=254), verbose_name=_("to"))
    # The message (serialize()); None once the transport accepted it, the
    # content is in Resend's log then (decided 2026-11-21)
    message = models.JSONField(_("message"), null=True, blank=True)
    created_at = models.DateTimeField(_("created at"), default=timezone.now)
    attempts = models.PositiveIntegerField(_("attempts"), default=0)
    # None once sent or given up: nothing more to do
    next_attempt_at = models.DateTimeField(_("next attempt at"), null=True)
    # Login codes: not sent any more after the code expired
    expires_at = models.DateTimeField(_("expires at"), null=True, blank=True)
    sent_at = models.DateTimeField(_("sent at"), null=True, blank=True)
    given_up_at = models.DateTimeField(_("given up at"), null=True, blank=True)
    last_error = models.TextField(_("last error"), blank=True)
    # Resend's ID of the mail, which its webhooks report
    provider_id = models.CharField(_("provider ID"), max_length=200, blank=True)
    delivery = models.CharField(
        _("delivery"), max_length=20, choices=Delivery, blank=True
    )
    delivery_at = models.DateTimeField(_("delivery reported at"), null=True)
    delivery_detail = models.TextField(_("delivery detail"), blank=True)

    objects = OutgoingMailQuerySet.as_manager()

    class Meta:
        verbose_name = _("outgoing mail")
        verbose_name_plural = _("outgoing mails")
        ordering = ["-created_at", "-pk"]
        indexes = [
            models.Index(
                fields=["next_attempt_at"],
                condition=models.Q(next_attempt_at__isnull=False),
                name="outbox_pending",
            ),
            models.Index(
                fields=["provider_id"],
                condition=~models.Q(provider_id=""),
                name="outbox_provider_id",
            ),
            models.Index(fields=["created_at"], name="outbox_created_at"),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} to {', '.join(self.recipients)}"

    @property
    def state(self):
        if self.sent_at:
            return _("sent")
        if self.given_up_at:
            return _("given up")
        return _("waiting")

    @property
    def subject(self):
        return (self.message or {}).get("subject", "")

    def email_message(self):
        return deserialize(self.message)


# The message as JSON -------------------------------------------------------


def serialize(message):
    """What's needed to build the same message again: addresses, subject,
    bodies, headers, alternatives, attachments (name, content, type)"""
    attachments = []
    for attachment in message.attachments:
        if not isinstance(attachment, tuple):
            raise TypeError("The outbox takes attachments as (name, content, type)")
        filename, content, mimetype = attachment
        if isinstance(content, bytes):
            content = {"base64": base64.b64encode(content).decode()}
        attachments.append([filename, content, mimetype])
    return {
        "subject": str(message.subject),
        "body": str(message.body),
        "content_subtype": message.content_subtype,
        "from_email": str(message.from_email),
        "to": [str(a) for a in message.to],
        "cc": [str(a) for a in message.cc],
        "bcc": [str(a) for a in message.bcc],
        "reply_to": [str(a) for a in message.reply_to],
        "headers": {str(k): str(v) for k, v in message.extra_headers.items()},
        "alternatives": [
            [str(content), mimetype]
            for content, mimetype in getattr(message, "alternatives", ())
        ],
        "attachments": attachments,
    }


def deserialize(data):
    message = EmailMultiAlternatives(
        data["subject"],
        data["body"],
        data["from_email"],
        data["to"],
        cc=data["cc"],
        bcc=data["bcc"],
        reply_to=data["reply_to"],
        headers=data["headers"],
    )
    message.content_subtype = data["content_subtype"]
    for content, mimetype in data["alternatives"]:
        message.attach_alternative(content, mimetype)
    for filename, content, mimetype in data["attachments"]:
        message.attach(
            filename,
            base64.b64decode(content["base64"])
            if isinstance(content, dict)
            else content,
            mimetype,
        )
    return message
