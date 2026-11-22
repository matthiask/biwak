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
from biwak.formats import format_range


# Consecutive changes of one person within this time of each other are one
# line (the editing session of ``record()``, the undo of completing)
MERGE_WINDOW = dt.timedelta(minutes=10)

# What the timeline tells; edits only when they changed the title or the
# due date
ACTIONS = [
    Action.COMPLETED,
    Action.REOPENED,
    Action.MOVED,
    Action.ASSIGNED,
    Action.UNASSIGNED,
    Action.EDITED,
    Action.TRASHED,
    Action.RESTORED,
]
# What an edit tells
EDIT_FIELDS = ("title", "due_on", "starts_on")
DATE_FIELDS = {"due_on", "starts_on"}


def _edit_fields(event):
    return [f for f in event.data.get("fields", []) if f in EDIT_FIELDS]


def _kind(event):
    """What the line's icon shows (``_timeline_line.html`` has the icons)"""
    if event.action == Action.EDITED:
        fields = _edit_fields(event)
        return "due" if fields and DATE_FIELDS.issuperset(fields) else "title"
    return str(event.action)


def _due(value):
    """``value``: the start and the due date (ISO or ``None``); "changed
    the dates" once a start date is or was involved (specs/start-dates.md)"""
    starts, due, with_start = value
    if not due:
        return _("removed the due date")
    if with_start:
        return _("changed the dates to %(dates)s") % {
            "dates": format_range(
                starts and dt.date.fromisoformat(starts),
                dt.date.fromisoformat(due),
                "SHORT_DATE_FORMAT",
            )
        }
    return _("set the due date to %(date)s") % {
        "date": date_format(dt.date.fromisoformat(due), "SHORT_DATE_FORMAT")
    }


# Pairs which undo each other: group -> value of each action
TOGGLES = {
    Action.COMPLETED: ("done", True),
    Action.REOPENED: ("done", False),
    Action.TRASHED: ("trash", True),
    Action.RESTORED: ("trash", False),
}


UNKNOWN = object()


def _always(older, newer):
    return True


def _in_order(events, others, actions):
    """``events`` and ``others`` of ``actions`` on items, oldest first, each
    with whether it's one of ``others``"""
    return sorted(
        [
            *((e, False) for e in events if e.action in actions and e.item_id),
            *((e, True) for e in others if e.action in actions and e.item_id),
        ],
        key=lambda pair: (pair[0].created_at, pair[0].pk),
    )


def cancelled(events, *, together=_always, others=()):
    """The IDs of the completing and reopening events (of ``events``, in
    any order) a later one undoes: each person's consecutive completing
    and reopening of an item (other events don't break it up, another
    person's completing or reopening does; ``together(older, newer)``
    for neighbours) is its net change, the last one or nothing when the
    item is back where it started (decided 2026-11-21, replacing deleting
    the earlier event when recording). ``others`` are events left out of
    ``events`` (a person's feed: the others' events) which still break
    runs up. For the feed, the lantern and the mails; the timeline's
    lines do the same through ``combine()``."""
    done = {Action.COMPLETED, Action.REOPENED}
    runs = {}  # item ID -> the runs of its completing and reopening
    for event, other in _in_order(events, others, done):
        item_runs = runs.setdefault(event.item_id, [])
        last = item_runs[-1][-1] if item_runs and item_runs[-1] else None
        if other:
            # Another person's event left out ends the run before it
            if last is not None and last.actor_id != event.actor_id:
                item_runs.append([])
            continue
        if (
            last is not None
            and last.actor_id == event.actor_id
            and together(last, event)
        ):
            item_runs[-1].append(event)
        else:
            item_runs.append([event])
    result = set()
    for item_runs in runs.values():
        for run in filter(None, item_runs):
            if run[0].action != run[-1].action:
                result.update(e.pk for e in run)
            else:
                result.update(e.pk for e in run[:-1])
    return result


def _move_kind(event):
    """A move's kind ("group" or "list"), where to and where from, and the
    column it ended up in and came from (a list move's ``group_id`` and
    ``group_was``, ``UNKNOWN`` for older ones); None for moves recorded
    before they said where from"""
    data = event.data
    if "group" in data:
        to, was = data.get("group_id"), data.get("group_was", UNKNOWN)
        kind = "group"
        column, column_was = to, was
    else:
        to, was = data.get("to_id"), data.get("to_was", UNKNOWN)
        kind = "list"
        column = data.get("group_id", UNKNOWN)
        column_was = data.get("group_was", UNKNOWN)
    if was is UNKNOWN:
        return None
    return kind, to, was, column, column_was


def _same(a, b):
    """Columns are the same, or one isn't known (older list moves)"""
    return a is UNKNOWN or b is UNKNOWN or a == b


def _net_moves(run):
    """The moves of a run (``[(event, kind, to, was, column, column_was)]``)
    which don't show: all of them when the to-do is back in the list and
    the column it started in; otherwise all but the last move into
    another list and the last column move after it (a list move ends the
    column moves before it: they're about a column it left), and those
    too if it's back in the column the list move put it in"""
    hidden = set()
    lists = [n for n, move in enumerate(run) if move[1] == "list"]
    # Where it started and ended up (the list: only if it moved to another)
    start_list = run[lists[0]][3] if lists else None
    end_list = run[lists[-1]][2] if lists else None
    start_column, end_column = run[0][5], run[-1][4]
    if end_list == start_list and _same(end_column, start_column):
        return {move[0].pk for move in run}
    if lists:
        last = lists[-1]
        hidden.update(move[0].pk for move in run[:last])
        columns = run[last + 1 :]
        if columns and columns[-1][4] == run[last][4]:
            hidden.update(move[0].pk for move in columns)
        else:
            hidden.update(move[0].pk for move in columns[:-1])
    else:
        hidden.update(move[0].pk for move in run[:-1])
    return hidden


def moved_back(events, *, together=_always, others=()):
    """The IDs of the moves (of ``events``, in any order) a later one makes
    pointless: each person's consecutive moves of an item into other
    columns or lists (other events don't break them up, another person's
    move does, also one of ``others`` like in ``cancelled()``) are their
    net change (``_net_moves()``), nothing when the to-do is back where it
    was (decision B, decided 2026-11-22). Like ``cancelled()``, for the
    feed; the timeline does it in ``combine()``."""
    runs = {}  # item ID -> runs of [(event, kind, to, was, column, column_was)]
    for event, other in _in_order(events, others, {Action.MOVED}):
        move = _move_kind(event)
        if move is None:
            continue
        item_runs = runs.setdefault(event.item_id, [])
        last = item_runs[-1][-1][0] if item_runs and item_runs[-1] else None
        if other:
            if last is not None and last.actor_id != event.actor_id:
                item_runs.append([])
            continue
        if (
            last is not None
            and last.actor_id == event.actor_id
            and together(last, event)
        ):
            item_runs[-1].append((event, *move))
        else:
            item_runs.append([(event, *move)])
    result = set()
    for item_runs in runs.values():
        for run in filter(None, item_runs):
            result |= _net_moves(run)
    return result


class Effect:
    """One thing an event did: ``key`` says what it was about (a later
    effect on the same key replaces it), ``value`` what it set,
    ``make(it)`` the phrase"""

    def __init__(self, kind, key, value, make, was=UNKNOWN, column=UNKNOWN):
        self.kind, self.key, self.value, self.make = kind, key, value, make
        # What it was before (title, due date), if the event says
        self.was = was
        # A list move: the column it ended up in and came from, if it says
        self.column, self.column_was = column, UNKNOWN


def _move(event, it):
    data = event.data
    if "group" in data:
        if data["group"]:
            to = mentions.plain(data["group"])
            return _("moved %(it)s to %(to)s") % {"it": it, "to": to}
        return _("moved %(it)s out of its group") % {"it": it}
    # Another list's name only if the viewer may see it
    to = mentions.plain(event.target_list) or _("another list")
    return _("moved %(it)s to %(to)s") % {"it": it, "to": to}


def effects(event):
    """What the event did, as a list of ``Effect``"""
    data = event.data
    action = event.action
    if action in TOGGLES:
        group, value = TOGGLES[action]
        word = {
            Action.COMPLETED: _("completed %(it)s"),
            Action.REOPENED: _("reopened %(it)s"),
            Action.TRASHED: _("trashed %(it)s"),
            Action.RESTORED: _("restored %(it)s"),
        }[action]
        return [Effect(str(action), group, value, lambda it: word % {"it": it})]
    match action:
        case Action.MOVED:
            if "group" in data:
                key, to, was = "group", data.get("group_id"), "group_was"
            else:
                key, to, was = "list", data.get("to_id"), "to_was"
            effect = Effect(
                "moved", key, to, lambda it: _move(event, it), data.get(was, UNKNOWN)
            )
            if key == "list":
                effect.column = data.get("group_id", UNKNOWN)
                effect.column_was = data.get("group_was", UNKNOWN)
            # Dragged into a column and back (one event, record())
            return [] if effect.was == to else [effect]
        case Action.ASSIGNED | Action.UNASSIGNED:
            sign = action == Action.ASSIGNED
            ids = event.data.get("assignees", [])
            names = getattr(event, "assignee_by_id", {})
            # Only those the viewer may know; "someone" if nobody
            known = [pk for pk in ids if pk in names]
            if ids and not known:
                return [Effect(str(action), ("person", None), sign, _("someone"))]
            return [
                Effect(str(action), ("person", pk), sign, names[pk]) for pk in known
            ]
        case Action.EDITED:
            result = []
            fields = _edit_fields(event)
            if "title" in fields:
                title = mentions.title(data.get("title", ""))
                text = _("changed the title to “%(title)s”") % {"title": title}
                was = data.get("title_was", UNKNOWN)
                if was is not UNKNOWN:
                    was = mentions.plain(was)
                if was != title:
                    result.append(Effect("title", "title", title, lambda it: text, was))
            if DATE_FIELDS & set(fields):
                value = (data.get("starts_on"), data.get("due_on"))
                was = (
                    (data.get("starts_was"), data["due_was"])
                    if "due_was" in data
                    else UNKNOWN
                )
                if was != value:
                    with_start = bool(data.get("starts_on") or data.get("starts_was"))
                    result.append(
                        Effect(
                            "due",
                            "due",
                            value,
                            lambda it, v=(*value, with_start): _due(v),
                            was,
                        )
                    )
            return result
    return []


def combine(events):
    """The effects of several events one after the other, without what
    cancelled out (assigning then removing the
    same person, completing then reopening, setting the due date and
    removing it, moving it and moving it back) and with only the last of
    what was set several times (the title, the due date, the place it was
    moved to)"""
    result = []
    for event in events:
        for effect in effects(event):
            if effect.key == "list":
                # A list move ends the column moves before it (_net_moves())
                column = next((e for e in result if e.key == "group"), None)
                if column is not None:
                    result.remove(column)
                    effect.column_was = column.was
            old = next((e for e in result if e.key == effect.key), None)
            if old is not None:
                result.remove(old)
                if effect.key in ("title", "due", "list", "group"):
                    # Back to what it was before the first change?
                    effect.was = old.was
                    if effect.key == "list":
                        effect.column_was = old.column_was
                    if (
                        effect.was is not UNKNOWN
                        and effect.was == effect.value
                        and _same(effect.column, effect.column_was)
                    ):
                        continue
                elif old.value != effect.value:
                    continue
            result.append(effect)
    return result


def phrases(events):
    """The phrases of ``combine(events)``: people assigned (or removed)
    together, the first phrase about "this", the later ones "it" """
    said = []
    effects_ = combine(events)
    people = {True: [], False: []}
    for effect in effects_:
        if isinstance(effect.key, tuple):
            people[effect.value].append(effect.make)
    placed = set()
    for effect in effects_:
        if isinstance(effect.key, tuple):
            if effect.value in placed:
                continue
            placed.add(effect.value)
            verb = _("assigned %(people)s") if effect.value else _("removed %(people)s")
            names = list(dict.fromkeys(people[effect.value]))
            said.append(
                lambda it, verb=verb, names=names: (
                    verb % {"people": get_text_list(names, _("and"))}
                )
            )
        else:
            said.append(effect.make)
    return [make(_("it") if n else _("this")) for n, make in enumerate(said)]


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
        kept = combine(self.events)
        return kept[0].kind if kept else _kind(self.events[0])

    @property
    def text(self):
        return get_text_list(phrases(self.events), _("and"))


def relevant(events, user):
    """The events the timeline tells: not edits of anything but the title
    and the due date"""
    return [
        event
        for event in events
        if not (event.action == Action.EDITED and not _edit_fields(event))
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
    events = relevant(events, user)
    feed.attach(events, user)
    entries = [Line([event]) for event in events]
    entries.extend(comments)
    # Comments before events at the same time
    entries.sort(key=lambda e: (e.created_at, isinstance(e, Line), e.pk))
    # Lines whose changes cancelled out are gone
    return [e for e in merge(entries) if not isinstance(e, Line) or e.text]
