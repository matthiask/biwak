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

from biwak import cursors
from biwak.accounts.models import User
from biwak.activity import mentions
from biwak.activity.models import Action, Event
from biwak.items.models import Comment, Item, Kind, Message
from biwak.organizations.names import display_name
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
    # An answer's link needs its occurrence (``Item.get_absolute_url()``)
    events = Event.objects.visible_to(user).select_related(
        "actor", "project", "item", "item__parent", "item__answer"
    )
    if project is not None:
        events = events.filter(project=project)
    else:
        # Archived projects are out of the feeds across projects
        events = events.filter(project__archived_at__isnull=True)
    if person is not None:
        events = events.filter(actor=person)
    if kind:
        events = events.filter(item__kind=kind)
    if action:
        events = events.filter(action=action)
    if visible_to_clients:
        # What clients see (``Event.objects.visible_to()``)
        events = events.filter(item__is_client_visible=True, is_client_visible=True)
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
    return cursors.encode(event.created_at, event.pk)


def page(events, before=None, *, user):
    """One page of events and the cursor of the next one (or None). With
    ``before`` only older events than the cursor's."""
    if before:
        created_at, pk = cursors.decode(before)
        events = events.filter(
            Q(created_at__lt=created_at) | Q(created_at=created_at, pk__lt=pk)
        )
    found = list(events[: PAGE_SIZE + 1])
    more = len(found) > PAGE_SIZE
    found = found[:PAGE_SIZE]
    attach(found, user)
    return found, cursor_for(found[-1]) if more else None


def _people_of(event):
    """The people an event is about: those assigned, those it was shared
    with"""
    match event.action:
        case Action.ASSIGNED:
            return event.data.get("assignees", [])
        case Action.SHARED:
            return event.data.get("people", [])
    return []


def attach(events, user):
    """What rendering needs besides the event: the assigned people's names
    (``event.assignee_names``, also those something was shared with), the target list of moves the viewer may
    see (``event.target_list``) and the project on the item, which saves a
    query per link"""
    ids = {pk for event in events for pk in _people_of(event)}
    people = list(User.objects.filter(pk__in=ids))
    # Whom the viewer may know, per project (clients and partners: members)
    known = {}
    for event in events:
        if event.item is not None:
            event.item.project = event.project
        if event.project_id not in known and _people_of(event):
            known[event.project_id] = {
                u.pk: display_name(u, user)
                for u in event.project.people_known_to(user, people)
            }
        names = known.get(event.project_id, {})
        event.assignee_names = [names[pk] for pk in _people_of(event) if pk in names]
    add_excerpts(events)
    add_target_lists(events, user)


EXCERPT_CHARS = 200


def add_excerpts(events):
    """``event.excerpt`` (specs/glance.md): the text as it is now, for
    events of comments (the comment's) and for every other event of a
    message (the message's: created, edited, archived and so on; decided
    2026-11-20), two queries at most for all events;
    empty if the comment is gone. The events are the viewer's, so the items are
    visible to them."""
    from biwak.templatetags.biwak import excerpt

    comment_ids = {
        event.data.get("comment")
        for event in events
        if event.action == Action.COMMENTED and event.item is not None
    } - {None}
    comments = {c.pk: c for c in Comment.objects.filter(pk__in=comment_ids)}
    message_ids = {event.item_id for event in events if _is_message_text(event)}
    messages = {m.pk: m.content for m in Message.objects.filter(pk__in=message_ids)}
    for event in events:
        text = ""
        if event.action == Action.COMMENTED and event.item is not None:
            comment = comments.get(event.data.get("comment"))
            # Only a comment of the event's own item
            if comment is not None and comment.item_id == event.item_id:
                text = comment.content
        elif _is_message_text(event):
            text = messages.get(event.item_id, "")
        event.excerpt = excerpt(text, EXCERPT_CHARS, event.item) if text else ""


def add_target_lists(events, user):
    """``event.target_list``: the name of the list a to-do moved to, or ""
    if the viewer may not see it (specs/feed.md). Checked now, not when the
    event was recorded, in one query for all events. Clients see the list's
    current title if it is visible to them, and nothing for events without
    the list's ID (recorded before it was stored); the own organization
    staff fall back to the title at the time for lists they can't find any
    more, partners (who may not see that project) don't."""
    moves = [e for e in events if e.action == Action.MOVED and e.data.get("to")]
    ids = {e.data.get("to_id") for e in moves} - {None}
    lists = dict(
        Item.objects
        .visible_to(user)
        .filter(pk__in=ids, kind=Kind.LIST)
        .values_list("pk", "title")
    )
    old_titles = None  # Whether the viewer gets them, asked once if needed
    for event in moves:
        title = lists.get(event.data.get("to_id"))
        if title is None:
            if old_titles is None:
                old_titles = user.sees_all_access
            if old_titles:
                title = event.data["to"]
        event.target_list = title or ""
    for event in events:
        if not hasattr(event, "target_list"):
            event.target_list = ""


def _is_message_text(event):
    return event.item is not None and event.item.kind == Kind.MESSAGE


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
    if kind == Kind.QUESTION:
        return ngettext("%(count)d check-in", "%(count)d check-ins", count)
    if kind == Kind.ANSWER:
        return ngettext("%(count)d answer", "%(count)d answers", count)
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
    def contents(self):
        """What a person reacted with, oldest first, each once"""
        return list(
            dict.fromkeys(
                e.data.get("content", "")
                for e in reversed(self.events)
                if e.action == Action.REACTED
            )
        )

    @property
    def where(self):
        """The list or project the events happened in"""
        key = container(self.latest)
        return key[2]


def container(event):
    """What counts as "the same list or project": a to-do's list, otherwise
    the project; as (kind, id, name)"""
    item = event.item
    if item is not None and item.parent_id is not None:
        return ("item", item.parent_id, mentions.plain(item.parent.title, item.parent))
    return ("project", event.project_id, event.project.name)


def local_day(event):
    return timezone.localtime(event.created_at).date()


def same_place(last, event):
    """Reactions merge per item ("Ada reacted to Order the tent: 👍 🎉",
    specs/reactions.md), the rest per list or project"""
    if last.action == Action.REACTED:
        return last.item_id == event.item_id
    return container(last)[:2] == container(event)[:2]


def merge(events):
    """Entries from events newest first: consecutive events of the same
    person with the same action in the same list or project (reactions: on
    the same item), each within an hour of the one before and on the same
    day, become one entry"""
    entries = []
    for event in events:
        if entries:
            last = entries[-1].events[-1]
            if (
                last.actor_id == event.actor_id
                and last.action == event.action
                and same_place(last, event)
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
