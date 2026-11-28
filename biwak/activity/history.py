"""The history of an item from the audit log (specs/feed.md)

The audit log (``biwak/audit/``) records every change of the item's rows
with who made it. This condenses it into readable changes: which field
changed when and by whom, with the old and the new value, texts as a diff.
Events say what happened, this says the details. Like Governance's history
(``governance/history/audit.py``) it reads the rows of the tables by primary
key and knows which columns matter; positions and timestamps don't.
"""

import dataclasses
import datetime as dt
import difflib

from django.db.models import Choices, Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.translation import gettext

from biwak.accounts.models import User
from biwak.audit.models import LoggedAction
from biwak.items.models import Group, Item, Kind, Status, TodoList
from biwak.projects.models import Project


# table → column → (label, kind of value); the other columns are ignored
TEXT, VALUE, BOOL, DATE, TIME, ITEM, GROUP, COMPLETED, PAUSED, SCHEDULE = (
    "text",
    "value",
    "bool",
    "date",
    "time",
    "item",
    "group",
    "completed",
    "paused",
    "schedule",
)
# Moved to another project (specs/lists-across-projects.md)
PROJECT = "project"
# Folders hold docs, files and folders; lists hold to-dos
IN_FOLDERS = {Kind.DOC, Kind.FILE, Kind.FOLDER}


def _fields(item):
    return {
        "items_item": {
            "title": (gettext("Title"), VALUE),
            "project_id": (gettext("Project"), PROJECT),
            "parent_id": (
                gettext("Folder") if item.kind in IN_FOLDERS else gettext("List"),
                ITEM,
            ),
            "is_client_visible": (gettext("Visible to clients"), BOOL),
            "status": (gettext("Status"), Status),
        },
        "items_todo": {
            "notes": (gettext("Notes"), TEXT),
            "group_id": (gettext("Group"), GROUP),
            "starts_on": (gettext("Starts on"), DATE),
            "due_on": (gettext("Due on"), DATE),
            "completed_at": (gettext("Completed"), COMPLETED),
            "obsolete": (gettext("Obsolete"), BOOL),
        },
        "items_todolist": {
            "description": (gettext("Description"), TEXT),
            "view": (gettext("View"), TodoList.View),
        },
        "items_message": {"content": (gettext("Content"), TEXT)},
        "items_upload": {"description": (gettext("Description"), TEXT)},
        "items_doc": {"content": (gettext("Content"), TEXT)},
        "checkins_answer": {"content": (gettext("Content"), TEXT)},
        "checkins_question": {
            "rule": (gettext("Schedule"), SCHEDULE),
            "starts_on": (gettext("First asked on"), DATE),
            "time_of_day": (gettext("Time of day"), TIME),
            "paused_at": (gettext("Paused"), PAUSED),
        },
    }


# The people of an item: table → (kind, column of the item, label added,
# label removed)
def _people_tables():
    return {
        "items_todo_assignees": (
            Kind.TODO,
            "todo_id",
            gettext("Assigned"),
            gettext("Unassigned"),
        ),
        "checkins_question_people": (
            Kind.QUESTION,
            "question_id",
            gettext("Asked"),
            gettext("No longer asked"),
        ),
    }


@dataclasses.dataclass
class Change:
    when: dt.datetime
    # The person, or the audit's name (a job, 🧚 for nobody) if it's not a person
    user: User | None
    user_name: str
    field: str
    label: str
    kind: str  # created, changed, assigned, unassigned
    old: str | None = None
    new: str | None = None
    # ``[("+", line), ("-", line), (" ", line)]`` for texts
    diff: list | None = None


def diff_lines(old, new, context=1):
    """The lines which changed with some context, separated by ("…", "")"""
    a, b = (old or "").splitlines(), (new or "").splitlines()
    lines = []
    for group in difflib.SequenceMatcher(None, a, b).get_grouped_opcodes(context):
        if lines:
            lines.append(("…", ""))
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                lines += [(" ", line) for line in a[i1:i2]]
            else:
                lines += [("-", line) for line in a[i1:i2]]
                lines += [("+", line) for line in b[j1:j2]]
    return lines


def _rows(item):
    """The audit rows of the item's tables, oldest first. The detail rows
    share the item's primary key (as ``item_id``)."""
    pk = str(item.pk)
    wanted = Q(table_name="items_item", row_data__id=pk) | Q(
        table_name=type(item.detail)._meta.db_table, row_data__item_id=pk
    )
    for table, (kind, column, *_labels) in _people_tables().items():
        if item.kind == kind:
            wanted |= Q(table_name=table, **{f"row_data__{column}": pk})
    return list(
        LoggedAction.objects.filter(wanted, row_data__isnull=False).order_by("event_id")
    )


def _ids(rows, column):
    return {
        int(value)
        for row in rows
        for source in [row.row_data or {}, row.changed_fields or {}]
        for key, value in source.items()
        if key == column and value
    }


def _show(rows, viewer, item):
    """The function turning a raw value of a kind into text"""
    from biwak import schedules

    items = {
        i.pk: i.title
        for i in Item.objects.visible_to(viewer).filter(pk__in=_ids(rows, "parent_id"))
    }
    groups = dict(
        Group.objects.filter(pk__in=_ids(rows, "group_id")).values_list("pk", "title")
    )
    projects = dict(
        Project.objects
        .accessible_to(viewer)
        .filter(pk__in=_ids(rows, "project_id"))
        .values_list("pk", "name")
    )

    def show(kind, raw):
        if raw in {None, ""}:
            return None
        if isinstance(kind, type) and issubclass(kind, Choices):
            # The label in the reader's language, not the stored value
            return str(dict(kind.choices).get(raw, raw))
        if kind == BOOL:
            return gettext("yes") if raw in {"t", "true", True} else gettext("no")
        if kind == ITEM:
            return items.get(
                int(raw),
                gettext("another folder")
                if item.kind in IN_FOLDERS
                else gettext("another list"),
            )
        if kind == PROJECT:
            return projects.get(int(raw), gettext("another project"))
        if kind == GROUP:
            return groups.get(int(raw), gettext("a deleted group"))
        if kind == TIME:
            return raw[:5]
        if kind == SCHEDULE:
            return schedules.describe(raw)
        if kind in {COMPLETED, PAUSED}:
            when = parse_datetime(raw)
            return timezone.localtime(when).strftime("%Y-%m-%d %H:%M") if when else raw
        return raw

    return show


def _assignment(row, who, people):
    """Assigned or unassigned, asked or no longer asked"""
    assigned = row.action == "I"
    _kind, _column, added, removed = _people_tables()[row.table_name]
    name = people.get(int(row.row_data["user_id"]))
    return Change(
        **who,
        field="assignees" if row.table_name == "items_todo_assignees" else "people",
        label=added if assigned else removed,
        kind="assigned" if assigned else "unassigned",
        new=str(name) if name else gettext("somebody"),
    )


def _updates(row, who, show, fields):
    for column, (label, kind) in fields.get(row.table_name, {}).items():
        if column not in (row.changed_fields or {}):
            continue
        old, new = row.row_data.get(column), row.changed_fields[column]
        change = Change(**who, field=column, label=label, kind="changed")
        if kind == COMPLETED:
            change.label = gettext("Completed") if new else gettext("Reopened")
        if kind == PAUSED:
            change.label = gettext("Paused") if new else gettext("Resumed")
        if kind == TEXT:
            change.old, change.new = old or None, new or None
            change.diff = diff_lines(old, new)
        else:
            change.old, change.new = show(kind, old), show(kind, new)
        yield change


def history(item, viewer):
    """The changes of the item, newest first. ``viewer`` only sees the
    titles of items they can see."""
    rows = _rows(item)
    show = _show(rows, viewer, item)
    fields = _fields(item)
    people = {
        u.pk: u
        for u in User.objects.filter(
            pk__in={r.user_id for r in rows if r.user_id} | _ids(rows, "user_id")
        )
    }
    # Assigned and asked: named only if the viewer may know them (clients
    # and externals: members, specs/access.md), else "somebody"
    known = {u.pk: u for u in item.project.people_known_to(viewer, people.values())}
    changes = []
    for row in rows:
        user = people.get(row.user_id)
        who = {
            "when": row.created_at,
            "user": user,
            "user_name": "" if user else (row.user_name or "🧚"),
        }
        if row.table_name in _people_tables():
            if row.action in {"I", "D"}:
                changes.append(_assignment(row, who, known))
        elif row.action == "I" and row.table_name == "items_item":
            changes.append(
                Change(
                    **who,
                    field="created",
                    label=gettext("Created"),
                    kind="created",
                    new=row.row_data.get("title"),
                )
            )
        elif row.action == "U":
            changes += _updates(row, who, show, fields)
    return list(reversed(changes))
