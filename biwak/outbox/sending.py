"""Sending through the outbox (specs/mail-sending.md).

``send(message, kind)`` writes the row in the current transaction and
sends it once that commits (nothing on a rollback), one attempt with a
short timeout. What fails waits for ``retry()`` (``send_mails``, every
minute): after 1, 2, 5, 10 and 30 minutes, then hourly; after 24 hours it's
given up and the admins are told. The transport is Django's default mailer
(``EMAIL_URL``, or Resend's API through anymail in production), which
``mail_admins`` uses directly, so telling the admins can't loop.

No double sends: a row is locked (``select_for_update(skip_locked)``) while
it's being sent, so two ``send_mails`` (or one and the attempt after the
commit) never send it both; Resend gets the row's ``Idempotency-Key`` and
drops a repeat after a crash between its answer and our commit, for 24
hours, the time we try at most.
"""

import datetime as dt
import logging
from email.utils import parseaddr
from functools import partial

from django.conf import settings
from django.core import mail as django_mail
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from biwak.outbox.models import Kind, OutgoingMail, serialize


logger = logging.getLogger(__name__)

# The waits after the first, second, ... failed attempt, then hourly
BACKOFF = [dt.timedelta(minutes=minutes) for minutes in (1, 2, 5, 10, 30)] + [
    dt.timedelta(hours=1)
]
# Given up after a day (Resend keeps idempotency keys for 24 hours: a mail
# tried later could go out twice)
GIVE_UP_AFTER = dt.timedelta(hours=24)
# Rows deleted after 90 days, like incoming mails (decided 2026-11-24:
# "did she get the invitation?" a few months later)
RETENTION = dt.timedelta(days=90)
# At most this many retries per run
RETRY_BATCH = 200


def send(message, kind, *, now=None):
    """Queues the message (a Django ``EmailMessage``) and sends it after the
    commit; returns the row"""
    now = now or timezone.now()
    kind = Kind(kind)
    expires_at = None
    if kind == Kind.LOGIN_CODE:
        # A code arriving after its ten minutes is no use (the person asks
        # for a new one)
        expires_at = now + dt.timedelta(seconds=settings.ACCOUNT_LOGIN_BY_CODE_TIMEOUT)
    row = OutgoingMail.objects.create(
        kind=kind,
        recipients=[parseaddr(str(a))[1] for a in message.recipients()],
        message=serialize(message),
        created_at=now,
        # The attempt after the commit has the first minute; a retry finds
        # it only if that attempt never happened (a crash in between)
        next_attempt_at=now + BACKOFF[0],
        expires_at=expires_at,
    )
    transaction.on_commit(partial(deliver, row.pk), robust=True)
    return row


def idempotency_key(row):
    """The row's ID, with the installation's host (more than one
    installation may share a Resend account) and the row's creation time
    (a recreated database starts at the same IDs again, which Resend
    refuses for 24 hours when the body differs)"""
    from biwak.activity.mails import host

    created = row.created_at.astimezone(dt.UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    return f"{host()}/outgoing-mail/{row.pk}/{created}"


def deliver(pk, *, now=None):
    """Sends the row if it's still waiting and nobody else is sending it;
    returns what ``attempt()`` did, or None"""
    with transaction.atomic():
        row = (
            OutgoingMail.objects
            .pending()
            .select_for_update(skip_locked=True)
            .filter(pk=pk)
            .first()
        )
        if row is None:
            return None
        return attempt(row, now=now or timezone.now())


SENT = "sent"
FAILED = "failed"
RATE_LIMITED = "rate-limited"
GIVEN_UP = "given-up"
EXPIRED = "expired"


def attempt(row, *, now):
    """One attempt at the locked row; saves it"""
    if row.expires_at and now >= row.expires_at:
        # The last error stays: why it wasn't sent
        error = " ".join(
            part
            for part in ["Not sent before the login code expired.", row.last_error]
            if part
        )
        _give_up(row, now, error[:2000])
        return EXPIRED
    if now >= row.created_at + GIVE_UP_AFTER:
        _give_up(row, now, row.last_error)
        return GIVEN_UP
    message = row.email_message()
    # For the Resend backend (biwak.outbox.resend), ignored by the others
    message.outbox_kind = row.kind
    message.idempotency_key = idempotency_key(row)
    row.attempts += 1
    try:
        if not django_mail.mailers.default.send_messages([message]):
            raise RuntimeError("The mailer sent nothing.")
    except Exception as exc:  # noqa: BLE001 (whatever the transport raises)
        row.last_error = f"{type(exc).__name__}: {exc}"[:2000]
        if getattr(exc, "status_code", None) == 429:
            # Too many requests: not the mail's fault, again next minute
            row.attempts -= 1
            row.next_attempt_at = now + BACKOFF[0]
            result = RATE_LIMITED
        else:
            row.next_attempt_at = now + BACKOFF[min(row.attempts, len(BACKOFF)) - 1]
            result = FAILED
        logger.warning("Sending mail %s failed: %s", row.pk, row.last_error)
        row.save()
        return result
    status = getattr(message, "anymail_status", None)
    row.provider_id = (status.message_id or "") if status else ""
    row.sent_at = now
    row.next_attempt_at = None
    # Only bookkeeping is kept (decided 2026-11-21)
    row.message = None
    row.last_error = ""
    row.save()
    return SENT


def _give_up(row, now, error):
    row.given_up_at = now
    row.next_attempt_at = None
    row.last_error = error
    row.save()


def retry(*, now=None):
    """Sends what's due again (``send_mails``); tells the admins about the
    mails given up, in one mail. Returns ``{result: count}``."""
    now = now or timezone.now()
    due = list(
        OutgoingMail.objects
        .pending()
        .filter(next_attempt_at__lte=now)
        .order_by("next_attempt_at", "pk")
        .values_list("pk", flat=True)[:RETRY_BATCH]
    )
    counts = {}
    given_up = []
    for pk in due:
        result = deliver(pk, now=now)
        if result is None:
            continue
        counts[result] = counts.get(result, 0) + 1
        if result == GIVEN_UP:
            given_up.append(pk)
        if result == RATE_LIMITED:
            # The rest next minute
            break
    if given_up:
        tell_admins(OutgoingMail.objects.filter(pk__in=given_up).order_by("pk"))
    return counts


def tell_admins(rows):
    rows = list(rows)
    logger.error("Gave up sending %s mails", len(rows))
    lines = [
        f"- {row.get_kind_display()} to {', '.join(row.recipients)}:"
        f" {row.subject!r}, {row.attempts} attempts, since"
        f" {timezone.localtime(row.created_at):%Y-%m-%d %H:%M}; {row.last_error}"
        for row in rows
    ]
    url = settings.BASE_URL.rstrip("/") + reverse(
        "admin:outbox_outgoingmail_changelist"
    )
    try:
        # Around the outbox: the plain mailer
        django_mail.mail_admins(
            f"{len(rows)} mails not sent",
            "These mails couldn't be sent for a day, the outbox gave up on"
            f" them:\n\n{'\n'.join(lines)}\n\nTheir content is kept in the"
            f" outbox for 30 days: {url}?state=given_up\n",
        )
    except Exception:
        logger.exception("Telling the admins about mails not sent failed")


def prune(*, now=None):
    """Deletes rows older than 30 days (``fairy_tasks``); returns how many"""
    cutoff = (now or timezone.now()) - RETENTION
    return OutgoingMail.objects.filter(created_at__lt=cutoff).delete()[0]
