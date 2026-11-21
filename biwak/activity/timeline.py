"""The to-do page's timeline (specs/timeline.md): the comments and what
happened to the to-do between them, oldest first, one list.

The events come from ``Event.objects.visible_to()``, so a client sees only
those of the time the to-do was visible to them; the lists' names are
resolved like the feed's (``feed.add_target_lists()``). Consecutive changes
of the same person within ten minutes become one line.
"""

import dataclasses
import datetime as dt

from django.utils.formats import date_format
from django.utils.text import get_text_list
from django.utils.translation import gettext as _

from biwak.activity import feed, mentions
from biwak.activity.models import Action, Event


# Consecutive changes of one person within this time of each other are one
# line (the editing session of ``record()``, the undo of completing)
MERGE_WINDOW = dt.timedelta(minutes=10)

# What the timeline tells; edits only when they changed the title or the
# due date, visibility switches only to staff
ACTIONS = [
    Action.COMPLETED,
    Action.REOPENED,
    Action.MOVED,
    Action.ASSIGNED,
    Action.UNASSIGNED,
    Action.EDITED,
    Action.VISIBILITY_CHANGED,
    Action.TRASHED,
    Action.RESTORED,
]
# What an edit tells
EDIT_FIELDS = ("title", "due_on")


def _edit_fields(event):
    return [f for f in event.data.get("fields", []) if f in EDIT_FIELDS]


def _kind(event):
    """What the line's icon shows (``_timeline_line.html`` has the icons)"""
    if event.action == Action.EDITED:
        return "due" if _edit_fields(event) == ["due_on"] else "title"
    if event.action == Action.VISIBILITY_CHANGED:
        return "visible" if event.data.get("visible") else "hidden"
    return str(event.action)


def _due(value):
    if not value:
        return _("removed the due date")
    return _("set the due date to %(date)s") % {
        "date": date_format(dt.date.fromisoformat(value), "j. M Y")
    }


def phrases(event, it):
    """What the event says, as a list of phrases (an edit may say two);
    ``it``: "this" for the first of a line, "it" after that"""
    data = event.data
    match event.action:
        case Action.COMPLETED:
            return [_("completed %(it)s") % {"it": it}]
        case Action.REOPENED:
            return [_("reopened %(it)s") % {"it": it}]
        case Action.MOVED if "group" in data:
            if data["group"]:
                to = mentions.plain(data["group"])
                return [_("moved %(it)s to %(to)s") % {"it": it, "to": to}]
            return [_("moved %(it)s out of its group") % {"it": it}]
        case Action.MOVED:
            # Another list's name only if the viewer may see it
            to = mentions.plain(event.target_list) or _("another list")
            return [_("moved %(it)s to %(to)s") % {"it": it, "to": to}]
        case Action.ASSIGNED:
            names = get_text_list(event.assignee_names, _("and")) or _("someone")
            return [_("assigned %(people)s") % {"people": names}]
        case Action.UNASSIGNED:
            names = get_text_list(event.assignee_names, _("and")) or _("someone")
            return [_("removed %(people)s") % {"people": names}]
        case Action.EDITED:
            result = []
            fields = _edit_fields(event)
            if "title" in fields:
                title = mentions.plain(data.get("title", ""))
                result.append(_("changed the title to “%(title)s”") % {"title": title})
            if "due_on" in fields:
                result.append(_due(data.get("due_on")))
            return result
        case Action.VISIBILITY_CHANGED:
            if data.get("visible"):
                return [_("made %(it)s visible to clients") % {"it": it}]
            return [_("hid %(it)s from clients") % {"it": it}]
        case Action.TRASHED:
            return [_("trashed %(it)s") % {"it": it}]
        case Action.RESTORED:
            return [_("restored %(it)s") % {"it": it}]
    return []


@dataclasses.dataclass
class Line:
    """One or more events of one person, oldest first"""

    events: list

    @property
    def is_line(self):
        return True

    @property
    def actor(self):
        return self.events[0].actor

    @property
    def created_at(self):
        return self.events[-1].created_at

    @property
    def pk(self):
        """Stable while later changes merge in (the live page tells the
        line by it)"""
        return self.events[0].pk

    @property
    def kind(self):
        return _kind(self.events[0])

    @property
    def text(self):
        said = []
        for event in self.events:
            said.extend(phrases(event, _("it") if said else _("this")))
        return get_text_list(said, _("and"))


def relevant(events, user):
    """The events the timeline tells: not what the person may not see
    (visibility switches: staff), not edits of anything but the title and
    the due date"""
    return [
        event
        for event in events
        if not (event.action == Action.VISIBILITY_CHANGED and user.is_client)
        and not (event.action == Action.EDITED and not _edit_fields(event))
    ]


def merge(entries):
    """Comments and lines, oldest first: a line takes in the next change if
    it's the same person's, right after (no comment in between) and within
    ``MERGE_WINDOW`` of the line's last"""
    result = []
    for entry in entries:
        if isinstance(entry, Line) and result and isinstance(result[-1], Line):
            last = result[-1]
            if (
                last.events[-1].actor_id == entry.events[0].actor_id
                and entry.events[0].created_at - last.created_at <= MERGE_WINDOW
            ):
                last.events.extend(entry.events)
                continue
        result.append(entry)
    return result


def _order(event):
    return (event.created_at, event.pk)


def list_switches(item, user, events):
    """To-dos have no visibility switch, their list has: for staff, the
    list's switching since the to-do is in it (since it was added, or
    moved in) are lines of the to-do's too, "made this visible to clients"
    (decided 2026-11-21, specs/timeline.md). ``events``: the to-do's own."""
    if item.parent_id is None:
        return []
    arrived = max(
        [item.created_at]
        + [
            e.created_at
            for e in events
            if e.action == Action.MOVED and e.data.get("to_id") == item.parent_id
        ]
    )
    return list(
        Event.objects
        .visible_to(user)
        .filter(
            item=item.parent_id,
            action=Action.VISIBILITY_CHANGED,
            created_at__gte=arrived,
        )
        .select_related("actor", "project", "item")
    )


def entries_for(item, user, comments):
    """Comments and event lines of the to-do, oldest first: two queries and
    what ``feed.attach()`` needs (the people's names, the lists' titles)"""
    events = list(
        Event.objects
        .visible_to(user)
        .filter(item=item, action__in=ACTIONS)
        .select_related("actor", "project", "item")
        .order_by("created_at", "pk")
    )
    if not user.is_client:
        events = sorted(events + list_switches(item, user, events), key=_order)
    events = relevant(events, user)
    feed.attach(events, user)
    entries = [Line([event]) for event in events]
    entries.extend(comments)
    # Comments before events at the same time
    entries.sort(key=lambda e: (e.created_at, isinstance(e, Line), e.pk))
    return merge(entries)
