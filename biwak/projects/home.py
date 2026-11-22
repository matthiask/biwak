"""Home, the page at ``/`` (specs/dashboard.md): what needs the person
(to-dos due, check-ins, to-dos waiting on others), recent updates, their
projects, bookmarks and links. Each section is the short version of a page
which has the rest, built from the same queries; a fixed number of queries
whatever the number of projects. Nothing here has a state of its own: what
shows as unread is the lantern's."""

import datetime as dt

from django.db.models import Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from biwak import schedules
from biwak.activity import feed, lantern
from biwak.activity.models import Action
from biwak.bookmarks.models import Bookmark
from biwak.checkins import operations as checkin_ops
from biwak.items import due, glance
from biwak.items.models import Status
from biwak.projects import operations as project_ops
from biwak.projects.overview import overview
from biwak.search.views import KIND_ICONS


# Rows per section, and the window of "due soon" and "recent"
TODOS = 10
WAITING = 10
UPDATES = 10
UPDATES_EVENTS = 50
BOOKMARKS = 5
PROJECTS = 6
WINDOW = dt.timedelta(days=7)


def _in_window(user, today, *, assigned_by):
    """Open to-dos due within the window or overdue: mine, or those I
    assigned to others"""
    if assigned_by:
        todos = due.todos(user, assigned_by="me").exclude(todo__assignees=user)
    else:
        todos = due.todos(user, assignee="me")
    return glance.with_signals(todos.filter(todo__due_on__lte=today + WINDOW))


def due_todos(user, today, *, assigned_by=False):
    """Those of ``_in_window()`` which have started, the most urgent first;
    the others are "Starting later" (specs/start-dates.md)"""
    todos = _in_window(user, today, assigned_by=assigned_by)
    return list(due.ordered(todos.filter(due.started(today)))[:TODOS])


def starting_later(user, today, *, assigned_by=False):
    """Those of ``_in_window()`` whose start date hasn't come yet, the next
    to start first"""
    todos = _in_window(user, today, assigned_by=assigned_by)
    return list(due.starting_later(todos, today))


def recent_events(user):
    """The newest events of the last week in my bookmarked projects and
    those which mention or assign me anywhere, newest first, as the feed
    shows them"""
    me = [user.pk]
    bookmarked = Bookmark.objects.filter(user=user, project__isnull=False).values(
        "project"
    )
    events = feed.feed_events(user, since=timezone.now() - WINDOW).filter(
        Q(project__in=bookmarked)
        | Q(data__mentioned__contains=me)
        | Q(action=Action.ASSIGNED, data__assignees__contains=me)
    )
    found = list(events[:UPDATES_EVENTS])
    feed.attach(found, user)
    return found


def updates(events):
    """The feed's entries of the events, at most ``UPDATES`` of them,
    grouped by day"""
    today = timezone.localdate()
    return [
        (day, feed.day_label(day, today), entries)
        for day, entries in feed.by_day(feed.merge(events)[:UPDATES])
    ]


def project_cards(user):
    """``(projects, hint)``: the bookmarked projects (newest bookmark
    first) as ``overview()``'s, without bookmarks the most recently active
    ones the person is a member of, with the hint to bookmark"""
    projects = overview(user)
    marked = dict(
        Bookmark.objects.filter(user=user, project__isnull=False).values_list(
            "project", "created_at"
        )
    )
    bookmarked = sorted(
        (p for p in projects if p.pk in marked),
        key=lambda p: (marked[p.pk], p.pk),
        reverse=True,
    )
    if bookmarked:
        return bookmarked, False
    return [p for p in projects if p.user_is_member][:PROJECTS], True


def bookmarked_items(user):
    """The newest bookmarks of items, not of projects, outside archived
    projects"""
    return list(
        Bookmark.objects
        .visible_to(user)
        .filter(
            item__isnull=False,
            item__status=Status.ACTIVE,
            item__project__archived_at__isnull=True,
        )
        .select_related("item", "item__project", "item__answer")[:BOOKMARKS]
    )


def mark_unread(user, items):
    """``item.unread_notification`` (with ``read_url``, which the lantern's
    script posts to when the row's link is followed) for the items with
    unread notifications of the person; ``items`` may repeat"""
    items = list(items)
    found = lantern.unread_by_item(user, {item.pk for item in items})
    for item in items:
        item.unread_notification = found.get(item.pk)


def dashboard(request):
    user = request.user
    if "archived" in request.GET:
        # The old address of the archived projects
        return redirect(f"{reverse('projects')}?{request.GET.urlencode()}")
    today = schedules.today()
    mine = due_todos(user, today)
    later = starting_later(user, today)
    waiting = [] if user.is_client else due_todos(user, today, assigned_by=True)
    waiting_later = (
        [] if user.is_client else starting_later(user, today, assigned_by=True)
    )
    occurrences = checkin_ops.due(user)
    events = recent_events(user)
    bookmarks = bookmarked_items(user)
    projects, bookmark_hint = project_cards(user)
    mark_unread(
        user,
        [
            *mine,
            *later,
            *waiting,
            *waiting_later,
            *(o.question.item for o in occurrences),
            *(e.item for e in events if e.item is not None),
            *(b.item for b in bookmarks),
        ],
    )
    for event in events:
        event.unread_notification = (
            event.item.unread_notification if event.item is not None else None
        )
    for bookmark in bookmarks:
        bookmark.item.kind_icon = KIND_ICONS[bookmark.item.kind]
    open_count = due.todos(user, assignee="me").count()
    return render(
        request,
        "projects/home.html",
        {
            "sections": due.sections(mine, today),
            "later": later,
            "open_count": open_count if open_count > len(mine) else None,
            "waiting": due.sections(waiting, today),
            "waiting_later": waiting_later,
            "occurrences": occurrences,
            "days": updates(events),
            "projects": projects,
            "bookmark_hint": bookmark_hint and bool(projects),
            "bookmarks": bookmarks,
            "can_create": project_ops.can_create_project(user),
        },
    )
