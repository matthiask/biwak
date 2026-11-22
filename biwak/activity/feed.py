"""The activity feed (specs/feed.md): the events a person can see, newest
first, merged into entries and grouped by day.

Everything starts from ``Event.objects.visible_to()``; the filters only
narrow it down. Pagination is by time with a cursor, not by offset: the
cursor of a page is the time and ID of its last event.
"""

import dataclasses
import datetime as dt
import itertools

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
    # The page ends between entries (decided 2026-11-22): looking ahead
    # up to another page for where it can
    found = list(events[: 2 * PAGE_SIZE + 1])
    more = len(found) > PAGE_SIZE
    if more:
        edge = _edge(found[: 2 * PAGE_SIZE], PAGE_SIZE)
        more = len(found) > edge
        found = found[:edge]
    attach(found, user)
    return found, cursor_for(found[-1]) if more else None


def _people_of(event):
    """The people an event is about: those assigned, those it was shared
    with"""
    match event.action:
        case Action.ASSIGNED | Action.UNASSIGNED:
            return event.data.get("assignees", [])
        case Action.SHARED:
            return event.data.get("people", [])
    return []


def _named(person, viewer):
    """The person's name as the viewer knows it, "(inactive)" after it for
    people who left (specs/handover.md)"""
    name = display_name(person, viewer)
    if not person.is_active:
        return gettext("%(name)s (inactive)") % {"name": name}
    return name


def attach(events, user):
    """What rendering needs besides the event: the assigned people's names
    (``event.assignee_names``, also those something was shared with), the target list of moves the viewer may
    see (``event.target_list``) and the project on the item, which saves a
    query per link"""
    ids = {pk for event in events for pk in _people_of(event)}
    people = list(User.objects.filter(pk__in=ids))
    # Whom the viewer may know, per project (clients and externals: members)
    known = {}
    for event in events:
        if event.item is not None:
            event.item.project = event.project
        if event.project_id not in known and _people_of(event):
            known[event.project_id] = {
                u.pk: _named(u, user)
                for u in event.project.people_known_to(user, people)
            }
        names = known.get(event.project_id, {})
        event.assignee_names = [names[pk] for pk in _people_of(event) if pk in names]
        # By ID, for what puts several events together (specs/timeline.md)
        event.assignee_by_id = {
            pk: names[pk] for pk in _people_of(event) if pk in names
        }
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
    more, externals (who may not see that project) don't."""
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
    add_projects(events, user)


def add_projects(events, user):
    """``event.source_project`` and ``event.target_project``: the names of
    the projects an item moved from and to (specs/lists-across-projects.md),
    each only if the viewer may open it now, else "". Checked now, in one
    query for all events, with the project's current name."""
    moves = [e for e in events if e.action == Action.MOVED and "to_project" in e.data]
    ids = {
        e.data.get(key) for e in moves for key in ("from_project_id", "to_project_id")
    }
    ids -= {None}
    names = (
        dict(
            Project.objects
            .accessible_to(user)
            .filter(pk__in=ids)
            .values_list("pk", "name")
        )
        if ids
        else {}
    )
    for event in events:
        event.source_project = names.get(event.data.get("from_project_id"), "")
        event.target_project = names.get(event.data.get("to_project_id"), "")


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
    def is_conversation(self):
        return False

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


class Conversation(Entry):
    """Comments on one item by anyone, newest first (``merge()``); the page
    shows them oldest first, as they were said"""

    @property
    def is_conversation(self):
        return True

    @property
    def item(self):
        return self.latest.item

    @property
    def comments(self):
        return self.events[::-1]


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


def conversations(events):
    """Events newest first, with the comments on one item that follow each
    other closely (each within an hour of the one before and on the same
    day) gathered into one ``Conversation`` at the place of the newest;
    other events in between don't break it up. Comments with no one to talk
    to stay events. Entries and events, newest first."""
    open_ones = {}  # item ID -> the entry of the latest comments on it
    result = []
    for event in events:
        if event.action == Action.COMMENTED and event.item_id is not None:
            entry = open_ones.get(event.item_id)
            if (
                entry is not None
                and local_day(entry.events[-1]) == local_day(event)
                and entry.events[-1].created_at - event.created_at <= MERGE_WINDOW
            ):
                entry.events.append(event)
                continue
            entry = open_ones[event.item_id] = Conversation([event])
            result.append(entry)
        else:
            result.append(event)
    return [
        e.events[0] if isinstance(e, Conversation) and e.count == 1 else e
        for e in result
    ]


def _together(older, newer):
    """Within the merge window and on the same day"""
    return (
        local_day(older) == local_day(newer)
        and newer.created_at - older.created_at <= MERGE_WINDOW
    )


# Toggles and moves of an item a later one may cancel (``merge()``)
NET_CHANGES = {Action.COMPLETED, Action.REOPENED, Action.MOVED}


def _edge(events, size):
    """Where a page of ``events`` (newest first) ends: after ``size``
    events or later, where no entry of ``merge()`` and nothing cancelling
    out would be split; ``len(events)`` if there's no such place"""
    position = {event.pk: n for n, event in enumerate(events)}
    reach = list(range(len(events)))  # the furthest partner of each event

    def link(a, b):
        a, b = sorted((position[a.pk], position[b.pk]))
        reach[a] = max(reach[a], b)

    for entry in merge(events):
        for newer, older in itertools.pairwise(entry.events):
            link(newer, older)
    last = {}  # item ID and actor -> the older event of what may cancel
    for event in reversed(events):
        if event.action in NET_CHANGES and event.item_id:
            key = (event.item_id, event.actor_id)
            if key in last and _together(last[key], event):
                link(last[key], event)
            last[key] = event
    furthest = -1
    for n, partner in enumerate(reach):
        furthest = max(furthest, partner)
        if n + 1 >= size and furthest <= n:
            return n + 1
    return len(events)


def _others(events):
    """The toggles and moves of the items of ``events`` between the first
    and the last of them which aren't in ``events`` (a person's feed leaves
    out the others'): another person's still breaks up what cancels out,
    so a person's feed shows that person's events as the whole feed does"""
    changes = [e for e in events if e.action in NET_CHANGES and e.item_id]
    if not changes:
        return []
    times = [e.created_at for e in changes]
    return list(
        Event.objects
        .filter(
            item__in={e.item_id for e in changes},
            action__in=NET_CHANGES,
            created_at__range=(min(times), max(times)),
        )
        .exclude(pk__in=[e.pk for e in changes])
        .only("pk", "item_id", "actor_id", "action", "created_at", "data")
    )


def merge(events):
    """Entries from events newest first: comments on the same item become
    conversations (``conversations()``); consecutive events of the same
    person with the same action in the same list or project (reactions: on
    the same item), each within an hour of the one before and on the same
    day, become one entry. A person's completing and reopening an item
    back and forth (each within an hour of the one before, on the same
    day) shows as the net change (``timeline.cancelled()``)."""
    from biwak.activity.timeline import cancelled, moved_back

    others = _others(events)
    hidden = cancelled(events, together=_together, others=others) | moved_back(
        events, together=_together, others=others
    )
    events = [event for event in events if event.pk not in hidden]
    entries = []
    for event in conversations(events):
        if isinstance(event, Conversation):
            entries.append(event)
            continue
        if entries and not entries[-1].is_conversation:
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
