"""To-dos by due date (specs/todos.md, stage 2): the query behind the page,
the API and the iCal feed, and the grouping into overdue, today, this week,
later and no date. Everything goes through ``Item.objects.visible_to()``."""

import datetime as dt

from django.db.models import (
    BigIntegerField,
    DateField,
    Exists,
    F,
    IntegerField,
    OuterRef,
    Q,
    Value,
)
from django.db.models.functions import Coalesce
from django.utils import formats
from django.utils.translation import gettext_lazy as _

from biwak import schedules
from biwak.items.models import Assignment, Item, Kind, Status


OVERDUE, TODAY, THIS_WEEK, NEXT_WEEK, LATER, NO_DATE = (
    "overdue",
    "today",
    "this_week",
    "next_week",
    "later",
    "none",
)
GROUPS = [OVERDUE, TODAY, THIS_WEEK, NEXT_WEEK, LATER, NO_DATE]
# ``LATER`` (everything after next week) is shown as one section per month
# (decided 2026-11-21); the headings of the others
GROUP_LABELS = {
    OVERDUE: _("Overdue"),
    TODAY: _("Today"),
    THIS_WEEK: _("This week"),
    NEXT_WEEK: _("Next week"),
    NO_DATE: _("No date"),
}
# Sorts to-dos without a due date last, and is a plain field for cursors
NO_DATE_SORT = dt.date.max


def week_end(today):
    """The Sunday ending ``today``'s week: where ``this_week`` ends"""
    return today + dt.timedelta(days=6 - today.weekday())


def group_of(due_on, today):
    """The group a to-do is in: ``this_week`` runs until Sunday,
    ``next_week`` from Monday until the Sunday after, ``later`` is the rest"""
    if due_on is None:
        return NO_DATE
    if due_on < today:
        return OVERDUE
    if due_on == today:
        return TODAY
    sunday = week_end(today)
    if due_on <= sunday:
        return THIS_WEEK
    if due_on <= sunday + dt.timedelta(days=7):
        return NEXT_WEEK
    return LATER


def month_label(day, today):
    """ "December", or "January 2027" outside the current year"""
    return formats.date_format(day, "F" if day.year == today.year else "F Y")


def sections(todos, today):
    """``[(key, heading, [to-do])]`` for to-dos ordered by due date: the
    groups, with ``later`` split into one section per month (the key is
    ``later-2027-01``); empty ones are left out"""
    found = {}
    for item in todos:
        key = group_of(item.todo.due_on, today)
        if key == LATER:
            key = f"{LATER}-{item.todo.due_on:%Y-%m}"
        found.setdefault(key, []).append(item)
    result = []
    for key in GROUPS:
        if key == LATER:
            for month in sorted(k for k in found if k.startswith(f"{LATER}-")):
                day = found[month][0].todo.due_on
                result.append((month, month_label(day, today), found[month]))
        elif key in found:
            result.append((key, GROUP_LABELS[key], found[key]))
    return result


def badge_state(todo, today=None):
    """``OVERDUE`` or ``TODAY`` for an open to-do (its ``Todo`` detail) due
    before or on ``today``, else an empty string: completed to-dos are never
    overdue (the badge, specs/todos.md, "The to-do's page")"""
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
    way. ``assignee``: ``"me"``, ``"nobody"`` (nobody active) or a person's ID (``None``:
    anybody); ``assigned_by``: ``"me"`` for those the person assigned
    (to anybody else, or to the ``assignee`` given, themselves too;
    ``None``: anybody);
    ``visible_to_clients`` ``True`` or ``False`` (clients only
    ever see visible to-dos); ``group`` one of ``GROUPS``."""
    qs = (
        Item.objects
        .visible_to(user)
        .filter(
            kind=Kind.TODO,
            project__archived_at__isnull=True,
            project__is_template=False,
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
            # An IntegerField: -1 is out of the positions' range, which
            # Django folds into "never" for equality (cursors compare it)
            group_key=Coalesce(
                "todo__group__position", Value(-1), output_field=IntegerField()
            ),
            # Cursors need values (biwak/api_conventions.py)
            group_id_key=Coalesce(
                "todo__group_id", Value(0), output_field=BigIntegerField()
            ),
        )
    )
    if project is not None:
        qs = qs.filter(project=project)
    if assigned_by == "me":
        # One assignment both to the assignee and by the person
        if assignee == "nobody":
            return qs.none()
        assignments = Assignment.objects.filter(
            todo_id=OuterRef("pk"), assigned_by=user
        )
        if assignee == "me":
            assignments = assignments.filter(user=user)
        elif assignee is not None:
            assignments = assignments.filter(user=assignee)
            qs = known_assignee(qs, user, assignee)
        else:
            # To anybody else (specs/todos.md): giving oneself a to-do isn't
            # waiting on others
            assignments = assignments.exclude(user=user)
        qs = qs.filter(Exists(assignments))
    else:
        qs = assigned_to(qs, user, assignee)
    if visible_to_clients is not None and not user.is_client:
        qs = qs.filter(is_client_visible=visible_to_clients)
    if group is not None:
        qs = _in_group(qs, group, today or schedules.today())
    return qs


def assigned_to(qs, user, assignee):
    """The to-dos of ``qs`` assigned to ``assignee``: ``"me"`` (``user``),
    ``"nobody"`` (nobody active) or a person's ID; ``None``: anybody (the
    to-dos page and a list's filter, specs/todos.md)"""
    if assignee == "me":
        return qs.filter(todo__assignees=user)
    if assignee == "nobody":
        # Nobody active (decided 2026-11-21): assigned to nobody, or only to
        # people deactivated since, it's nobody's job either way
        return qs.exclude(
            Exists(
                Assignment.objects.filter(todo_id=OuterRef("pk"), user__is_active=True)
            )
        )
    if assignee is not None:
        return known_assignee(qs.filter(todo__assignees=assignee), user, assignee)
    return qs


def known_assignee(qs, user, assignee):
    """The to-dos of ``qs`` in projects where ``user`` may know the person
    ``assignee`` (an ID; ``Project.people_known_to()``): clients and
    externals filtering by somebody they may not know find nothing there,
    as ``assignees`` doesn't name them (2026-11-28, specs/access.md)"""
    from biwak.accounts.models import User, own_staff
    from biwak.projects.models import Membership, knows_everybody

    if knows_everybody(user):
        return qs
    known = Q(
        Exists(Membership.objects.filter(project=OuterRef("project"), user=assignee))
    )
    if not user.is_client and User.objects.filter(own_staff(), pk=assignee).exists():
        # Externals know the own staff of their all-access projects
        known |= Q(project__is_all_access=True)
    return qs.filter(known)


def _in_group(qs, group, today):
    """``group_of()`` as a filter"""
    sunday = week_end(today)
    return {
        OVERDUE: lambda: qs.filter(todo__due_on__lt=today),
        TODAY: lambda: qs.filter(todo__due_on=today),
        THIS_WEEK: lambda: qs.filter(todo__due_on__gt=today, todo__due_on__lte=sunday),
        NEXT_WEEK: lambda: qs.filter(
            todo__due_on__gt=sunday, todo__due_on__lte=sunday + dt.timedelta(days=7)
        ),
        LATER: lambda: qs.filter(todo__due_on__gt=sunday + dt.timedelta(days=7)),
        NO_DATE: lambda: qs.filter(todo__due_on__isnull=True),
    }[group]()


def started(today):
    """To-dos which have started: without a start date or one up to
    ``today``; the others are "Starting later" on My to-dos, the to-dos
    page and Home (specs/start-dates.md)"""
    return Q(todo__starts_on__isnull=True) | Q(todo__starts_on__lte=today)


def starting_later(qs, today):
    """Those of ``qs`` which haven't started, the next to start first"""
    return qs.filter(todo__starts_on__gt=today).order_by(
        "todo__starts_on",
        "due_key",
        "project__name",
        "parent__position",
        "position",
        "pk",
    )


def ordered(qs):
    """Open to-dos by due date, those without one last"""
    return qs.order_by("due_key", "project__name", "parent__position", "position", "pk")


PROJECT_ORDERING = (
    "project_key",
    "project_id",
    "parent__position",
    "parent_id",
    "group_key",
    "group_id_key",
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
