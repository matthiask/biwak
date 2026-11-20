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

from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.translation import gettext

from biwak.accounts.models import User
from biwak.audit.models import LoggedAction
from biwak.items.models import Group, Item, Kind


# table → column → (label, kind of value); the other columns are ignored
TEXT, VALUE, BOOL, DATE, ITEM, GROUP, COMPLETED = (
    "text",
    "value",
    "bool",
    "date",
    "item",
    "group",
    "completed",
)


def _fields():
    return {
        "items_item": {
            "title": (gettext("Title"), VALUE),
            "parent_id": (gettext("List"), ITEM),
            "is_client_visible": (gettext("Visible to clients"), BOOL),
            "status": (gettext("Status"), VALUE),
        },
        "items_todo": {
            "notes": (gettext("Notes"), TEXT),
            "group_id": (gettext("Group"), GROUP),
            "starts_on": (gettext("Starts on"), DATE),
            "due_on": (gettext("Due on"), DATE),
            "completed_at": (gettext("Completed"), COMPLETED),
        },
        "items_todolist": {
            "description": (gettext("Description"), TEXT),
            "view": (gettext("View"), VALUE),
        },
        "items_message": {"content": (gettext("Content"), TEXT)},
        "items_doc": {"content": (gettext("Content"), TEXT)},
    }


@dataclasses.dataclass
class Change:
    when: dt.datetime
    # The person, or the audit's name (a job, "unknown") if it's not a person
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
    if item.kind == Kind.TODO:
        wanted |= Q(table_name="items_todo_assignees", row_data__todo_id=pk)
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


def _show(rows, viewer):
    """The function turning a raw value of a kind into text"""
    items = {
        i.pk: i.title
        for i in Item.objects.visible_to(viewer).filter(pk__in=_ids(rows, "parent_id"))
    }
    groups = dict(
        Group.objects.filter(pk__in=_ids(rows, "group_id")).values_list("pk", "title")
    )

    def show(kind, raw):
        if raw in {None, ""}:
            return None
        if kind == BOOL:
            return gettext("yes") if raw in {"t", "true", True} else gettext("no")
        if kind == ITEM:
            return items.get(int(raw), gettext("another list"))
        if kind == GROUP:
            return groups.get(int(raw), gettext("a deleted group"))
        if kind == COMPLETED:
            when = parse_datetime(raw)
            return timezone.localtime(when).strftime("%Y-%m-%d %H:%M") if when else raw
        return raw

    return show


def _assignment(row, who, people):
    assigned = row.action == "I"
    name = people.get(int(row.row_data["user_id"]))
    return Change(
        **who,
        field="assignees",
        label=gettext("Assigned") if assigned else gettext("Unassigned"),
        kind="assigned" if assigned else "unassigned",
        new=str(name) if name else gettext("somebody"),
    )


def _updates(row, who, show):
    for column, (label, kind) in _fields().get(row.table_name, {}).items():
        if column not in (row.changed_fields or {}):
            continue
        old, new = row.row_data.get(column), row.changed_fields[column]
        change = Change(**who, field=column, label=label, kind="changed")
        if kind == COMPLETED:
            change.label = gettext("Completed") if new else gettext("Reopened")
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
    show = _show(rows, viewer)
    people = {
        u.pk: u
        for u in User.objects.filter(
            pk__in={r.user_id for r in rows if r.user_id} | _ids(rows, "user_id")
        )
    }
    changes = []
    for row in rows:
        user = people.get(row.user_id)
        who = {
            "when": row.created_at,
            "user": user,
            "user_name": "" if user else (row.user_name or gettext("unknown")),
        }
        if row.table_name == "items_todo_assignees":
            if row.action in {"I", "D"}:
                changes.append(_assignment(row, who, people))
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
            changes += _updates(row, who, show)
    return list(reversed(changes))
