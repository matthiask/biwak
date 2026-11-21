"""To-dos by due date (specs/todos.md, stage 2): the query behind the page,
the API and the iCal feed, and the grouping into overdue, today, this week,
later and no date. Everything goes through ``Item.objects.visible_to()``."""

import datetime as dt

from django.db.models import DateField, Exists, F, OuterRef, Value
from django.db.models.functions import Coalesce

from biwak import schedules
from biwak.items.models import Assignment, Item, Kind, Status


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
    assignee=None,
    assigned_by=None,
    completed=False,
    visible_to_clients=None,
    group=None,
    today=None,
):
    """To-dos the person sees, annotated with ``due_key`` (the due date,
    far away when there's none). Archived projects and lists are out of the
    way. ``assignee``: ``"me"``, ``"nobody"`` or a person's ID (``None``:
    anybody); ``assigned_by``: ``"me"`` for those the person assigned
    (to somebody, or to the ``assignee`` given; ``None``: anybody);
    ``visible_to_clients`` ``True`` or ``False`` (clients only
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
        .select_related("project", "parent", "creator", "todo__previous", "todo__group")
        .prefetch_related("todo__assignees")
        .annotate(
            due_key=Coalesce(
                "todo__due_on", Value(NO_DATE_SORT), output_field=DateField()
            ),
            # For ordering by project: to-dos outside groups come first, and
            # the first ordering field of cursors is a plain annotation
            project_key=F("project__name"),
            group_key=Coalesce("todo__group__position", Value(-1)),
        )
    )
    if project is not None:
        qs = qs.filter(project=project)
    if assigned_by == "me":
        # One assignment both to the assignee and by the person
        if assignee == "nobody":
            return qs.none()
        wanted = {"assigned_by": user}
        if assignee == "me":
            wanted["user"] = user
        elif assignee is not None:
            wanted["user"] = assignee
        qs = qs.filter(
            Exists(Assignment.objects.filter(todo_id=OuterRef("pk"), **wanted))
        )
    elif assignee == "me":
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


PROJECT_ORDERING = (
    "project_key",
    "project_id",
    "parent__position",
    "parent_id",
    "group_key",
    "todo__group_id",
    "position",
    "pk",
)


def ordered_by_project(qs):
    """Open to-dos in the order of the pages: projects by name, lists in
    their positions, ungrouped to-dos first, then the groups, and each to-do
    in its position"""
    return qs.order_by(*PROJECT_ORDERING)


def by_project(qs):
    """``ordered_by_project()`` as ``[(project, [(list, [(group, [to-do])])])]``,
    ``group`` is ``None`` for to-dos outside groups (listed first). One query:
    empty projects, lists and groups don't appear."""
    projects = []
    for item in ordered_by_project(qs):
        if not projects or projects[-1][0].pk != item.project_id:
            projects.append((item.project, []))
        lists = projects[-1][1]
        if not lists or lists[-1][0].pk != item.parent_id:
            lists.append((item.parent, []))
        groups = lists[-1][1]
        group = item.todo.group
        if not groups or (groups[-1][0] and groups[-1][0].pk) != (group and group.pk):
            groups.append((group, []))
        groups[-1][1].append(item)
    return projects
