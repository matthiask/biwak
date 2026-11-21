"""Mails of check-ins (specs/checkins.md): the question and the summary of
the answers. Everything goes out after the transaction commits
(``after_commit``), through the outbox (specs/mail-sending.md); the mails of single answers are the normal
notifications (``biwak.activity``)."""

import logging

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import translation
from django.utils.formats import date_format
from django.utils.translation import gettext as _

from biwak.activity import mentions
from biwak.activity.mails import (
    absolute,
    build_mail,
    host,
    plain_text,
    unsubscribe_headers,
    unsubscribe_url,
)
from biwak.activity.notify import who_can_see
from biwak.inbound.tokens import reply_to
from biwak.items.models import Item
from biwak.outbox import sending as outbox
from biwak.outbox.models import Kind as MailKind


logger = logging.getLogger(__name__)


def after_commit(build, occurrence, people):
    """Sends ``build(person, occurrence)`` to each of the people once the
    transaction has committed, if they're still active and see the question
    then (like ``biwak.activity.mails._deliverable()``); a mail which can't
    be sent is logged and doesn't keep the others from going out"""
    pks = [person.pk for person in people]
    transaction.on_commit(lambda: _send_all(build, occurrence, pks), robust=True)


def _send_all(build, occurrence, pks):
    # As it is now, not as it was loaded
    item = Item.objects.select_related("project").get(pk=occurrence.question.item_id)
    for user in who_can_see(item).filter(pk__in=pks).order_by("pk"):
        try:
            with (
                translation.override(user.language or settings.LANGUAGE_CODE),
                mentions.reading_as(user),
            ):
                message = build(user, occurrence)
            # Its own transaction: the outbox sends it once it's committed
            with transaction.atomic():
                outbox.send(message, MailKind.CHECKIN)
        except Exception:
            logger.exception("Sending a check-in mail failed")


def question_url(occurrence):
    """The answer form of the occurrence (the mail and the API's "due")"""
    item = occurrence.question.item
    return (
        absolute(reverse("question_answer", args=[item.pk]))
        + f"?occurrence={occurrence.pk}"
    )


def thread(user, occurrence):
    """One thread per person and occurrence: the question (its message ID)
    and the summary"""
    return (
        f"<question-{occurrence.question.item_id}-{occurrence.pk}-{user.pk}@{host()}>"
    )


def reply_headers(user, occurrence):
    """Replying answers the occurrence (``notifications.md``, stage 2): a
    reply token's address in ``Reply-To``, nothing while replying is off"""
    return reply_to(user, occurrence.question.item, occurrence=occurrence)


def _context(user, occurrence):
    question = occurrence.question
    item = question.item
    return {
        "user": user,
        "item": item,
        "title": mentions.plain(item.title, item),
        "project": item.project,
        "question": question,
        "occurrence": occurrence,
        "schedule": question.schedule_description,
        "url": question_url(occurrence),
        "page_url": absolute(item.get_absolute_url()),
        "unsubscribe_url": unsubscribe_url(user, item),
        "settings_url": absolute(reverse("settings")),
    }


def _build(user, occurrence, *, subject, context, name, first=False):
    """``first``: the mail starting the occurrence's thread"""
    thread_id = thread(user, occurrence)
    headers = unsubscribe_headers(context["unsubscribe_url"])
    if first:
        # Only the question takes replies: a reply to the summary isn't
        # an answer
        headers |= {"Message-ID": thread_id} | reply_headers(user, occurrence)
    else:
        headers |= {"In-Reply-To": thread_id, "References": thread_id}
    return build_mail(
        user,
        subject=subject,
        template=f"checkins/mails/{name}",
        context=context,
        headers=headers,
    )


def question_mail(user, occurrence):
    """The question, with the link to the answer form"""
    context = _context(user, occurrence)
    subject = _("[%(project)s] %(title)s") % context
    return _build(
        user, occurrence, subject=subject, context=context, name="question", first=True
    )


def summary_mail(user, occurrence):
    """All answers of the occurrence in one mail"""
    from biwak.checkins.operations import answers_of

    context = _context(user, occurrence)
    context["day"] = date_format(occurrence.date, "j. F Y")
    context["answers"] = [
        {
            "author": answer.author,
            "content": answer.content,
            "text": plain_text(answer.content, answer.item),
            "item": answer.item,
            "url": absolute(answer.item.get_absolute_url()),
        }
        for answer in reversed(answers_of(occurrence))
    ]
    subject = _("[%(project)s] %(title)s: answers of %(day)s") % context
    return _build(user, occurrence, subject=subject, context=context, name="summary")
