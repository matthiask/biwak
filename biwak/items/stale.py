"""Stale to-dos: warned, then marked obsolete (specs/stale-todos.md)

An open to-do is stale when the latest of its last activity (its latest
event except reactions, or its creation), its due date and its start date
is more than its group's ``stale_after`` days ago. The daily run
(``fairy_tasks``) clears the warnings of to-dos touched since, marks those
warned ``WARNING`` days ago obsolete, and warns about at most
``WARNINGS_PER_PROJECT`` more per project, the oldest first. The staff
following a warned to-do get one mail a day (``send_warnings()``, called by
``send_mails``)."""

import datetime as dt
import logging

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.db.models import (
    DateTimeField,
    ExpressionWrapper,
    F,
    Max,
    OuterRef,
    Subquery,
    Value,
)
from django.db.models.functions import Cast, Coalesce, Greatest
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.formats import date_format
from django.utils.translation import gettext as _, ngettext

from biwak.accounts.languages import language_for
from biwak.accounts.models import MailDelivery, User
from biwak.accounts.quiet import in_working_time, is_away
from biwak.activity import mentions
from biwak.activity.models import Action, Event, Subscription
from biwak.activity.operations import record
from biwak.api_conventions import absolute
from biwak.items.models import STALE_AFTER, Item, Kind, StaleWarning, Status, Todo
from biwak.outbox import sending as outbox
from biwak.outbox.models import Kind as MailKind


logger = logging.getLogger(__name__)

# Days between the warning and marking it obsolete (decided 2026-11-26)
WARNING = 14
# Warnings per project and day, the oldest first (decided 2026-11-26): the
# first run would warn about every old to-do at once
WARNINGS_PER_PROJECT = 20


def is_on():
    return settings.STALE_TODOS


def _last_activity():
    """The latest event of the to-do except reactions, as a subquery"""
    return Subquery(
        Event.objects
        .filter(item=OuterRef("pk"))
        .exclude(action=Action.REACTED)
        .values("item")
        .annotate(latest=Max("created_at"))
        .values("latest")[:1]
    )


def open_todos():
    """Open to-dos which may get stale: not trashed, not in a template, not
    in an archived list or project, annotated with ``touched_at`` (the
    latest of the last activity, the due date and the start date) and
    ``stale_days``"""
    return (
        Item.objects
        .filter(
            kind=Kind.TODO,
            status=Status.ACTIVE,
            todo__completed_at__isnull=True,
            parent__status=Status.ACTIVE,
            project__archived_at__isnull=True,
            project__is_template=False,
        )
        .annotate(last_activity_at=Coalesce(_last_activity(), F("created_at")))
        .annotate(
            touched_at=Greatest(
                F("last_activity_at"),
                Cast("todo__due_on", DateTimeField()),
                Cast("todo__starts_on", DateTimeField()),
            ),
            stale_days=Coalesce("todo__group__stale_after", Value(STALE_AFTER)),
        )
    )


def stale_todos(now):
    """The open to-dos which are stale at ``now``, the oldest first"""
    return (
        open_todos()
        .annotate(
            stale_from=ExpressionWrapper(
                F("touched_at") + F("stale_days") * Value(dt.timedelta(days=1)),
                output_field=DateTimeField(),
            )
        )
        .filter(stale_from__lt=now)
        .order_by("touched_at", "pk")
    )


def touched(item):
    """``(when, reason)`` for one to-do as ``open_todos()`` sees it:
    ``reason`` is "due", "starts" or "activity" (also its creation)"""
    todo = item.todo
    # Annotated by ``open_todos()``, else one query
    latest = (
        getattr(item, "last_activity_at", None)
        or (
            Event.objects
            .filter(item=item)
            .exclude(action=Action.REACTED)
            .aggregate(latest=Max("created_at"))["latest"]
        )
    )
    activity = timezone.localdate(latest or item.created_at)
    candidates = [(activity, "activity")]
    if todo.due_on:
        candidates.append((todo.due_on, "due"))
    if todo.starts_on:
        candidates.append((todo.starts_on, "starts"))
    # The activity wins a tie: "Nothing since" says more than the date
    return max(candidates, key=lambda c: (c[0], c[1] == "activity"))


def banner_reason(item):
    """The banner's first sentence"""
    day, reason = touched(item)
    formatted = date_format(day, "DATE_FORMAT")
    if reason == "due":
        return _("It was due on %(day)s.") % {"day": formatted}
    return _("Nothing happened since %(day)s.") % {"day": formatted}


def reason_text(item):
    """ "Nothing since 3 May" or "Due 3 May" """
    day, reason = touched(item)
    formatted = date_format(day, "DATE_FORMAT")
    if reason == "due":
        return _("Due %(day)s") % {"day": formatted}
    return _("Nothing since %(day)s") % {"day": formatted}


def obsolete_on(todo):
    """The day a warned to-do will be marked obsolete"""
    return timezone.localdate(todo.stale_warned_at) + dt.timedelta(days=WARNING)


def is_warned(item):
    """Open and warned: the to-do's page shows the banner"""
    todo = item.todo
    return todo.stale_warned_at is not None and not todo.is_completed


# The daily run --------------------------------------------------------------


def run(now=None):
    """Clears, marks and warns; nothing unless ``STALE_TODOS``. Returns
    ``(cleared, marked, warned)``."""
    if not is_on():
        return (0, 0, 0)
    now = now or timezone.now()
    cleared = clear_warnings(now)
    marked = mark_warned(now)
    warned = warn(now)
    return (cleared, marked, warned)


def clear_warnings(now):
    """Warned to-dos which aren't stale any more (touched since, a due or
    start date moved, kept for a year now) or aren't open any more: no
    warning. Their unsent mails are dropped when sending."""
    stale = stale_todos(now).values("pk")
    return (
        Todo.objects
        .filter(stale_warned_at__isnull=False)
        .exclude(item__in=stale)
        .update(stale_warned_at=None)
    )


def mark_warned(now):
    """Marks the to-dos still stale obsolete on the day ``obsolete_on()``
    promised (the local date of the warning plus ``WARNING`` days), as
    Biwak (no actor): warned before the start of the local day ``WARNING
    - 1`` days ago, whatever the time of the run or a DST change."""
    day = timezone.localdate(now) - dt.timedelta(days=WARNING - 1)
    before = timezone.make_aware(dt.datetime.combine(day, dt.time.min))
    items = stale_todos(now).filter(todo__stale_warned_at__lt=before)
    count = 0
    for item in Item.objects.filter(pk__in=items.values("pk")).select_related(
        "project"
    ):
        try:
            with transaction.atomic():
                _mark(item)
            count += 1
        except Exception:
            logger.exception("Marking a stale to-do obsolete failed")
    return count


def _mark(item):
    from biwak.items import operations as ops

    ops.mark_obsolete(item, actor=None)
    Todo.objects.filter(item=item).update(stale_warned_at=None)


def warn(now):
    """Warns about stale to-dos not warned yet, at most
    ``WARNINGS_PER_PROJECT`` per project, the oldest first: sets
    ``stale_warned_at`` and writes a ``StaleWarning`` for each person to
    tell"""
    chosen = []
    per_project = {}
    candidates = stale_todos(now).filter(todo__stale_warned_at__isnull=True)
    for item in candidates.select_related("project"):
        taken = per_project.get(item.project_id, 0)
        if taken >= WARNINGS_PER_PROJECT:
            continue
        per_project[item.project_id] = taken + 1
        chosen.append(item)
    with transaction.atomic():
        for item in chosen:
            Todo.objects.filter(item=item).update(stale_warned_at=now)
            StaleWarning.objects.bulk_create(
                StaleWarning(user=user, item=item, created_at=now)
                for user in recipients(item)
            )
    return len(chosen)


def recipients(item):
    """The to-do's subscribers who are staff (own or externals), active,
    and see it; never clients (decided 2026-11-26)"""
    subscribed = Subscription.objects.filter(item=item).values("user")
    return [
        user
        for user in User.objects.filter(
            pk__in=subscribed, is_active=True, is_client=False
        )
        if Item.objects.visible_to(user).filter(pk=item.pk).exists()
    ]


def report(now=None, *, project=None):
    """What ``./manage.py stale_todos`` shows: per project the counts and
    the stale to-dos, the oldest first, each with its ``state``: "warned"
    (``obsolete_on``), "to_warn" (by the next run) or "later" (over the
    day's limit)"""
    now = now or timezone.now()
    todos = stale_todos(now).select_related("project", "parent", "todo__group")
    if project is not None:
        todos = todos.filter(project=project)
    projects = {}
    for item in todos:
        entry = projects.setdefault(
            item.project, {"stale": 0, "warned": 0, "to_warn": 0, "todos": []}
        )
        entry["stale"] += 1
        if item.todo.stale_warned_at is not None:
            entry["warned"] += 1
            state = "warned"
        elif entry["to_warn"] < WARNINGS_PER_PROJECT:
            entry["to_warn"] += 1
            state = "to_warn"
        else:
            state = "later"
        entry["todos"].append({"item": item, "state": state})
    return projects


# Keeping --------------------------------------------------------------------


@transaction.atomic
def keep(item, *, actor):
    """ "Keep open": an internal event telling nobody, which starts the
    clock again; the warning goes"""
    record(
        actor=actor, action=Action.KEPT, project=item.project, item=item, internal=True
    )
    Todo.objects.filter(item=item).update(stale_warned_at=None)


_SALT = "biwak.stale.keep"


def keep_token(user, item):
    return signing.dumps([user.pk, item.pk], salt=_SALT)


def read_keep_token(token):
    """``(person ID, item ID)``, or None for a token we didn't sign"""
    try:
        user_pk, item_pk = signing.loads(token, salt=_SALT)
    except signing.BadSignature, ValueError, TypeError:
        return None
    return user_pk, item_pk


def keep_url(user, item):
    return absolute(reverse("todo_keep_link", args=[keep_token(user, item)]))


# The mail -------------------------------------------------------------------


def _due(user, local):
    """From 07:00 (``DIGEST_AT``), with quiet hours in the working time"""
    from biwak.activity.mails import DIGEST_AT

    if user.quiet_hours:
        return in_working_time(user, local)
    return local.time() >= DIGEST_AT


def _still_warned(user, pks):
    """The warned, open to-dos among ``pks`` the person still sees"""
    return list(
        Item.objects
        .visible_to(user)
        .filter(
            pk__in=pks,
            todo__stale_warned_at__isnull=False,
            todo__completed_at__isnull=True,
        )
        .select_related("project", "parent", "todo")
        .order_by("project__name", "project_id", "parent__position", "position")
    )


def warning_mail(user, items):
    """The mail about ``items``, by project and list"""
    from biwak.activity.mails import build_mail, unsubscribe_headers

    count = len(items)
    day = min(obsolete_on(item.todo) for item in items)
    sections = []
    for item in items:
        key = (item.project, item.parent)
        if not sections or sections[-1][0] != key:
            sections.append((key, []))
        sections[-1][1].append({
            "title": mentions.title(item.title, item),
            "url": absolute(item.get_absolute_url()),
            "reason": reason_text(item),
            "keep_url": keep_url(user, item),
        })
    heading = ngettext(
        "%(count)d to-do will be marked as obsolete on %(day)s",
        "%(count)d to-dos will be marked as obsolete on %(day)s",
        count,
    ) % {"count": count, "day": date_format(day, "DATE_FORMAT")}
    subject = ngettext(
        "[Biwak] %(count)d to-do will be marked as obsolete",
        "[Biwak] %(count)d to-dos will be marked as obsolete",
        count,
    ) % {"count": count}
    settings_url = absolute(reverse("settings"))
    context = {
        "user": user,
        "heading": heading,
        "sections": [
            {"project": project, "list": todolist, "todos": todos}
            for (project, todolist), todos in sections
        ],
        "settings_url": settings_url,
    }
    return build_mail(
        user,
        subject=subject,
        template="mails/stale",
        context=context,
        headers=unsubscribe_headers(settings_url, one_click=False),
    )


def _deliverable(user):
    return (
        user.is_active
        and user.mail_undeliverable_at is None
        and user.mail_delivery != MailDelivery.NONE
    )


def send_warnings(now):
    """The warning mails due now, one per person; returns how many.
    Warnings of people who get no mail (no mails, inactive, bounced, away)
    or about to-dos not warned any more are dropped."""
    local = timezone.localtime(now)
    pending = {}
    for user_id, pk in StaleWarning.objects.filter(sent_at__isnull=True).values_list(
        "user", "pk"
    ):
        pending.setdefault(user_id, []).append(pk)
    count = 0
    for user in User.objects.filter(pk__in=pending):
        pks = pending[user.pk]
        if _deliverable(user) and not _due(user, local):
            continue
        try:
            with transaction.atomic():
                count += _send(user, pks, now, local)
        except Exception:
            logger.exception("Building the stale to-dos mail failed")
    return count


def _send(user, pks, now, local):
    """Marks the warnings sent and puts the mail into the outbox; another
    run marking them first wins"""
    claimed = list(
        StaleWarning.objects
        .select_for_update(skip_locked=True)
        .filter(pk__in=pks, sent_at__isnull=True)
        .values_list("item", flat=True)
    )
    StaleWarning.objects.filter(pk__in=pks, sent_at__isnull=True).update(sent_at=now)
    if not claimed or not _deliverable(user) or is_away(user, local.date()):
        return 0
    with translation.override(language_for(user)), mentions.reading_as(user):
        items = _still_warned(user, claimed)
        if not items:
            return 0
        message = warning_mail(user, items)
    outbox.send(message, MailKind.STALE)
    return 1
