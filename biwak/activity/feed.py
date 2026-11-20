"""The activity feed (specs/feed.md): the events a person can see, newest
first, merged into entries and grouped by day.

Everything starts from ``Event.objects.visible_to()``; the filters only
narrow it down. Pagination is by time with a cursor, not by offset: the
cursor of a page is the time and ID of its last event.
"""

import dataclasses
import datetime as dt

from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext, ngettext

from biwak.accounts.models import User
from biwak.activity.models import Action, Event
from biwak.items.models import Kind
from biwak.projects.models import Project


PAGE_SIZE = 50
# Consecutive events within this time of each other can be merged
MERGE_WINDOW = dt.timedelta(hours=1)


def feed_events(
    user,
    *,
    project=None,
    person=None,
    kind=None,
    action=None,
    visible_to_clients=False,
    since=None,
):
    """The events the person can see, newest first, narrowed down by the
    filters (all optional): the project, the actor, the kind of item, the
    action, only items clients can see, only events from ``since`` on"""
    events = Event.objects.visible_to(user).select_related(
        "actor", "project", "item", "item__parent"
    )
    if project is not None:
        events = events.filter(project=project)
    if person is not None:
        events = events.filter(actor=person)
    if kind:
        events = events.filter(item__kind=kind)
    if action:
        events = events.filter(action=action)
    if visible_to_clients:
        events = events.filter(item__is_client_visible=True)
    if since is not None:
        events = events.filter(created_at__gte=since)
    return events


def people_visible_to(user, project=None):
    """The people the viewer shares a project with (in ``project``, if
    given); a person's feed and the person filter only reveal these"""
    projects = Project.objects.accessible_to(user)
    if project is not None:
        projects = projects.filter(pk=project.pk)
    return User.objects.filter(memberships__project__in=projects).distinct()


def cursor_for(event):
    """``<microseconds since the epoch>,<id>`` of the event"""
    delta = event.created_at - dt.datetime(1970, 1, 1, tzinfo=dt.UTC)
    micros = (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds
    return f"{micros},{event.pk}"


def parse_cursor(value):
    """The time and ID of a cursor; ``ValueError`` if it isn't one"""
    micros, pk = value.split(",")
    return (
        dt.datetime(1970, 1, 1, tzinfo=dt.UTC) + dt.timedelta(microseconds=int(micros)),
        int(pk),
    )


def page(events, before=None):
    """One page of events and the cursor of the next one (or None). With
    ``before`` only older events than the cursor's."""
    if before:
        created_at, pk = parse_cursor(before)
        events = events.filter(
            Q(created_at__lt=created_at) | Q(created_at=created_at, pk__lt=pk)
        )
    found = list(events[: PAGE_SIZE + 1])
    more = len(found) > PAGE_SIZE
    found = found[:PAGE_SIZE]
    attach(found)
    return found, cursor_for(found[-1]) if more else None


def attach(events):
    """What rendering needs besides the event: the assigned people's names
    (``event.assignee_names``) and the project on the item, which saves a
    query per link"""
    ids = {
        pk
        for event in events
        if event.action == Action.ASSIGNED
        for pk in event.data.get("assignees", [])
    }
    names = {u.pk: u.get_short_name() for u in User.objects.filter(pk__in=ids)}
    for event in events:
        if event.item is not None:
            event.item.project = event.project
        event.assignee_names = [
            names[pk] for pk in event.data.get("assignees", []) if pk in names
        ]


def _noun(kind, count):
    if kind == Kind.TODO:
        return ngettext("%(count)d to-do", "%(count)d to-dos", count)
    if kind == Kind.LIST:
        return ngettext("%(count)d list", "%(count)d lists", count)
    if kind == Kind.MESSAGE:
        return ngettext("%(count)d message", "%(count)d messages", count)
    if kind == Kind.FOLDER:
        return ngettext("%(count)d folder", "%(count)d folders", count)
    if kind == Kind.DOC:
        return ngettext("%(count)d doc", "%(count)d docs", count)
    return ngettext("%(count)d item", "%(count)d items", count)


@dataclasses.dataclass
class Entry:
    """One or more events by the same person doing the same in the same
    list or project, newest first"""

    events: list

    @property
    def latest(self):
        return self.events[0]

    @property
    def count(self):
        return len(self.events)

    @property
    def is_merged(self):
        return self.count > 1

    @property
    def what(self):
        """ "5 to-dos" for merged entries"""
        kinds = {e.item.kind if e.item else None for e in self.events}
        kind = kinds.pop() if len(kinds) == 1 else None
        return _noun(kind, self.count) % {"count": self.count}

    @property
    def where(self):
        """The list or project the events happened in"""
        key = container(self.latest)
        return key[2]

    @property
    def is_client_visible(self):
        return all(e.item and e.item.is_client_visible for e in self.events)


def container(event):
    """What counts as "the same list or project": a to-do's list, otherwise
    the project; as (kind, id, name)"""
    item = event.item
    if item is not None and item.parent_id is not None:
        return ("item", item.parent_id, item.parent.title)
    return ("project", event.project_id, event.project.name)


def local_day(event):
    return timezone.localtime(event.created_at).date()


def merge(events):
    """Entries from events newest first: consecutive events of the same
    person with the same action in the same list or project, each within
    an hour of the one before and on the same day, become one entry"""
    entries = []
    for event in events:
        if entries:
            last = entries[-1].events[-1]
            if (
                last.actor_id == event.actor_id
                and last.action == event.action
                and container(last)[:2] == container(event)[:2]
                and local_day(last) == local_day(event)
                and last.created_at - event.created_at <= MERGE_WINDOW
            ):
                entries[-1].events.append(event)
                continue
        entries.append(Entry([event]))
    return entries


def by_day(entries):
    """``[(date, [entry, …]), …]``, days in the local time zone (TIME_ZONE)"""
    days = []
    for entry in entries:
        day = local_day(entry.latest)
        if days and days[-1][0] == day:
            days[-1][1].append(entry)
        else:
            days.append((day, [entry]))
    return days


def day_label(day, today=None):
    today = today or timezone.localdate()
    if day == today:
        return gettext("Today")
    if day == today - dt.timedelta(days=1):
        return gettext("Yesterday")
    return None
