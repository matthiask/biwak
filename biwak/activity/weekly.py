"""The weekly mail of one's open to-dos (specs/notifications.md, "The weekly
to-dos", decided 2026-11-23): opted in per person, on Monday at 07:00 or
with quiet hours at the start of the first working day of the week, once a
week, whatever the delivery except no mails. The to-dos come from the
to-dos page's query (``due.todos()``), so through
``Item.objects.visible_to()``; what's waiting on others is the digest's."""

import datetime as dt
import logging

from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.formats import date_format
from django.utils.translation import gettext as _, ngettext

from biwak.accounts.languages import language_for
from biwak.accounts.models import MailDelivery, User
from biwak.accounts.quiet import in_working_time, is_away
from biwak.activity import digest, mentions
from biwak.api_conventions import absolute
from biwak.items import due
from biwak.outbox import sending as outbox
from biwak.outbox.models import Kind as MailKind


logger = logging.getLogger(__name__)

# The sections, as on the to-dos page by due date; "Today" is part of the
# week, and everything after next week one section
SECTIONS = [due.OVERDUE, due.THIS_WEEK, due.NEXT_WEEK, due.LATER]


def monday(day):
    """The Monday of ``day``'s week: the week the mail is about"""
    return day - dt.timedelta(days=day.weekday())


def is_due(user, local):
    """Whether this week's mail is due at the local time ``local``: on
    Monday from 07:00 (``DIGEST_AT``), with quiet hours during the working
    time of the first working day of the week. Only on that day: a mail
    missed (being away, no mails that day) waits for the next week."""
    from biwak.activity.mails import DIGEST_AT

    today = local.date()
    if user.weekly_todos_on is not None and user.weekly_todos_on >= monday(today):
        return False
    if user.quiet_hours:
        first = min(user.working_days or [0])
        return today.weekday() == first and in_working_time(user, local)
    return today.weekday() == 0 and local.time() >= DIGEST_AT


def sections(user, today):
    """``([(heading, [row])], undated)``: the person's open to-dos with a
    due date in the sections, the most urgent first, and how many have
    none"""
    todos = due.todos(user, assignee="me")
    found = {}
    for item in due.ordered(todos.filter(todo__due_on__isnull=False)):
        key = due.group_of(item.todo.due_on, today)
        key = due.THIS_WEEK if key == due.TODAY else key
        found.setdefault(key, []).append(digest.todo_row(item, user, today))
    headings = due.GROUP_LABELS | {due.LATER: _("Later")}
    result = [(str(headings[key]), found[key]) for key in SECTIONS if key in found]
    return result, todos.filter(todo__due_on__isnull=True).count()


def undated_line(count, *, after_others):
    """ "And 12 to-dos without a date" after dated ones, else "12 to-dos
    without a date" """
    if after_others:
        return ngettext(
            "And %(count)d to-do without a date",
            "And %(count)d to-dos without a date",
            count,
        ) % {"count": count}
    return ngettext(
        "%(count)d to-do without a date", "%(count)d to-dos without a date", count
    ) % {"count": count}


def weekly_mail(user, today):
    """The mail, None when there's nothing to say: no open to-dos at all
    and nothing overdue waiting on others"""
    from biwak.activity.mails import build_mail, unsubscribe_headers

    found, undated = sections(user, today)
    waiting = digest.waiting_on(user, today)
    if not (found or undated or waiting):
        return None
    week = date_format(monday(today), "DATE_FORMAT")
    settings_url = absolute(reverse("settings"))
    context = {
        "user": user,
        "heading": _("Your open to-dos, week of %(day)s") % {"day": week},
        "sections": found,
        "undated": undated_line(undated, after_others=bool(found)) if undated else "",
        # The to-dos page by due date, where they're "No date" at the end
        "undated_url": absolute(f"{reverse('todos')}?grouping=due#due-none"),
        "waiting": waiting,
        "settings_url": settings_url,
    }
    return build_mail(
        user,
        subject=_("[Biwak] %(heading)s") % context,
        template="mails/weekly",
        context=context,
        # Turned off in the settings, like the digest
        headers=unsubscribe_headers(settings_url, one_click=False),
    )


def _send(user, local):
    """Marks the week as done for the person and puts the mail into the
    outbox in one transaction; nothing while away (the week is skipped) or
    with nothing to say. Another run marking it first wins."""
    today = local.date()
    claimed = (
        User.objects
        .filter(pk=user.pk)
        .filter(Q(weekly_todos_on__isnull=True) | Q(weekly_todos_on__lt=monday(today)))
        .update(weekly_todos_on=today)
    )
    if not claimed or is_away(user, today):
        return False
    with translation.override(language_for(user)), mentions.reading_as(user):
        message = weekly_mail(user, today)
    if message is None:
        return False
    outbox.send(message, MailKind.WEEKLY)
    return True


def send_weekly(now):
    """The weekly mails due now; returns how many. Not to inactive people,
    those wanting no mails or whose address bounced."""
    local = timezone.localtime(now)
    people = User.objects.filter(
        Q(weekly_todos_on__isnull=True) | Q(weekly_todos_on__lt=monday(local.date())),
        weekly_todos=True,
        is_active=True,
        mail_undeliverable_at__isnull=True,
    ).exclude(mail_delivery=MailDelivery.NONE)
    count = 0
    for user in people:
        if not is_due(user, local):
            continue
        try:
            with transaction.atomic():
                count += _send(user, local)
        except Exception:
            logger.exception("Building the weekly to-dos mail failed")
    return count
