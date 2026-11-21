"""Posting replies by mail (specs/notifications.md, stage 2)

``receive()`` takes an ``InboundMail`` from any provider and decides, in
this order:

1. Each mail once per provider and ID (providers retry webhooks).
2. Auto-replies, out-of-office and bounces are dropped, never answered.
3. Without a known reply token, dropped.
4. At most 20 mails per token and hour, the rest dropped.
5. Posted as the token's person only if the ``From`` address is theirs,
   the receiving server's authentication passed, the token is valid and
   they can still see (and comment on, or answer) the item **now**.
   Otherwise one short answer per token says why.
6. The reply without quotes and signature, its attachments (at most
   25 MB each), through ``add_comment()`` or the check-in's ``answer()``.
"""

import datetime as dt
import logging

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.mail import EmailMessage
from django.db import IntegrityError, transaction
from django.template.loader import render_to_string
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from biwak.accounts.middleware import set_user_name
from biwak.activity import mentions
from biwak.activity.mails import sender
from biwak.activity.notify import can_see
from biwak.files import attachments
from biwak.inbound.models import InboundMessage, InboundStatus, ReplyToken
from biwak.inbound.strip import reply_text
from biwak.inbound.tokens import token_in
from biwak.outbox import sending as outbox
from biwak.outbox.models import Kind as MailKind


logger = logging.getLogger(__name__)

# At most this many mails per token and hour (decided 2026-11-20)
RATE_LIMIT = 20
RATE_WINDOW = dt.timedelta(hours=1)
# Attachments of replies, each (decided 2026-11-20)
MAX_ATTACHMENT_SIZE = 25 * 2**20

# Answered with why, at most once per token
REJECTIONS = {
    InboundStatus.WRONG_SENDER,
    InboundStatus.UNAUTHENTICATED,
    InboundStatus.EXPIRED,
    InboundStatus.NO_ACCESS,
}


def is_automatic(mail):
    """Auto-replies, out-of-office notices and bounces"""
    auto_submitted = mail.header("Auto-Submitted").strip().lower()
    return bool(
        (auto_submitted and auto_submitted != "no")
        or mail.header("Precedence").strip().lower() in {"bulk", "junk", "list"}
        or (mail.envelope_sender is not None and not mail.envelope_sender)
        or "X-Autoreply" in mail.headers
        or "X-Autorespond" in mail.headers
        # Delivery status notifications (bounces)
        or mail.headers.get_content_type() == "multipart/report"
    )


def is_authenticated(mail):
    """What the receiving server reports for the ``From`` domain: DMARC
    passed, or DKIM passed (Resend reports DKIM as passed only when the
    signing domain is the ``From`` domain). SPF alone isn't enough: it's
    about the envelope sender, and Resend doesn't say whether that is
    aligned with ``From``."""
    return mail.dmarc == "pass" or mail.dkim == "pass"


def can_reply(user, token):
    """Whether the person may post this reply now: active, the item visible
    to them now, commentable; for check-ins asked the question"""
    from biwak.checkins.operations import can_answer

    item = token.item
    if not can_see(user, item):
        return False
    if token.occurrence_id:
        return can_answer(user, item)
    return item.is_commentable


def receive(mail, *, provider, provider_id, now=None):
    """Records and handles the mail; None if it was received before"""
    now = now or timezone.now()
    with transaction.atomic():
        try:
            with transaction.atomic():
                message = InboundMessage.objects.create(
                    provider=provider,
                    provider_id=provider_id,
                    received_at=now,
                    sender=mail.sender[:300],
                )
        except IntegrityError:
            return None
        message.status = _handle(message, mail, now)
        message.save()
    logger.info("Mail %s from %s: %s", provider_id, mail.sender, message.status)
    return message


def _handle(message, mail, now):
    if is_automatic(mail):
        return InboundStatus.LOOP
    value = token_in(mail.recipients)
    token = (
        ReplyToken.objects
        .select_for_update(of=("self",))
        .select_related("user", "item__project", "occurrence")
        .filter(token=value)
        .first()
        if value
        else None
    )
    if token is None:
        return InboundStatus.UNKNOWN_TOKEN
    message.token = token
    recent = (
        InboundMessage.objects
        .filter(token=token, received_at__gt=now - RATE_WINDOW)
        .exclude(pk=message.pk)
        .count()
    )
    if recent >= RATE_LIMIT:
        return InboundStatus.RATE_LIMITED

    user = token.user
    authenticated = is_authenticated(mail)
    if not mail.sender or mail.sender != user.email.lower():
        status = InboundStatus.WRONG_SENDER
    elif not authenticated:
        status = InboundStatus.UNAUTHENTICATED
    elif not token.is_valid(now):
        status = InboundStatus.EXPIRED
    elif not can_reply(user, token):
        status = InboundStatus.NO_ACCESS
    else:
        return _post(message, mail, token)
    _reject(token, mail, status, authenticated=authenticated, now=now)
    return status


def _post(message, mail, token):
    from biwak.checkins.operations import answer
    from biwak.items.operations import add_comment

    user, item = token.user, token.item
    text = reply_text(mail)
    files = []
    skipped = []
    for attachment in mail.attachments:
        if len(attachment.content) > MAX_ATTACHMENT_SIZE:
            skipped.append(attachment.name)
            continue
        files.append(attachment)
    if not text and not files and not skipped:
        return InboundStatus.EMPTY

    set_user_name(user)
    uploaded = [
        attachments.upload(
            project=item.project,
            file=ContentFile(attachment.content, name=attachment.name),
            uploaded_by=user,
        )
        for attachment in files
    ]
    with translation.override(user.language or settings.LANGUAGE_CODE):
        too_large = [
            _("An attachment was too large and is not included: %(name)s")
            % {"name": name}
            for name in skipped
        ]
    content = "\n\n".join(
        part
        for part in [
            mentions.resolve(item, text, author=user),
            "\n".join(upload.markdown for upload in uploaded),
            "\n".join(too_large),
        ]
        if part
    )
    if token.occurrence_id:
        message.answer = answer(
            item, user=user, content=content, occurrence=token.occurrence
        )
    else:
        message.comment = add_comment(item, author=user, content=content)
    if skipped:
        message.error = "Larger than 25 MB, left out: " + ", ".join(skipped)
    return InboundStatus.POSTED


def _reject(token, mail, status, *, authenticated, now):
    """One short answer per token saying why. To the ``From`` address only
    when the receiving server confirmed it (else the answer could go to
    whoever was impersonated), otherwise to the token's person, who got
    the mail replied to."""
    if token.error_sent_at is not None:
        return
    user = token.user
    to_user = not (authenticated and mail.sender)
    if to_user and not user.is_active:
        return
    recipient = user.email if to_user else mail.sender
    language = (
        user.language if recipient.lower() == user.email.lower() else ""
    ) or settings.LANGUAGE_CODE
    with translation.override(language):
        reasons = {
            InboundStatus.WRONG_SENDER: _(
                "Replies are only posted when they come from the address the"
                " notification was sent to."
            ),
            InboundStatus.UNAUTHENTICATED: _(
                "The receiving mail server couldn't confirm that the reply"
                " came from your address (SPF, DKIM and DMARC)."
            ),
            InboundStatus.EXPIRED: _(
                "The reply address isn't valid any more. Reply to a newer"
                " notification or in the app."
            ),
            InboundStatus.NO_ACCESS: _(
                "You can't see or answer what you replied to any more."
            ),
        }
        headers = {"Auto-Submitted": "auto-replied"}
        if mail.message_id:
            headers |= {"In-Reply-To": mail.message_id, "References": mail.message_id}
        message = EmailMessage(
            _("Your reply couldn't be posted"),
            render_to_string(
                "inbound/rejection.txt",
                {"reason": reasons[status], "subject": mail.subject},
            ),
            sender("Biwak"),
            [recipient],
            headers=headers,
        )
    token.error_sent_at = now
    token.save(update_fields=["error_sent_at"])
    # Through the outbox: sent once this commits
    outbox.send(message, MailKind.REPLY_REFUSED)
