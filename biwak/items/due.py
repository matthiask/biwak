"""To-dos by due date (specs/todos.md, stage 2): the query behind the page,
the API and the iCal feed, and the grouping into overdue, today, this week,
later and no date. Everything goes through ``Item.objects.visible_to()``."""

import datetime as dt

from django.db.models import DateField, Value
from django.db.models.functions import Coalesce

from biwak import schedules
from biwak.items.models import Item, Kind, Status


OVERDUE, TODAY, THIS_WEEK, LATER, NO_DATE = (
    "overdue",
    "today",
    "this_week",
    "later",
    "none",
)
GROUPS = [OVERDUE, TODAY, THIS_WEEK, LATER, NO_DATE]
# Sorts to-dos without a due date last, and is a plain field for cursors
NO_DATE_SORT = dt.date.max


def week_end(today):
    """The Sunday ending ``today``'s week: where ``this_week`` ends"""
    return today + dt.timedelta(days=6 - today.weekday())


def group_of(due_on, today):
    """The group a to-do is in: ``this_week`` runs until Sunday"""
    if due_on is None:
        return NO_DATE
    if due_on < today:
        return OVERDUE
    if due_on == today:
        return TODAY
    if due_on <= week_end(today):
        return THIS_WEEK
    return LATER


def badge_state(todo, today=None):
    """``OVERDUE`` or ``TODAY`` for an open to-do (its ``Todo`` detail) due
    before or on ``today``, else an empty string: completed to-dos are never
    overdue (the badge, specs/ui-round-1.md, part 5)"""
    if todo.due_on is None or todo.is_completed:
        return ""
    group = group_of(todo.due_on, today or schedules.today())
    return group if group in (OVERDUE, TODAY) else ""


def todos(
    user,
    *,
    project=None,
    todolist=None,
    assignee=None,
    completed=False,
    visible_to_clients=None,
    group=None,
    today=None,
):
    """To-dos the person sees, annotated with ``due_key`` (the due date,
    far away when there's none). Archived projects and lists are out of the
    way. ``assignee``: ``"me"``, ``"nobody"`` or a person's ID (``None``:
    anybody); ``visible_to_clients`` ``True`` or ``False`` (clients only
    ever see visible to-dos); ``group`` one of ``GROUPS``."""
    qs = (
        Item.objects
        .visible_to(user)
        .filter(
            kind=Kind.TODO,
            project__archived_at__isnull=True,
            parent__status=Status.ACTIVE,
            todo__completed_at__isnull=not completed,
        )
        .select_related("project", "parent", "creator", "todo__previous")
        .prefetch_related("todo__assignees")
        .annotate(
            due_key=Coalesce(
                "todo__due_on", Value(NO_DATE_SORT), output_field=DateField()
            )
        )
    )
    if project is not None:
        qs = qs.filter(project=project)
    if todolist is not None:
        qs = qs.filter(parent=todolist)
    if assignee == "me":
        qs = qs.filter(todo__assignees=user)
    elif assignee == "nobody":
        qs = qs.filter(todo__assignees__isnull=True)
    elif assignee is not None:
        qs = qs.filter(todo__assignees=assignee)
    if visible_to_clients is not None and not user.is_client:
        qs = qs.filter(is_client_visible=visible_to_clients)
    if group is not None:
        qs = _in_group(qs, group, today or schedules.today())
    return qs


def _in_group(qs, group, today):
    """``group_of()`` as a filter"""
    sunday = week_end(today)
    return {
        OVERDUE: lambda: qs.filter(todo__due_on__lt=today),
        TODAY: lambda: qs.filter(todo__due_on=today),
        THIS_WEEK: lambda: qs.filter(todo__due_on__gt=today, todo__due_on__lte=sunday),
        LATER: lambda: qs.filter(todo__due_on__gt=sunday),
        NO_DATE: lambda: qs.filter(todo__due_on__isnull=True),
    }[group]()


def ordered(qs):
    """Open to-dos by due date, those without one last"""
    return qs.order_by("due_key", "project__name", "parent__position", "position", "pk")
