"""The timeline of to-dos, messages, docs and files (specs/timeline.md):
the comments and what happened to the item between them, oldest first,
one list.

The events come from ``Event.objects.visible_to()``, so a client sees only
those of the time the item was visible to them; the lists' and folders'
names are resolved like the feed's (``feed.add_target_lists()``).
Consecutive changes of the same person within ten minutes become one line.
"""

import dataclasses
import datetime as dt

from django.urls import reverse
from django.utils.formats import date_format
from django.utils.html import conditional_escape, escape, format_html
from django.utils.safestring import mark_safe
from django.utils.text import get_text_list
from django.utils.translation import gettext as _

from biwak.activity import feed, mentions
from biwak.activity.models import Action, Event
from biwak.formats import format_range
from biwak.items.models import Item, Kind


# Consecutive changes of one person within this time of each other are one
# line (the editing session of ``record()``, the undo of completing)
MERGE_WINDOW = dt.timedelta(minutes=10)

# What the timeline tells; edits of to-dos only when they changed the title
# or the due date, of the other kinds when they changed the title or the
# text (or replaced the file); the switch, which to-dos don't have
ACTIONS = [
    Action.COMPLETED,
    Action.MARKED_OBSOLETE,
    Action.REOPENED,
    Action.MOVED,
    Action.ASSIGNED,
    Action.UNASSIGNED,
    Action.EDITED,
    Action.TRASHED,
    Action.RESTORED,
    Action.VISIBILITY_CHANGED,
]
# What an edit of a to-do tells
EDIT_FIELDS = ("title", "due_on", "starts_on")
DATE_FIELDS = {"due_on", "starts_on"}
# What an edit of a message, a doc or a file tells: "edited this" for the
# title and the text (comments may refer to the old one, decided
# 2026-11-23), "uploaded a new version" for a file replaced
TEXT_FIELDS = ("title", "content", "description", "file")


def _is_todo(event):
    return event.item.kind == Kind.TODO


def _edit_fields(event):
    shown = EDIT_FIELDS if _is_todo(event) else TEXT_FIELDS
    return [f for f in event.data.get("fields", []) if f in shown]


def _kind(event):
    """What the line's icon shows (``_timeline_line.html`` has the icons)"""
    if event.action == Action.EDITED:
        fields = _edit_fields(event)
        if not _is_todo(event):
            return "edited"
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
    Action.MARKED_OBSOLETE: ("done", True),
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
    done = {Action.COMPLETED, Action.MARKED_OBSOLETE, Action.REOPENED}
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
            # Back where it started (completed or marked obsolete and
            # reopened): nothing; else the last one
            if (run[0].action == Action.REOPENED) != (
                run[-1].action == Action.REOPENED
            ):
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
    if "folder_id" in data:
        if data["folder_id"] is None:
            return _("moved %(it)s out of its folder") % {"it": it}
        # The folder's name only if the viewer may see it
        to = mentions.plain(event.target_folder) or _("another folder")
        return _("moved %(it)s to %(to)s") % {"it": it, "to": to}
    if "to_project" in data and "to" not in data:
        # From another project (specs/lists-across-projects.md), named only
        # if the viewer may open it (feed.add_projects())
        if event.source_project:
            return _("moved %(it)s from %(project)s") % {
                "it": it,
                "project": event.source_project,
            }
        return _("moved %(it)s from another project") % {"it": it}
    if not _is_todo(event):
        # Older moves of docs and files didn't say where to
        return _("moved %(it)s") % {"it": it}
    if "group" in data:
        if data["group"]:
            to = mentions.plain(data["group"])
            return _("moved %(it)s to %(to)s") % {"it": it, "to": to}
        return _("moved %(it)s out of its group") % {"it": it}
    # Another list's name only if the viewer may see it
    to = mentions.plain(event.target_list) or _("another list")
    return _("moved %(it)s to %(to)s") % {"it": it, "to": to}


def _moved(event):
    """What a move did: into another list, group or folder (each with where
    from, for moving back), or for docs and files into this project or
    somewhere older events don't say"""
    data = event.data
    if "folder_id" in data:
        key, to, was = "folder", data["folder_id"], "folder_was"
    elif "group" in data:
        key, to, was = "group", data.get("group_id"), "group_was"
    elif not _is_todo(event):
        # Into another project, or an older move: no way back
        key, to, was = "place", True, None
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


def effects(event):
    """What the event did, as a list of ``Effect``"""
    data = event.data
    action = event.action
    if action in TOGGLES:
        group, value = TOGGLES[action]
        word = {
            Action.COMPLETED: _("completed %(it)s"),
            Action.MARKED_OBSOLETE: _("marked %(it)s as obsolete"),
            Action.REOPENED: _("reopened %(it)s"),
            Action.TRASHED: _("trashed %(it)s"),
            Action.RESTORED: _("restored %(it)s"),
        }[action]
        return [Effect(str(action), group, value, lambda it: word % {"it": it})]
    match action:
        case Action.MOVED:
            return _moved(event)
        case Action.ASSIGNED | Action.UNASSIGNED:
            sign = action == Action.ASSIGNED
            ids = event.data.get("assignees", [])
            names = getattr(event, "assignee_links", {})
            # Only those the viewer may know; "someone" if nobody
            known = [pk for pk in ids if pk in names]
            if ids and not known:
                return [Effect(str(action), ("person", None), sign, _("someone"))]
            return [
                Effect(str(action), ("person", pk), sign, names[pk]) for pk in known
            ]
        case Action.VISIBILITY_CHANGED:
            shown = bool(data.get("visible"))
            word = _("showed %(it)s to clients") if shown else _("made %(it)s internal")
            return [
                Effect(
                    "shown" if shown else "hidden",
                    "visibility",
                    value=shown,
                    make=lambda it: word % {"it": it},
                )
            ]
        case Action.EDITED if not _is_todo(event):
            return _text_edits(event)
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


def _text_edits(event):
    """What an edit of a message, a doc or a file did: "edited this" (for
    staff a link to the history, ``event.history_url``), "uploaded a new
    version" """
    fields = _edit_fields(event)
    result = []
    if set(fields) - {"file"}:
        url = getattr(event, "history_url", None)

        def edited(it):
            text = _("edited %(it)s") % {"it": it}
            return format_html('<a href="{}">{}</a>', url, text) if url else text

        result.append(Effect("edited", "edited", value=True, make=edited))
    if "file" in fields:
        result.append(
            Effect(
                "file", "file", value=True, make=lambda it: _("uploaded a new version")
            )
        )
    return result


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
                if effect.key in ("title", "due", "list", "group", "folder"):
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
    """The phrases of ``combine(events)``, escaped HTML: people assigned
    (or removed) together, their names linked (``feed.attach()``), the
    first phrase about "this", the later ones "it" """
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
                lambda it, verb=verb, names=names: mark_safe(
                    escape(verb) % {"people": _text_list(names)}
                )
            )
        else:
            # The history's link is HTML already, the rest is text
            said.append(lambda it, make=effect.make: conditional_escape(make(it)))
    return [make(_("it") if n else _("this")) for n, make in enumerate(said)]


def _text_list(parts):
    """``get_text_list()`` of escaped parts, escaped"""
    return mark_safe(
        get_text_list([conditional_escape(p) for p in parts], escape(_("and")))
    )


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
        return _text_list(phrases(self.events))

    @property
    def completion(self):
        """The completing people react to (specs/reactions.md): the line's
        last ``completed`` event if the line says it completed the to-do;
        None when it doesn't (nothing completed, or reopened again)"""
        kept = combine(self.events)
        if not any(e.key == "done" and e.value for e in kept):
            return None
        last = next(
            e
            for e in reversed(self.events)
            if e.action in {Action.COMPLETED, Action.MARKED_OBSOLETE}
        )
        # Marked obsolete isn't getting it done: nothing to react to
        return last if last.action == Action.COMPLETED else None


def relevant(events, user, comments=()):
    """The events the timeline tells: not edits of anything but the title
    and the due date of to-dos; edits of the title and the text of other
    items only after their first comment (decided 2026-11-23: before it,
    nobody can have referred to the old text; the writing of a new doc
    isn't told either)"""
    first = min((c.created_at for c in comments), default=None)
    return [
        event
        for event in events
        if not (event.action == Action.EDITED and not _edit_fields(event))
        and not (
            event.action == Action.EDITED
            and not _is_todo(event)
            and (first is None or event.created_at < first)
        )
    ]


def add_target_folders(events, user):
    """``event.target_folder``: the name of the folder a doc, file or folder
    moved to, or "" if the viewer may not see it; checked now, in one query
    for all events (like ``feed.add_target_lists()``)"""
    moves = [e for e in events if e.action == Action.MOVED and "folder_id" in e.data]
    ids = {e.data["folder_id"] for e in moves} - {None}
    folders = (
        dict(
            Item.objects
            .visible_to(user)
            .filter(pk__in=ids, kind=Kind.FOLDER)
            .values_list("pk", "title")
        )
        if ids
        else {}
    )
    for event in moves:
        event.target_folder = folders.get(event.data["folder_id"], "")


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
    """Comments and event lines of the item, oldest first: two queries and
    what ``feed.attach()`` needs (the people's names, the lists' titles),
    one more for folders when something moved between them"""
    comments = list(comments)
    events = list(
        Event.objects
        .visible_to(user)
        .filter(item=item, action__in=ACTIONS)
        .select_related("actor", "project", "item")
        .order_by("created_at", "pk")
    )
    events = relevant(events, user, comments)
    feed.attach(events, user)
    add_target_folders(events, user)
    if not user.is_client:
        # "edited this" links to the history, staff only (specs/feed.md)
        url = reverse("item_history", args=[item.pk])
        for event in events:
            event.history_url = url
    entries = [Line([event]) for event in events]
    entries.extend(comments)
    # Comments before events at the same time
    entries.sort(key=lambda e: (e.created_at, isinstance(e, Line), e.pk))
    # Lines whose changes cancelled out are gone
    return [e for e in merge(entries) if not isinstance(e, Line) or e.text]
