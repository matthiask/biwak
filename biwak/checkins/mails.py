"""Mails of check-ins (specs/checkins.md): the question and the summary of
the answers. Everything goes out after the transaction commits
(``after_commit``); the mails of single answers are the normal
notifications (``biwak.activity``)."""

import logging
from email.utils import make_msgid

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import translation
from django.utils.formats import date_format
from django.utils.translation import gettext as _

from biwak.activity import mentions
from biwak.activity.mails import absolute, host, plain_text, sender, unsubscribe_url


logger = logging.getLogger(__name__)


def after_commit(build, occurrence, people):
    """Sends ``build(person, occurrence)`` to each of the people once the
    transaction has committed; a mail which can't be sent is logged and
    doesn't keep the others from going out"""
    pks = [person.pk for person in people]
    transaction.on_commit(lambda: _send_all(build, occurrence, pks), robust=True)


def _send_all(build, occurrence, pks):
    from biwak.accounts.models import User

    for user in User.objects.filter(pk__in=pks).order_by("pk"):
        try:
            with translation.override(user.language or settings.LANGUAGE_CODE):
                message = build(user, occurrence)
            message.send()
        except Exception:
            logger.exception("Sending a check-in mail failed")


def question_url(occurrence):
    """The answer form of the occurrence"""
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
    """Where replying by mail goes (``notifications.md``, stage 2 puts the
    reply token's address into ``Reply-To`` here); nothing yet"""
    return {}


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
        "settings_url": absolute(reverse("notification_settings")),
    }


def _build(user, occurrence, *, subject, context, name, first=False):
    """``first``: the mail starting the occurrence's thread"""
    thread_id = thread(user, occurrence)
    headers = {
        "Message-ID": thread_id if first else make_msgid(domain=host()),
        "List-Unsubscribe": f"<{context['unsubscribe_url']}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        "Auto-Submitted": "auto-generated",
    }
    if not first:
        headers |= {"In-Reply-To": thread_id, "References": thread_id}
    headers |= reply_headers(user, occurrence)
    message = EmailMultiAlternatives(
        subject,
        render_to_string(f"checkins/mails/{name}.txt", context),
        sender("Biwak"),
        [user.email],
        headers=headers,
    )
    message.attach_alternative(
        render_to_string(f"checkins/mails/{name}.html", context), "text/html"
    )
    return message


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
