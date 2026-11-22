"""Forwarding mails into Biwak (specs/forwarding.md): receiving them at
``inbox@REPLY_DOMAIN``, filing them as a message or a to-do, deleting
them. Views, the API and the CLI call these."""

import datetime as dt
import logging
import re

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.core.mail import EmailMessage
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone, translation
from django.utils.formats import date_format
from django.utils.translation import gettext as _

from biwak.accounts.languages import language_for
from biwak.accounts.middleware import set_user_name
from biwak.accounts.models import User
from biwak.activity.mails import sender
from biwak.files import attachments
from biwak.files.models import new_key
from biwak.forwarding.models import KEEP_DAYS, ForwardedFile, ForwardedMail
from biwak.forwarding.parse import forward
from biwak.inbound import tokens
from biwak.inbound.models import InboundMessage, InboundStatus
from biwak.items import operations as ops
from biwak.outbox import sending as outbox
from biwak.outbox.models import Kind as MailKind


logger = logging.getLogger(__name__)

# The local part of the one address (decided 2026-11-22)
LOCAL_PART = "inbox"
# Each file, like the attachments of replies (decided 2026-11-21)
MAX_FILE_SIZE = 25 * 2**20
# Refused forwards answered per sender and hour, like the replies per
# token; the rest are dropped without an answer
RATE_LIMIT = 20
RATE_WINDOW = dt.timedelta(hours=1)
REFUSED = {InboundStatus.WRONG_SENDER, InboundStatus.UNAUTHENTICATED}


def enabled():
    """On with replying by mail (``REPLY_DOMAIN`` and Resend's settings)"""
    return tokens.enabled()


def address():
    return f"{LOCAL_PART}@{settings.REPLY_DOMAIN}"


def is_inbox(recipients):
    """Whether the mail was sent to the inbox"""
    if not enabled():
        return False
    return address().lower() in {recipient.lower() for recipient in recipients}


def can_forward(user):
    """Staff, own and externals (decided 2026-11-22); not clients"""
    return user.is_authenticated and user.is_active and not user.is_client


def forwarder(address):
    """The active staff member with this address, or None"""
    if not address:
        return None
    return (
        User.objects
        .filter(email__iexact=address, is_active=True, is_client=False)
        .order_by("pk")
        .first()
    )


def forwarded_for(user):
    """The person's forwarded mails, newest first; nobody else's"""
    if not can_forward(user):
        return ForwardedMail.objects.none()
    return ForwardedMail.objects.filter(user=user)


def waiting(user):
    """How many forwarded mails wait for the person (the menu's count)"""
    if not enabled() or not can_forward(user):
        return 0
    return forwarded_for(user).count()


# Receiving --------------------------------------------------------------------


def receive(message, mail, now):
    """A mail to the inbox (``biwak.inbound.receive``, in its transaction):
    kept for the forwarder when it comes from an active staff member's
    address and the receiving server confirmed that; otherwise refused
    with a short answer. Returns the ``InboundStatus``."""
    from biwak.inbound.receive import is_authenticated

    user = forwarder(mail.sender)
    authenticated = is_authenticated(mail)
    if user is not None and authenticated:
        set_user_name(user)
        store(user, mail, now=now)
        return InboundStatus.FORWARDED
    status = (
        InboundStatus.WRONG_SENDER if user is None else InboundStatus.UNAUTHENTICATED
    )
    refused = (
        InboundMessage.objects
        .filter(
            sender=mail.sender[:300],
            token=None,
            status__in=REFUSED,
            received_at__gt=now - RATE_WINDOW,
        )
        .exclude(pk=message.pk)
        .count()
    )
    if refused >= RATE_LIMIT:
        return InboundStatus.RATE_LIMITED
    _refuse(mail, status, user=user, authenticated=authenticated)
    return status


def _markdown_name(name):
    return re.sub(r"([\\\[\]])", r"\\\1", " ".join(name.split()))


@attachments.cleans_up_files
@transaction.atomic
def store(user, mail, *, now=None):
    """The forwarded mail in the person's list: the original's subject,
    sender, date and recipients, its text with the files where they were
    (inline images) or below, files over 25 MB left out with a line
    saying which"""
    parsed = forward(mail)
    forwarded = ForwardedMail.objects.create(
        user=user,
        received_at=now or timezone.now(),
        subject=parsed.subject,
        sender_name=parsed.sender_name[:300],
        sender_email=parsed.sender_email[:300],
        sent_on=parsed.sent_on,
        to=parsed.to,
        cc=parsed.cc,
    )
    text = parsed.text
    below = []
    too_large = []
    for file in parsed.files:
        if len(file.content) > MAX_FILE_SIZE:
            too_large.append(file.name)
            text = text.replace(file.placeholder, "")
            continue
        stored = ForwardedFile(
            mail=forwarded,
            key=new_key(),
            name=attachments.clean_name(file.name),
            size=len(file.content),
            content_type=file.content_type,
        )
        attachments.store(
            stored.file, stored.name, ContentFile(file.content, name=stored.name)
        )
        stored.save()
        if file.placeholder in text:
            text = text.replace(file.placeholder, stored.markdown)
        else:
            below.append(stored.markdown)
    with translation.override(language_for(user)):
        lines = [
            _("An attachment was too large and is not included: %(name)s")
            % {"name": _markdown_name(name)}
            for name in too_large
        ]
    forwarded.text = "\n\n".join(
        part for part in [text.strip(), "\n".join(below), "\n".join(lines)] if part
    )
    forwarded.save(update_fields=["text"])
    if too_large:
        logger.info("Forwarded mail %s: left out %s", forwarded.pk, too_large)
    return forwarded


def _refuse(mail, status, *, user, authenticated):
    """A short answer saying why: to ``From`` when the receiving server
    confirmed it, else to the staff member whose address it claims (the
    answer could otherwise go to whoever was impersonated), else none"""
    if authenticated and mail.sender:
        recipient = mail.sender
    elif user is not None:
        recipient = user.email
    else:
        return
    language = (
        language_for(user)
        if user is not None and recipient.lower() == user.email.lower()
        else settings.LANGUAGE_CODE
    )
    with translation.override(language):
        reasons = {
            InboundStatus.WRONG_SENDER: _(
                "Forwarded mails are only kept when they come from the address"
                " of a staff member."
            ),
            InboundStatus.UNAUTHENTICATED: _(
                "The receiving mail server couldn't confirm that the mail came"
                " from your address (SPF, DKIM and DMARC)."
            ),
        }
        headers = {"Auto-Submitted": "auto-replied"}
        if mail.message_id:
            headers |= {"In-Reply-To": mail.message_id, "References": mail.message_id}
        message = EmailMessage(
            _("Your forwarded mail couldn't be kept"),
            render_to_string(
                "forwarding/refused.txt",
                {"reason": reasons[status], "subject": mail.subject},
            ),
            sender("Biwak"),
            [recipient],
            headers=headers,
        )
    outbox.send(message, MailKind.REPLY_REFUSED)


# Filing -----------------------------------------------------------------------


def _escaped(text):
    return re.sub(r"([\\`*_\[\]<>])", r"\\\1", text)


def forwarded_line(mail):
    """ "Forwarded from Ada Example <ada@example.org>, 3 Dec 2026", and the
    recipients below, in the language of the moment"""
    who = _escaped(mail.sender_name)
    if mail.sender_email:
        who = f"{who} <{mail.sender_email}>" if who else f"<{mail.sender_email}>"
    if mail.sent_on and who:
        line = _("Forwarded from %(sender)s, %(date)s") % {
            "sender": who,
            "date": date_format(mail.sent_on, "SHORT_DATE_FORMAT"),
        }
    elif who:
        line = _("Forwarded from %(sender)s") % {"sender": who}
    else:
        line = _("Forwarded")
    lines = [line]
    if mail.to:
        lines.append(_("To: %(people)s") % {"people": _escaped(mail.to)})
    if mail.cc:
        lines.append(_("Cc: %(people)s") % {"people": _escaped(mail.cc)})
    return "\n".join(lines)


def _content(mail, *, project, actor):
    """The text for the item: the line about the original, the text, the
    files as attachments in ``project`` by ``actor`` (linked when the item
    is saved)"""
    text = mail.text
    for file in mail.files.all():
        with file.file.open("rb") as handle:
            content = handle.read()
        attachment = attachments.upload(
            project=project,
            file=ContentFile(content, name=file.name),
            uploaded_by=actor,
        )
        text = text.replace(f"(forwarded:{file.key})", f"(attachment:{attachment.key})")
    with translation.override(language_for(actor)):
        line = forwarded_line(mail)
    return "\n\n".join(part for part in [line, text] if part)


def _check(mail, actor):
    if mail.user_id != actor.pk or not can_forward(actor):
        raise PermissionDenied("Only the forwarder files a forwarded mail.")


@attachments.cleans_up_files
@transaction.atomic
def file_as_message(mail, *, project, title, actor, category=None):
    """An internal message by the forwarder with the text and files;
    posting it tells people as posting a message does. The forwarded mail
    is gone afterwards."""
    _check(mail, actor)
    item = ops.create_message(
        project=project,
        title=title,
        content=_content(mail, project=project, actor=actor),
        category=category,
        creator=actor,
        visible=False,
    )
    mail.delete()
    return item


@attachments.cleans_up_files
@transaction.atomic
def file_as_todo(mail, *, todolist, title, actor, group=None):
    """A to-do in the list (optionally a group) with the text as its notes
    and the files attached; the forwarded mail is gone afterwards"""
    _check(mail, actor)
    if todolist.is_client_visible:
        # Filed mails are internal (specs/forwarding.md)
        raise ValueError("Forwarded mails are filed into internal lists only.")
    item = ops.create_todo(
        todolist=todolist,
        title=title,
        creator=actor,
        group=group,
        notes=_content(mail, project=todolist.project, actor=actor),
    )
    mail.delete()
    return item


@transaction.atomic
def delete(mail, *, actor):
    _check(mail, actor)
    mail.delete()


@transaction.atomic
def delete_old(*, now=None):
    """Deletes forwarded mails nobody filed after KEEP_DAYS (fairy_tasks);
    their files go when the transaction commits. Returns how many."""
    cutoff = (now or timezone.now()) - dt.timedelta(days=KEEP_DAYS)
    old = ForwardedMail.objects.filter(received_at__lt=cutoff)
    count = old.count()
    old.delete()
    return count
