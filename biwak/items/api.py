"""Lists, groups, to-dos, comments and subscriptions (specs/core.md,
specs/api-cli.md). The same operations as the web interface, so writes
create the same events and subscriptions."""

import datetime as dt
from contextlib import contextmanager
from typing import Annotated, Literal

from django.db.models import F, Prefetch
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _
from ninja import Field, Router, Schema, Status
from ninja.errors import HttpError
from pydantic import StringConstraints

from biwak import schedules
from biwak.accounts.models import Color
from biwak.activity.mentions import resolve as resolve_mentions
from biwak.activity.models import Action, Event
from biwak.activity.operations import (
    NOTE_LENGTH,
    StillAssigned,
    is_subscribed,
    share,
    subscribable_people,
    subscribe,
    unsubscribe,
)
from biwak.api_conventions import (
    ItemOut,
    PersonOut,
    Title,
    html,
    item_out,
    page_of,
    paginated,
    person_out,
)
from biwak.items import due, operations as ops, stale
from biwak.items.filters import NO_GROUP, in_group
from biwak.items.models import (
    STALE_AFTER,
    STALE_AFTER_LONG,
    SWITCH_MESSAGE,
    Assignment,
    Group,
    Item,
    Kind,
    Status as ItemStatus,
)
from biwak.items.views import (
    changeable_group,
    changeable_list,
    item_for,
    todos_to_move,
)
from biwak.projects.api import project_for
from biwak.reactions.models import Reaction
from biwak.reactions.operations import prefetch
from biwak.reactions.schemas import ReactionOut, reactions_out


router = Router(tags=["items"])


def bad_request(message):
    raise HttpError(400, message)


# Lists ----------------------------------------------------------------------


class GroupOut(Schema):
    id: int
    title: str
    position: int
    # The color's name, "" for none, and its label (specs/core.md, "Group
    # colors")
    color: Color | Literal[""] = ""
    color_name: str = ""
    stale_after: int = Field(
        STALE_AFTER,
        description="Days without activity before its to-dos are marked"
        " obsolete after a warning: 90, or 365 for a backlog"
        " (specs/stale-todos.md)",
    )


def group_out(group):
    return {
        "id": group.pk,
        "title": group.title,
        "position": group.position,
        "color": group.color,
        "color_name": group.get_color_display() if group.color else "",
        "stale_after": group.stale_after,
    }


def _stale_after(request, days):
    """``stale_after`` as sent: staff only, 90 or 365"""
    if days is None:
        return {}
    if request.user.is_client:
        raise HttpError(403, _("Only staff decide how long to-dos are kept."))
    if days not in (STALE_AFTER, STALE_AFTER_LONG):
        bad_request(
            _("stale_after is %(short)s or %(long)s.")
            % {"short": STALE_AFTER, "long": STALE_AFTER_LONG}
        )
    return {"stale_after": days}


class ListOut(ItemOut):
    description: str
    description_html: str
    view: str
    groups: list[GroupOut]


def list_out(item):
    todolist = item.todolist
    return item_out(item) | {
        "description": todolist.description,
        "description_html": html(todolist.description),
        "view": todolist.view,
        "groups": [group_out(g) for g in todolist.groups.all()],
    }


@router.get("projects/{project_id}/lists/", response=list[ListOut])
def list_list(request, project_id: int, *, archived: bool = False):
    project = project_for(request, project_id)
    lists = (
        Item.objects
        .visible_to(request.user)
        .filter(project=project, kind=Kind.LIST, parent=None)
        .filter(status=ItemStatus.ARCHIVED if archived else ItemStatus.ACTIVE)
        .select_related("creator", "todolist")
        .prefetch_related("todolist__groups")
    )
    return [list_out(item) for item in lists]


class ListIn(Schema):
    title: Title
    description: str = ""
    visible_to_clients: bool = False


@router.post("projects/{project_id}/lists/", response={201: ListOut})
def list_create(request, project_id: int, data: ListIn):
    """Staff only (specs/access.md)"""
    project = project_for(request, project_id)
    if not ops.can_create(request.user, Kind.LIST):
        raise HttpError(403, _("Only staff create lists."))
    item = ops.create_list(
        project=project,
        title=data.title,
        description=data.description,
        creator=request.user,
        visible=data.visible_to_clients,
    )
    return Status(201, list_out(item))


@router.get("lists/{list_id}/", response=ListOut)
def list_detail(request, list_id: int):
    return list_out(item_for(request, list_id, Kind.LIST))


class ListPatch(Schema):
    title: Title | None = None
    description: str | None = None
    view: Literal["list", "board"] | None = None
    archived: bool | None = None


@router.patch("lists/{list_id}/", response=ListOut)
def list_update(request, list_id: int, data: ListPatch):
    """Changes the fields given; ``archived`` archives the list or brings it
    back. Clients only change lists they created."""
    item = changeable_list(request, list_id)
    given = data.model_fields_set
    changes = {
        f: getattr(data, f) for f in ["title", "description", "view"] if f in given
    }
    if any(value is None for value in changes.values()):
        bad_request(_("Leave out what doesn't change instead of sending null."))
    if changes:
        ops.update_list(item, actor=request.user, **changes)
    if data.archived:
        ops.archive(item, actor=request.user)
    elif "archived" in given:
        ops.unarchive(item, actor=request.user)
    return list_out(item_for(request, list_id, Kind.LIST))


class ListCopyIn(Schema):
    project_id: int
    # Left out: the list's own; " (copy)" … only on a clash
    title: Title | None = None
    dates: Literal["keep", "shift", "remove"] = "keep"
    # For "shift": how many days, negative for earlier
    days: int = Field(0, ge=-3650, le=3650)
    visible_to_clients: bool = False


@router.post("lists/{list_id}/copy/", response={201: ListOut})
def list_copy(request, list_id: int, data: ListCopyIn):
    """A copy of the list's open work in a project (this one or another):
    description, groups, open to-dos with notes, checklists, recurrence and
    the assignees who are members there; due dates kept, shifted by
    ``days`` or removed. Internal unless ``visible_to_clients``. Staff
    only, like creating lists (specs/lists-across-projects.md)."""
    item = item_for(request, list_id, Kind.LIST)
    if not ops.can_create(request.user, Kind.LIST):
        raise HttpError(403, _("Only staff create lists."))
    project = project_for(request, data.project_id)
    if data.dates == "shift" and not data.days:
        bad_request(_("Send the days to move the due dates by."))
    try:
        copy = ops.copy_list(
            item,
            project=project,
            title=data.title or item.title,
            actor=request.user,
            dates=data.dates,
            days=data.days,
            visible=data.visible_to_clients,
        )
    except ValueError as exc:
        bad_request(str(exc))
    return Status(201, list_out(copy))


class ListOrderIn(Schema):
    list_ids: list[int]


@router.put("projects/{project_id}/lists/order/", response=list[ListOut])
def list_order(request, project_id: int, data: ListOrderIn):
    """The order of the project's active lists: all their IDs, staff only"""
    if request.user.is_client:
        raise HttpError(403, _("Only staff can reorder lists."))
    project = project_for(request, project_id)
    lists = {
        item.pk: item
        for item in Item.objects.visible_to(request.user).filter(
            project=project, kind=Kind.LIST, parent=None, status=ItemStatus.ACTIVE
        )
    }
    if sorted(data.list_ids) != sorted(lists):
        bad_request(_("Send the IDs of all active lists, each once."))
    ops.reorder([lists[pk] for pk in data.list_ids])
    return list_list(request, project_id)


# Group.title's length
GroupTitle = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]


class GroupIn(Schema):
    title: GroupTitle
    # A palette name or "" for none (the default)
    color: Color | Literal[""] = ""
    # 90 (the default) or 365, staff only
    stale_after: int | None = None


@router.post("lists/{list_id}/groups/", response={201: GroupOut})
def group_create(request, list_id: int, data: GroupIn):
    item = changeable_list(request, list_id)
    group = ops.create_group(
        todolist=item.todolist,
        title=data.title,
        color=data.color,
        **_stale_after(request, data.stale_after),
    )
    return Status(201, group_out(group))


class GroupPatch(Schema):
    title: GroupTitle | None = None
    # A palette name or "" for none
    color: Color | Literal[""] | None = None
    # 90 or 365, staff only
    stale_after: int | None = None
    index: int | None = None


@router.patch("groups/{group_id}/", response=GroupOut)
def group_update(request, group_id: int, data: GroupPatch):
    """Renames the group, sets its color and/or moves it (with its to-dos)
    to ``index``"""
    group = changeable_group(request, group_id)[0]
    for field in ["title", "color"]:
        if field in data.model_fields_set and getattr(data, field) is None:
            bad_request(_("Leave out what doesn't change instead of sending null."))
    ops.update_group(
        group,
        **{
            field: getattr(data, field)
            for field in ["title", "color"]
            if field in data.model_fields_set
        },
        **_stale_after(request, data.stale_after),
    )
    if data.index is not None:
        ops.move_group(group, index=max(0, data.index))
        group.refresh_from_db()
    return group_out(group)


@router.delete("groups/{group_id}/", response={204: None})
def group_delete(request, group_id: int):
    """Removes the group; its to-dos stay, ungrouped at the end"""
    ops.delete_group(changeable_group(request, group_id)[0])
    return Status(204, None)


# To-dos ---------------------------------------------------------------------


class AssigneeOut(PersonOut):
    assigned_by: PersonOut | None = Field(
        description="Who assigned them; null for assignments from before it"
        " was stored, imported ones and people who were deleted."
    )


class TodoOut(ItemOut):
    list_id: int
    group: GroupOut | None
    position: int
    notes: str
    notes_html: str
    # The task list in the notes (specs/editor.md)
    checklist_done: int
    checklist_total: int
    starts_on: dt.date | None
    due_on: dt.date | None
    completed_at: dt.datetime | None
    completed_by: PersonOut | None
    stale_warned_at: dt.datetime | None = Field(
        None,
        description="Warned it'll be marked obsolete 14 days later unless"
        " something happens or it's kept (POST keep/, specs/stale-todos.md)",
    )
    obsolete: bool = Field(
        description="Completed as obsolete, not done (specs/stale-todos.md):"
        " by hand, or by Biwak after a warning (completed_by null)"
    )
    assignees: list[AssigneeOut]
    recurrence: str
    recurrence_description: str
    recurrence_ends_on: dt.date | None
    recurrence_count: int | None
    previous_id: int | None
    reactions: list[ReactionOut]


def _previous_id(item, todo):
    """The to-do this one was created from; not when it's internal and this
    one visible (it was moved, clients mustn't learn its ID)"""
    if todo.previous_id is None:
        return None
    previous = todo.previous
    if item.is_client_visible and not previous.is_client_visible:
        return None
    return todo.previous_id


def todo_out(item, user):
    todo = item.todo
    group = todo.group
    return item_out(item) | {
        "list_id": item.parent_id,
        "group": group and group_out(group),
        "position": item.position,
        "notes": todo.notes,
        "notes_html": html(todo.notes, item),
        "checklist_done": todo.checklist_done,
        "checklist_total": todo.checklist_total,
        "starts_on": todo.starts_on,
        "due_on": todo.due_on,
        "completed_at": todo.completed_at,
        "completed_by": person_out(todo.completed_by),
        "obsolete": todo.obsolete,
        "stale_warned_at": todo.stale_warned_at,
        "assignees": _assignees_out(item, todo, user),
        "recurrence": todo.recurrence,
        "recurrence_description": todo.recurrence_description,
        "recurrence_ends_on": todo.recurrence_ends_on,
        "recurrence_count": todo.recurrence_count,
        "previous_id": _previous_id(item, todo),
        "reactions": reactions_out(item, None, user),
    }


def _assignees_out(item, todo, user):
    """Those the reader may know (``people_known_to()``: clients and
    externals don't learn about people removed from the project)"""
    from biwak.projects.models import known_ids_for

    known = known_ids_for(user, item)
    return [
        person_out(a.user) | {"assigned_by": person_out(a.assigned_by)}
        for a in todo.assignment_set.all()
        if known is None or a.user_id in known
    ]


# The assignees in the order of the people, with who assigned them
ASSIGNMENTS = Prefetch(
    "todo__assignment_set",
    queryset=Assignment.objects.select_related("user", "assigned_by").order_by(
        Lower("user__full_name"), "user__email"
    ),
)


def _for_todo_out(qs):
    """What ``todo_out()`` reads, without a query per to-do"""
    return (
        qs
        .select_related(
            "creator", "todo__group", "todo__completed_by", "todo__previous"
        )
        .prefetch_related(ASSIGNMENTS)
        .prefetch_related(
            Prefetch("reactions", queryset=Reaction.objects.select_related("user"))
        )
    )


def _assignee(assignee):
    """``assignee`` for ``due.assigned_to()``: ``me``, ``nobody``,
    ``anybody`` (``None``, the default) or a person's ID, else 400"""
    if assignee not in {None, "", "me", "nobody", "anybody"} and not (
        assignee.isdecimal()
    ):
        bad_request(_("assignee is me, nobody, anybody or a person's ID."))
    # "anybody" like the page's "Anybody" (specs/todos.md)
    return None if assignee in {"", "anybody"} else assignee


def _group(list_item, group):
    """``group`` for ``filters.in_group()``: ``none`` (outside groups), the
    ID of one of the list's groups, or ``None`` (all), else 400"""
    if group in {None, ""}:
        return None
    if group == NO_GROUP:
        return group
    if not (
        group.isdecimal() and list_item.todolist.groups.filter(pk=int(group)).exists()
    ):
        bad_request(_("group is none or the ID of one of the list's groups."))
    return group


def _todos(request, list_item, assignee=None, group=None):
    """The list's to-dos, those assigned to ``assignee`` and in ``group``
    (as on the list's page, specs/todos.md, "Filters on a list")"""
    return _for_todo_out(
        in_group(
            due.assigned_to(
                Item.objects.visible_to(request.user).filter(
                    parent=list_item, kind=Kind.TODO
                ),
                request.user,
                _assignee(assignee),
            ),
            _group(list_item, group),
        )
    )


@router.get("lists/{list_id}/todos/", response=list[TodoOut])
def todo_list(
    request, list_id: int, assignee: str | None = None, group: str | None = None
):
    """The open to-dos in the list's order: ungrouped first, then by group;
    ``assignee`` is ``me``, ``nobody``, ``anybody`` (the default) or a
    person's ID; ``group`` is ``none`` (outside groups) or a group's ID"""
    item = item_for(request, list_id, Kind.LIST)
    todos = _todos(request, item, assignee, group).filter(
        todo__completed_at__isnull=True
    )
    groups = {g.pk: g.position for g in item.todolist.groups.all()}
    return [
        todo_out(todo, request.user)
        for todo in sorted(
            todos,
            key=lambda t: (
                t.todo.group_id is not None,
                groups.get(t.todo.group_id, 0),
                t.position,
                t.pk,
            ),
        )
    ]


@router.get("lists/{list_id}/todos/completed/", response=page_of(TodoOut))
def todo_list_completed(
    request,
    list_id: int,
    assignee: str | None = None,
    group: str | None = None,
    cursor: str | None = None,
    page_size: int | None = None,
):
    """Completed to-dos, the latest first; ``assignee`` and ``group`` as for
    the open ones"""
    item = item_for(request, list_id, Kind.LIST)
    return paginated(
        request,
        _todos(request, item, assignee, group)
        .filter(todo__completed_at__isnull=False)
        .annotate(completed=F("todo__completed_at")),
        lambda item: todo_out(item, request.user),
        ordering=("-completed", "-pk"),
        cursor=cursor,
        page_size=page_size,
    )


def _assignees(request, item, ids, *, keep=False):
    """People who can see the to-do, by ID; 400 for anybody else. ``keep``:
    those assigned already stay possible (a deactivated person, a client
    on a to-do made internal), as in the edit form
    (``ops.assignable_or_assigned()``), so a change never needs them taken
    out."""
    if ids is None:
        return None
    people = ops.assignable_or_assigned if keep else ops.assignable_people
    people = list(people(item, request.user).filter(pk__in=ids))
    if len(people) != len(set(ids)):
        bad_request(_("Only people who can see the to-do can be assigned."))
    return people


class TodoIn(Schema):
    title: Title
    notes: str = ""
    due_on: dt.date | None = None
    starts_on: dt.date | None = None
    assignees: list[int] = []
    group_id: int | None = None
    recurrence: str = ""
    recurrence_ends_on: dt.date | None = None
    recurrence_count: int | None = None


def _rule(value, anchor):
    """A preset name or an RRULE (counting from the due date, or today) as
    a valid rule; 400 for anything else"""
    try:
        return schedules.resolve(value, anchor or schedules.today())
    except schedules.InvalidRule as exc:
        bad_request(str(exc))


@contextmanager
def invalid_dates():
    """400 for a start date without a due date or after it (the operations
    check before changing anything)"""
    try:
        yield
    except ops.InvalidDates as exc:
        bad_request(str(exc))


def _count(value):
    if value is not None and value < 1:
        bad_request(_("The number of repeats left must be 1 or more."))
    return value


@router.post("lists/{list_id}/todos/", response={201: TodoOut})
def todo_create(request, list_id: int, data: TodoIn):
    item = item_for(request, list_id, Kind.LIST)
    group = None
    if data.group_id is not None:
        group = get_object_or_404(Group, pk=data.group_id, todolist=item.todolist)
    with invalid_dates():
        todo = ops.create_todo(
            todolist=item,
            title=resolve_mentions(item, data.title, author=request.user),
            creator=request.user,
            group=group,
            notes=resolve_mentions(item, data.notes, author=request.user),
            due_on=data.due_on,
            starts_on=data.starts_on,
            assignees=_assignees(request, item, data.assignees),
            recurrence=_rule(data.recurrence, data.due_on),
            recurrence_ends_on=data.recurrence_ends_on,
            recurrence_count=_count(data.recurrence_count),
        )
    return Status(201, todo_out(Item.objects.get(pk=todo.pk), request.user))


class FromTextTodoOut(Schema):
    # Set once added
    id: int | None
    title: str
    notes: str
    completed: bool
    checklist_done: int
    checklist_total: int


class FromTextGroupOut(Schema):
    # None: ungrouped, or a new group not added yet
    id: int | None
    title: str | None
    new: bool
    todos: list[FromTextTodoOut]


class FromTextOut(Schema):
    list_id: int
    added: bool
    count: int
    left_out: int
    # Why nothing can be added (only with ``preview``; else a 400)
    problem: str
    groups: list[FromTextGroupOut]


class FromTextIn(Schema):
    text: str
    preview: bool = False


def from_text_out(item, plan, *, added):
    return {
        "list_id": item.pk,
        "added": added,
        "count": plan.count,
        "left_out": plan.left_out,
        "problem": plan.problem,
        "groups": [
            {
                "id": section.group.pk if section.group is not None else None,
                "title": section.title,
                "new": section.is_new,
                "todos": [
                    {
                        "id": todo.id,
                        "title": todo.title,
                        "notes": todo.notes,
                        "completed": todo.completed,
                        "checklist_done": todo.done,
                        "checklist_total": todo.total,
                    }
                    for todo in section.todos
                ],
            }
            for section in plan.sections
            if section.title is not None or section.todos
        ],
    }


@router.post(
    "lists/{list_id}/todos/from-text/", response={200: FromTextOut, 201: FromTextOut}
)
def todos_from_text(request, list_id: int, data: FromTextIn):
    """To-dos from a Markdown or plain text (specs/todos-from-text.md):
    headings become groups, list items to-dos. ``preview`` answers the plan
    without adding anything, with ``problem`` saying why nothing could be
    added; otherwise such a problem is a 400."""
    item = item_for(request, list_id, Kind.LIST)
    if not ops.may_add_to(request.user, item):
        bad_request(_("No to-dos can be added to this list."))
    if data.preview:
        plan = ops.text_plan(item, data.text, request.user)
        return Status(200, from_text_out(item, plan, added=False))
    try:
        plan = ops.add_from_text(item, data.text, actor=request.user)
    except ops.FromTextRefused as exc:
        bad_request(str(exc))
    return Status(201, from_text_out(item, plan, added=True))


class DueTodoOut(TodoOut):
    due_group: Literal["overdue", "today", "this_week", "next_week", "later", "none"]
    project_name: str
    list_title: str
    list_position: int


@router.get("todos/", response=page_of(DueTodoOut))
def todo_overview(
    request,
    *,
    project_id: int | None = None,
    assignee: str | None = None,
    assigned_by: str | None = None,
    completed: bool = False,
    grouping: Literal["project", "due"] | None = None,
    visible_to_clients: bool | None = None,
    due_group: Literal["overdue", "today", "this_week", "next_week", "later", "none"]
    | None = None,
    started: bool | None = None,
    cursor: str | None = None,
    page_size: int | None = None,
):
    """To-dos across all projects the person sees, by due date (to-dos
    without one last) or, with ``grouping=project``, by project name, the
    list's position, the group's position (to-dos outside groups first)
    and the to-do's; ``grouping`` defaults to ``project``. ``completed`` the completed ones, the latest first.
    ``assignee`` is ``me``, ``nobody``, ``anybody`` (the default) or a
    person's ID, ``assigned_by=me``
    the to-dos the person assigned to somebody, ``due_group`` one
    of the groups of the page. ``started=true`` only those which have
    started (or have no start date), ``false`` only those starting later
    (specs/start-dates.md); without it all. Archived projects and lists
    are left out.
    Clients only ever get what is visible to them."""
    project = project_for(request, project_id) if project_id is not None else None
    assignee = _assignee(assignee)
    if assigned_by not in {None, "", "me"}:
        bad_request(_("assigned_by is me."))
    qs = _for_todo_out(
        due.todos(
            request.user,
            project=project,
            assignee=assignee or None,
            assigned_by=assigned_by or None,
            completed=completed,
            visible_to_clients=visible_to_clients,
            group=due_group,
        )
    )
    today = schedules.today()
    if started is not None:
        qs = (
            qs.filter(due.started(today))
            if started
            else qs.filter(todo__starts_on__gt=today)
        )
    grouping = grouping or "project"
    if completed:
        ordering = ("-completed_key", "-pk")
    elif grouping == "project":
        ordering = due.PROJECT_ORDERING
    else:
        ordering = ("due_key", "pk")
    if completed:
        qs = qs.annotate(completed_key=F("todo__completed_at"))
    return paginated(
        request,
        qs,
        lambda item: (
            todo_out(item, request.user)
            | {
                "due_group": due.group_of(item.todo.due_on, today),
                "project_name": item.project.name,
                "list_title": item.parent.title,
                "list_position": item.parent.position,
            }
        ),
        ordering=ordering,
        cursor=cursor,
        page_size=page_size,
    )


class AssignManyIn(Schema):
    ids: list[int]
    people: list[int]
    replace: bool = False


@router.post("todos/assign/", response=list[TodoOut])
def todos_assign(request, data: AssignManyIn):
    """ "Assign…" for several to-dos (specs/handover.md): adds ``people`` to
    each of the to-dos ``ids``, or with ``replace`` makes them their only
    assignees. All or nothing: 400 naming the problem (to-dos the person
    can't change, people who can't be assigned to every one of them).
    Returns the to-dos."""
    from biwak.items.assigning import missing_message, todos_for

    if not data.ids or not data.people:
        bad_request(_("Send at least one to-do and one person."))
    todos, missing = todos_for(request.user, list(dict.fromkeys(data.ids)))
    if missing:
        bad_request(missing_message(missing))
    people = list(
        ops.assignable_to_all_or_assigned(todos, request.user).filter(
            pk__in=data.people
        )
    )
    if len(people) != len(set(data.people)):
        bad_request(
            _(
                "Only people who can be assigned to every one of the to-dos can be assigned."
            )
        )
    try:
        ops.assign_todos(todos, people, actor=request.user, replace=data.replace)
    except ops.AssignRefused as exc:
        bad_request(str(exc))
    found = {
        item.pk: item
        for item in _for_todo_out(Item.objects.filter(pk__in=[t.pk for t in todos]))
    }
    return [todo_out(found[todo.pk], request.user) for todo in todos]


class DatesManyIn(Schema):
    ids: list[int]
    dates: Literal["set", "shift", "remove"]
    due_on: dt.date | None = None
    days: int = Field(0, ge=-3650, le=3650)


@router.post("todos/dates/", response=list[TodoOut])
def todos_dates(request, data: DatesManyIn):
    """ "Due date…" for several to-dos (specs/handover.md): ``set`` gives
    each of the to-dos ``ids`` the due date ``due_on`` (start dates stay),
    ``shift`` moves due and start dates by ``days``, ``remove`` removes
    them. All or nothing: 400 naming the problem (to-dos the person can't
    change, a start date after the new due date). Returns the to-dos."""
    from biwak.items.assigning import missing_message, todos_for

    if not data.ids:
        bad_request(_("Send at least one to-do."))
    if data.dates == "set" and data.due_on is None:
        bad_request(_("Send the due date."))
    if data.dates == "shift" and not data.days:
        bad_request(_("Send the days to move the due dates by."))
    todos, missing = todos_for(request.user, list(dict.fromkeys(data.ids)))
    if missing:
        bad_request(missing_message(missing))
    try:
        ops.date_todos(
            todos,
            actor=request.user,
            dates={"set": ops.Dates.KEEP}.get(data.dates, data.dates),
            due_on=data.due_on,
            days=data.days,
        )
    except ops.InvalidDates as exc:
        bad_request(str(exc))
    found = {
        item.pk: item
        for item in _for_todo_out(Item.objects.filter(pk__in=[t.pk for t in todos]))
    }
    return [todo_out(found[todo.pk], request.user) for todo in todos]


class MoveSelectedIn(Schema):
    ids: list[int]
    list_id: int
    group_id: int | None = None
    index: int | None = None
    # Moving into another project adds or drops people: say so first
    confirm: bool = False


@router.post("todos/move/", response=list[TodoOut])
def todos_move_selected(request, data: MoveSelectedIn):
    """The selection's "Move…" (specs/handover.md): the to-dos ``ids``,
    completed ones too, into the list ``list_id`` of any project (staff;
    clients within the to-dos' project) and ``group_id``, next to each
    other in this order at ``index`` (default: the end). All or nothing.
    Into another project people who don't see them there are added or
    dropped: without ``confirm`` that's a 400 saying who."""
    from biwak.items.assigning import missing_message, move_notes, todos_for

    if not data.ids:
        bad_request(_("Send at least one to-do."))
    todos, missing = todos_for(request.user, list(dict.fromkeys(data.ids)))
    if missing:
        bad_request(missing_message(missing))
    target = item_for(request, data.list_id, Kind.LIST)
    group = None
    if data.group_id is not None:
        group = get_object_or_404(Group, pk=data.group_id, todolist=target.todolist)
    if any(todo.project_id != target.project_id for todo in todos):
        if request.user.is_client:
            raise HttpError(403, _("Only staff move to-dos into other projects."))
        note = move_notes(todos, target.project, target.is_client_visible, request.user)
        if note and not data.confirm:
            bad_request(
                " ".join([note, _("Send “confirm”: true to move them anyway.")])
            )
    try:
        ops.move_todos_to(
            todos, todolist=target, group=group, index=data.index, actor=request.user
        )
    except ValueError as exc:
        bad_request(str(exc))
    found = {
        item.pk: item
        for item in _for_todo_out(Item.objects.filter(pk__in=[t.pk for t in todos]))
    }
    return [todo_out(found[todo.pk], request.user) for todo in todos]


class CompletionOut(Schema):
    id: int = Field(description="The event's ID, to react to it.")
    completed_by: PersonOut | None
    completed_at: dt.datetime
    reactions: list[ReactionOut]


class TodoDetailOut(TodoOut):
    completions: list[CompletionOut] = Field(
        description="Each time it was completed, oldest first, with the"
        " reactions to it (specs/reactions.md); clients only those of the time"
        " they saw it. Only here, not in lists."
    )


def completions_out(item, user):
    events = (
        Event.objects
        .visible_to(user)
        .filter(item=item, action=Action.COMPLETED)
        .select_related("actor")
        .order_by("created_at", "pk")
    )
    return [
        {
            "id": event.pk,
            "completed_by": person_out(event.actor),
            "completed_at": event.created_at,
            "reactions": reactions_out(item, None, user, event),
        }
        for event in events
    ]


@router.get("todos/{todo_id}/", response=TodoDetailOut)
def todo_detail(request, todo_id: int):
    item = item_for(request, todo_id, Kind.TODO)
    return todo_out(item, request.user) | {
        "completions": completions_out(item, request.user)
    }


class TodoPatch(Schema):
    title: Title | None = None
    notes: str | None = None
    due_on: dt.date | None = None
    starts_on: dt.date | None = None
    assignees: list[int] | None = None
    recurrence: str | None = None
    recurrence_ends_on: dt.date | None = None
    recurrence_count: int | None = None


@router.patch("todos/{todo_id}/", response=TodoOut)
def todo_update(request, todo_id: int, data: TodoPatch):
    """Changes the fields given; ``assignees`` is the complete new set,
    ``"due_on": null`` removes the due date and the start date,
    ``"starts_on": null`` the start date; a start date needs a due date
    and can't be after it. ``recurrence`` is a preset name
    (counting from the due date) or an RRULE; ``null`` or ``""`` removes it
    and its end and count."""
    item = item_for(request, todo_id, Kind.TODO)
    given = data.model_fields_set
    changes = {
        field: getattr(data, field)
        for field in ["title", "notes", "due_on", "starts_on"]
        if field in given
    }
    if "title" in changes and changes["title"] is None:
        bad_request(_("The title can't be empty."))
    if "notes" in changes and changes["notes"] is None:
        changes["notes"] = ""
    for field in {"title", "notes"} & changes.keys():
        changes[field] = resolve_mentions(item, changes[field], author=request.user)
    if "assignees" in given:
        changes["assignees"] = _assignees(
            request, item, data.assignees or [], keep=True
        )
    if "recurrence" in given:
        anchor = changes.get("due_on", item.todo.due_on)
        changes["recurrence"] = _rule(data.recurrence, anchor)
    for field in ["recurrence_ends_on", "recurrence_count"]:
        if field in given:
            changes[field] = getattr(data, field)
    _count(changes.get("recurrence_count"))
    with invalid_dates():
        ops.update_todo(item, actor=request.user, **changes)
    return todo_out(item_for(request, todo_id, Kind.TODO), request.user)


@router.post("todos/{todo_id}/complete/", response=TodoOut)
def todo_complete(request, todo_id: int):
    item = item_for(request, todo_id, Kind.TODO)
    ops.complete(item, actor=request.user)
    return todo_out(item_for(request, todo_id, Kind.TODO), request.user)


@router.post("todos/{todo_id}/obsolete/", response=TodoOut)
def todo_obsolete(request, todo_id: int):
    """Completes it as obsolete, not done (specs/stale-todos.md); reopening
    undoes it. Already completed, nothing happens."""
    item = item_for(request, todo_id, Kind.TODO)
    ops.mark_obsolete(item, actor=request.user)
    return todo_out(item_for(request, todo_id, Kind.TODO), request.user)


@router.post("todos/{todo_id}/keep/", response=TodoOut)
def todo_keep(request, todo_id: int):
    """ "Keep open": starts the clock of a stale to-do again and ends its
    warning (specs/stale-todos.md); an internal event telling nobody"""
    item = item_for(request, todo_id, Kind.TODO)
    stale.keep(item, actor=request.user)
    return todo_out(item_for(request, todo_id, Kind.TODO), request.user)


@router.post("todos/{todo_id}/reopen/", response=TodoOut)
def todo_reopen(request, todo_id: int):
    item = item_for(request, todo_id, Kind.TODO)
    ops.reopen(item, actor=request.user)
    return todo_out(item_for(request, todo_id, Kind.TODO), request.user)


class MoveIn(Schema):
    list_id: int | None = None
    group_id: int | None = None
    index: int | None = None


@router.post("todos/{todo_id}/move/", response=TodoOut)
def todo_move(request, todo_id: int, data: MoveIn):
    """Into a list (default: its own) and group (default: ungrouped), at an
    index (default: the end). Clients can't move to-dos into lists they
    don't see."""
    item = item_for(request, todo_id, Kind.TODO)
    target = item_for(request, data.list_id or item.parent_id, Kind.LIST)
    if target.project_id != item.project_id:
        bad_request(_("To-dos can't move to another project."))
    group = None
    if data.group_id is not None:
        group = get_object_or_404(Group, pk=data.group_id, todolist=target.todolist)
    ops.move_todo(
        item, todolist=target, group=group, index=data.index, actor=request.user
    )
    return todo_out(Item.objects.get(pk=todo_id), request.user)


class MoveManyIn(Schema):
    todo_ids: list[int]
    group_id: int | None = None
    index: int | None = None


@router.post("lists/{list_id}/todos/move/", response=list[TodoOut])
def todos_move(request, list_id: int, data: MoveManyIn):
    """Moves several to-dos together into the list's group (or ungrouped),
    next to each other in the given order at ``index`` (default: the end)"""
    target = item_for(request, list_id, Kind.LIST)
    # A repeated ID counts once, as in todos/move/
    ids = list(dict.fromkeys(data.todo_ids))
    todos = todos_to_move(request, target, ids)
    group = None
    if data.group_id is not None:
        group = get_object_or_404(Group, pk=data.group_id, todolist=target.todolist)
    try:
        ops.move_todos(
            [todos[pk] for pk in ids],
            todolist=target,
            group=group,
            index=data.index,
            actor=request.user,
        )
    except ValueError as exc:
        bad_request(str(exc))
    return [todo_out(item_for(request, pk, Kind.TODO), request.user) for pk in ids]


# Comments and subscriptions -------------------------------------------------


class CommentOut(Schema):
    id: int
    item_id: int
    author: PersonOut
    content: str
    content_html: str
    created_at: dt.datetime
    visible_to_clients: bool
    reactions: list[ReactionOut]


@router.get("items/{item_id}/comments/", response=page_of(CommentOut))
def comment_list(
    request, item_id: int, cursor: str | None = None, page_size: int | None = None
):
    """Oldest first, like on the page"""
    item = item_for(request, item_id)
    prefetch(item)
    return paginated(
        request,
        item.comments.select_related("author"),
        lambda comment: comment_out(comment, item, request.user),
        ordering=("created_at", "pk"),
        cursor=cursor,
        page_size=page_size,
    )


def comment_out(comment, item, user):
    return {
        "id": comment.pk,
        "item_id": item.pk,
        "author": person_out(comment.author),
        "content": comment.content,
        "content_html": html(comment.content, item),
        "created_at": comment.created_at,
        "visible_to_clients": item.is_client_visible,
        "reactions": reactions_out(item, comment, user),
    }


class CommentIn(Schema):
    content: str


@router.post("items/{item_id}/comments/", response={201: CommentOut})
def comment_create(request, item_id: int, data: CommentIn):
    item = item_for(request, item_id)
    if not item.is_commentable:
        bad_request(_("Lists and folders have no comments."))
    if not data.content.strip():
        bad_request(_("The comment is empty."))
    comment = ops.add_comment(
        item,
        author=request.user,
        content=resolve_mentions(item, data.content, author=request.user),
    )
    return Status(201, comment_out(comment, item, request.user))


class SubscriptionOut(Schema):
    item_id: int
    subscribed: bool


@router.get("items/{item_id}/subscription/", response=SubscriptionOut)
def subscription_detail(request, item_id: int):
    item = item_for(request, item_id)
    return {"item_id": item.pk, "subscribed": is_subscribed(request.user, item)}


@router.put("items/{item_id}/subscription/", response=SubscriptionOut)
def subscription_create(request, item_id: int):
    item = item_for(request, item_id)
    subscribe(request.user, item)
    return {"item_id": item.pk, "subscribed": True}


@router.delete("items/{item_id}/subscription/", response=SubscriptionOut)
def subscription_delete(request, item_id: int):
    item = item_for(request, item_id)
    try:
        unsubscribe(request.user, item)
    except StillAssigned as exc:
        bad_request(str(exc))
    return {"item_id": item.pk, "subscribed": False}


class SubscriberOut(Schema):
    person: PersonOut
    added_by: PersonOut | None = Field(
        description="Who subscribed them, if somebody else (and you may know them)"
    )
    created_at: dt.datetime


class SubscribersOut(Schema):
    item_id: int
    visible_to_clients: bool
    subscribers: list[SubscriberOut]


def subscribers_out(item, user):
    """The item's subscribers the person may know (clients and externals:
    the members), by name"""
    subscriptions = list(
        item.subscriptions.select_related("user", "added_by").order_by(
            "created_at", "pk"
        )
    )
    known = {
        person.pk
        for person in item.project.people_known_to(
            user,
            [s.user for s in subscriptions]
            + [s.added_by for s in subscriptions if s.added_by],
        )
    }
    return {
        "item_id": item.pk,
        "visible_to_clients": item.is_client_visible,
        "subscribers": [
            {
                "person": person_out(s.user),
                "added_by": person_out(s.added_by) if s.added_by_id in known else None,
                "created_at": s.created_at,
            }
            for s in subscriptions
            if s.user_id in known
        ],
    }


@router.get("items/{item_id}/subscribers/", response=SubscribersOut)
def subscriber_list(request, item_id: int):
    """Everybody who gets what happens to the item, with who added them"""
    return subscribers_out(item_for(request, item_id), request.user)


class SubscribersIn(Schema):
    people: list[int] = Field(description="The IDs of the people to subscribe")
    notify: bool = Field(
        default=False, description="Tell them now (the `shared` event)"
    )
    note: Annotated[str, StringConstraints(max_length=NOTE_LENGTH)] = Field(
        default="", description="One line sent with it when you tell them now"
    )


@router.post("items/{item_id}/subscribers/", response=SubscribersOut)
def subscriber_add(request, item_id: int, data: SubscribersIn):
    """Subscribes others: people who can see the item and whom you may
    know. With `notify` each gets a notification at once (the `shared`
    event: "Ada wants you to see this"); otherwise they hear about the next
    change. Answers with all subscribers."""
    item = item_for(request, item_id)
    if not data.people:
        bad_request(_("Send at least one person."))
    users = list(
        subscribable_people(item, request.user).filter(pk__in=set(data.people))
    )
    if len(users) != len(set(data.people)):
        bad_request(_("Some of them can't be subscribed to this."))
    share(item, users, actor=request.user, notify=data.notify, note=data.note)
    return subscribers_out(item, request.user)


class SwitchIn(Schema):
    visible_to_clients: bool


@router.put("items/{item_id}/visibility/", response=ItemOut)
def visibility_switch(request, item_id: int, data: SwitchIn):
    """The visibility switch, staff only, on items which have one"""
    if request.user.is_client:
        raise HttpError(403, _("Only staff can change what clients see."))
    item = item_for(request, item_id)
    if not item.has_switch:
        bad_request(str(SWITCH_MESSAGE))
    ops.set_visibility(item, visible=data.visible_to_clients, actor=request.user)
    return item_out(item_for(request, item_id))


# The trash ----------------------------------------------------------------


@router.delete("items/{item_id}/", response=ItemOut)
def item_trash(request, item_id: int):
    """Moves the item (with what's in it) to the trash for 30 days; clients
    only what they created"""
    item = item_for(request, item_id)
    if not ops.can_change(request.user, item):
        raise HttpError(403, _("You can only trash what you created."))
    ops.trash(item, actor=request.user)
    item.refresh_from_db()
    return item_out(item)


@router.get("projects/{project_id}/trash/", response=list[ItemOut])
def project_trash(request, project_id: int):
    """Trashed items (not those trashed with their parent), staff only"""
    if request.user.is_client:
        raise HttpError(403, _("Only staff see the trash."))
    project = project_for(request, project_id)
    return [
        item_out(item)
        for item in ops.trashed_roots(
            Item.objects
            .visible_to(request.user, with_trashed=True)
            .filter(project=project)
            .select_related("creator")
        )
    ]


@router.post("items/{item_id}/restore/", response=ItemOut)
def item_restore(request, item_id: int):
    if request.user.is_client:
        raise HttpError(403, _("Only staff restore from the trash."))
    item = get_object_or_404(
        Item.objects.visible_to(request.user, with_trashed=True), pk=item_id
    )
    try:
        ops.restore(item, actor=request.user)
    except ValueError as exc:
        bad_request(str(exc))
    return item_out(item_for(request, item_id))
