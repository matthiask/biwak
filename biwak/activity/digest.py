"""What the daily digest adds to the notifications (specs/notifications.md,
"Digest", decided 2026-11-23): the person's to-dos needing them today, the
overdue to-dos they wait on, what's for them in particular first, and one
line per item for the rest. Everything comes from the queries of Home and
the to-dos page (``biwak.items.due``), so it goes through
``Item.objects.visible_to()``."""

from django.db.models import Q
from django.utils.text import get_text_list
from django.utils.translation import gettext as _, ngettext

from biwak.accounts.quiet import away_detail
from biwak.activity import mentions
from biwak.activity.models import Action
from biwak.api_conventions import absolute
from biwak.formats import format_range
from biwak.items import due


def _row(item, user, today, *, others=False):
    """A to-do as one line: its title and link, its project, what's urgent
    about it ("Overdue", "Today", "Starts today") and its dates; with
    ``others`` who has it, by the names the person may know, those away
    with "(away until 3 Dec)" """
    todo = item.todo
    state = due.badge_state(todo, today)
    if state == due.OVERDUE:
        label = _("Overdue")
    elif state == due.TODAY:
        label = _("Today")
    else:
        label = _("Starts today")
    row = {
        "title": mentions.title(item.title, item),
        "url": absolute(item.get_absolute_url()),
        "project": item.project,
        "label": label,
        "overdue": state == due.OVERDUE,
        # "Today" alone on the due date, as on the rows (specs/start-dates.md)
        "dates": ""
        if state == due.TODAY
        else format_range(todo.starts_on, todo.due_on, "MONTH_DAY_FORMAT"),
        "is_client_visible": item.is_client_visible,
    }
    if others:
        people = item.project.people_known_to(
            user, [p for p in todo.assignees.all() if p.pk != user.pk]
        )
        row["assignees"] = ", ".join(
            f"{p} ({detail})" if p.is_active and (detail := away_detail(p)) else str(p)
            for p in people
        )
    return row


def needs_you(user, today):
    """The person's open to-dos which are overdue, due today or start today
    (specs/start-dates.md), the most urgent first: Home's "Due" without
    the rest of the week"""
    todos = due.todos(user, assignee="me").filter(
        Q(todo__due_on__lte=today) | Q(todo__starts_on=today)
    )
    return [_row(item, user, today) for item in due.ordered(todos)]


def waiting_on(user, today):
    """Open, overdue to-dos the person assigned to others (Home's "Waiting
    on others", ``biwak todos --assigned-by-me``), with who has them"""
    todos = (
        due
        .todos(user, assigned_by="me")
        .exclude(todo__assignees=user)
        .filter(todo__due_on__lt=today)
    )
    return [_row(item, user, today, others=True) for item in due.ordered(todos)]


def todos(user, today):
    """Both to-do sections, ``{"needs_you": […], "waiting": […]}``"""
    return {"needs_you": needs_you(user, today), "waiting": waiting_on(user, today)}


def for_you(notification):
    """Whether the notification is for the person in particular: they were
    mentioned or assigned (the same test as push notifications,
    specs/web-push.md); those come first, in full"""
    from biwak.activity.push import wanted

    return wanted(notification)


def _people(events):
    return get_text_list(
        list(dict.fromkeys(str(event.actor) for event in events)), _("and")
    )


def summary(notifications, user):
    """One line for an item's notifications (the rest of the digest):
    what happened, in the mails' words (``describe()``), each line once,
    then "3 comments by Ada and Bob.", "2 reactions by Carl." """
    from biwak.activity.mails import describe

    events = sorted((n.event for n in notifications), key=lambda e: e.created_at)
    comments = [e for e in events if e.action == Action.COMMENTED]
    reactions = [e for e in events if e.action == Action.REACTED]
    lines = dict.fromkeys(
        describe(e, user)
        for e in events
        if e.action not in {Action.COMMENTED, Action.REACTED}
    )
    parts = list(lines)
    if comments:
        parts.append(
            ngettext(
                "%(count)d comment by %(people)s.",
                "%(count)d comments by %(people)s.",
                len(comments),
            )
            % {"count": len(comments), "people": _people(comments)}
        )
    if reactions:
        parts.append(
            ngettext(
                "%(count)d reaction by %(people)s.",
                "%(count)d reactions by %(people)s.",
                len(reactions),
            )
            % {"count": len(reactions), "people": _people(reactions)}
        )
    return " ".join(parts)
