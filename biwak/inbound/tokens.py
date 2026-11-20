"""Reply addresses: ``r-<token>@REPLY_DOMAIN`` in the ``Reply-To`` of
notification and check-in question mails (specs/notifications.md, stage 2)"""

import datetime as dt
import re

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from biwak.inbound.models import (
    RETENTION_DAYS,
    TOKEN_LENGTH,
    InboundMessage,
    ReplyToken,
)


ADDRESS = re.compile(rf"^r-([a-z0-9]{{{TOKEN_LENGTH}}})@(.+)$")


def enabled():
    """Replying is on when the reply domain, Resend's API key and its
    webhook secret are set"""
    return bool(
        settings.REPLY_DOMAIN
        and settings.RESEND_API_KEY
        and settings.RESEND_WEBHOOK_SECRET
    )


def address(token):
    return f"r-{token.token}@{settings.REPLY_DOMAIN}"


def reply_to(user, item, *, occurrence=None):
    """The ``Reply-To`` header of one mail with a new token, or nothing
    while replying is off"""
    if not enabled():
        return {}
    token = ReplyToken.objects.create(user=user, item=item, occurrence=occurrence)
    return {"Reply-To": address(token)}


def token_in(recipients):
    """The first reply token among the addresses, if any"""
    domain = (settings.REPLY_DOMAIN or "").lower()
    for recipient in recipients:
        match = ADDRESS.match(recipient.lower())
        if match and domain and match[2] == domain:
            return match[1]
    return None


def prune(*, now=None):
    """Deletes received mails and reply tokens expired or revoked more than
    RETENTION_DAYS ago (fairy_tasks); comments posted from replies stay.
    Returns how many mails and tokens went."""
    cutoff = (now or timezone.now()) - dt.timedelta(days=RETENTION_DAYS)
    messages = InboundMessage.objects.filter(received_at__lt=cutoff).delete()[0]
    tokens = ReplyToken.objects.filter(
        Q(expires_at__lt=cutoff) | Q(revoked_at__lt=cutoff)
    ).delete()[0]
    return messages, tokens
