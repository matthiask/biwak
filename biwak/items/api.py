"""Lists, groups, to-dos, comments and subscriptions (specs/core.md,
specs/api-cli.md). The same operations as the web interface, so writes
create the same events and subscriptions."""

import datetime as dt
from typing import Literal

from django.db.models import F, Prefetch
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _
from ninja import Router, Schema, Status
from ninja.errors import HttpError

from biwak import schedules
from biwak.activity.mentions import resolve as resolve_mentions
from biwak.activity.operations import is_subscribed, subscribe, unsubscribe
from biwak.api_conventions import (
    ItemOut,
    PersonOut,
    html,
    item_out,
    page_of,
    paginated,
    person_out,
)
from biwak.items import due, operations as ops
from biwak.items.models import Group, Item, Kind, Status as ItemStatus
from biwak.items.views import assignable_people
from biwak.projects.api import project_for
from biwak.reactions.models import Reaction
from biwak.reactions.operations import prefetch
from biwak.reactions.schemas import ReactionOut, reactions_out


router = Router(tags=["items"])


def item_for(request, pk, kind=None):
    """The item if the person may see it, else 404: the one check
    (specs/access.md)"""
    qs = Item.objects.visible_to(request.user).select_related(
        "project", "parent", "creator"
    )
    if kind:
        qs = qs.filter(kind=kind)
    return get_object_or_404(qs, pk=pk)


def bad_request(message):
    raise HttpError(400, message)


# Lists ----------------------------------------------------------------------


class GroupOut(Schema):
    id: int
    title: str
    position: int


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
        "groups": [
            {"id": g.pk, "title": g.title, "position": g.position}
            for g in todolist.groups.all()
        ],
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
    title: str
    description: str = ""
    visible_to_clients: bool = False


@router.post("projects/{project_id}/lists/", response={201: ListOut})
def list_create(request, project_id: int, data: ListIn):
    """What clients create is visible to clients (specs/access.md)"""
    project = project_for(request, project_id)
    item = ops.create_list(
        project=project,
        title=data.title,
        description=data.description,
        creator=request.user,
        visible=data.visible_to_clients or request.user.is_client,
    )
    return Status(201, list_out(item))


@router.get("lists/{list_id}/", response=ListOut)
def list_detail(request, list_id: int):
    return list_out(item_for(request, list_id, Kind.LIST))


class ListPatch(Schema):
    title: str | None = None
    description: str | None = None
    view: Literal["list", "board"] | None = None
    archived: bool | None = None


@router.patch("lists/{list_id}/", response=ListOut)
def list_update(request, list_id: int, data: ListPatch):
    """Changes the fields given; ``archived`` archives the list or brings it
    back. Clients only change lists they created."""
    item = item_for(request, list_id, Kind.LIST)
    if not ops.can_change(request.user, item):
        raise HttpError(403, _("You can only change lists you created."))
    given = data.model_fields_set
    changes = {
        f: getattr(data, f) for f in ["title", "description", "view"] if f in given
    }
    empty_title = "title" in changes and not changes["title"]
    if empty_title or any(value is None for value in changes.values()):
        bad_request(_("Leave out what doesn't change instead of sending null."))
    if changes:
        ops.update_list(item, actor=request.user, **changes)
    if "archived" in given:
        archived = item.status == ItemStatus.ARCHIVED
        if data.archived and not archived:
            ops.archive(item, actor=request.user)
        elif archived and not data.archived:
            ops.unarchive(item, actor=request.user)
    return list_out(item_for(request, list_id, Kind.LIST))


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


class GroupIn(Schema):
    title: str


@router.post("lists/{list_id}/groups/", response={201: GroupOut})
def group_create(request, list_id: int, data: GroupIn):
    item = item_for(request, list_id, Kind.LIST)
    group = ops.create_group(todolist=item.todolist, title=data.title[:200])
    return Status(
        201, {"id": group.pk, "title": group.title, "position": group.position}
    )


class GroupPatch(Schema):
    title: str | None = None
    index: int | None = None


def _group_for(request, group_id):
    group = get_object_or_404(Group, pk=group_id)
    item_for(request, group.todolist_id, Kind.LIST)
    return group


@router.patch("groups/{group_id}/", response=GroupOut)
def group_update(request, group_id: int, data: GroupPatch):
    """Renames the group and/or moves it (with its to-dos) to ``index``"""
    group = _group_for(request, group_id)
    if data.title:
        ops.rename_group(group, title=data.title[:200])
    if data.index is not None:
        ops.move_group(group, index=max(0, data.index))
        group.refresh_from_db()
    return {"id": group.pk, "title": group.title, "position": group.position}


@router.delete("groups/{group_id}/", response={204: None})
def group_delete(request, group_id: int):
    """Removes the group; its to-dos stay, ungrouped at the end"""
    ops.delete_group(_group_for(request, group_id))
    return Status(204, None)


# To-dos ---------------------------------------------------------------------


class TodoOut(ItemOut):
    list_id: int
    group: GroupOut | None
    position: int
    notes: str
    notes_html: str
    starts_on: dt.date | None
    due_on: dt.date | None
    completed_at: dt.datetime | None
    completed_by: PersonOut | None
    assignees: list[PersonOut]
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
        "group": group
        and {"id": group.pk, "title": group.title, "position": group.position},
        "position": item.position,
        "notes": todo.notes,
        "notes_html": html(todo.notes, item),
        "starts_on": todo.starts_on,
        "due_on": todo.due_on,
        "completed_at": todo.completed_at,
        "completed_by": person_out(todo.completed_by),
        "assignees": [person_out(user) for user in todo.assignees.all()],
        "recurrence": todo.recurrence,
        "recurrence_description": todo.recurrence_description,
        "recurrence_ends_on": todo.recurrence_ends_on,
        "recurrence_count": todo.recurrence_count,
        "previous_id": _previous_id(item, todo),
        "reactions": reactions_out(item, None, user),
    }


def _todos(request, list_item):
    return (
        Item.objects
        .visible_to(request.user)
        .filter(parent=list_item, kind=Kind.TODO)
        .select_related(
            "creator", "todo__group", "todo__completed_by", "todo__previous"
        )
        .prefetch_related("todo__assignees")
        .prefetch_related(
            Prefetch("reactions", queryset=Reaction.objects.select_related("user"))
        )
    )


@router.get("lists/{list_id}/todos/", response=list[TodoOut])
def todo_list(request, list_id: int):
    """The open to-dos in the list's order: ungrouped first, then by group"""
    item = item_for(request, list_id, Kind.LIST)
    todos = _todos(request, item).filter(todo__completed_at__isnull=True)
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
    request, list_id: int, cursor: str | None = None, page_size: int | None = None
):
    """Completed to-dos, the latest first"""
    item = item_for(request, list_id, Kind.LIST)
    return paginated(
        request,
        _todos(request, item)
        .filter(todo__completed_at__isnull=False)
        .annotate(completed=F("todo__completed_at")),
        lambda item: todo_out(item, request.user),
        ordering=("-completed", "-pk"),
        cursor=cursor,
        page_size=page_size,
    )


def _assignees(item, ids):
    """People who can see the to-do, by ID; 400 for anybody else"""
    if ids is None:
        return None
    people = list(assignable_people(item).filter(pk__in=ids))
    if len(people) != len(set(ids)):
        bad_request(_("Only people who can see the to-do can be assigned."))
    return people


class TodoIn(Schema):
    title: str
    notes: str = ""
    due_on: dt.date | None = None
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
    todo = ops.create_todo(
        todolist=item,
        title=resolve_mentions(item, data.title),
        creator=request.user,
        group=group,
        notes=resolve_mentions(item, data.notes),
        due_on=data.due_on,
        assignees=_assignees(item, data.assignees),
        recurrence=_rule(data.recurrence, data.due_on),
        recurrence_ends_on=data.recurrence_ends_on,
        recurrence_count=_count(data.recurrence_count),
    )
    return Status(201, todo_out(Item.objects.get(pk=todo.pk), request.user))


class DueTodoOut(TodoOut):
    due_group: Literal["overdue", "today", "this_week", "later", "none"]
    project_name: str
    list_title: str


@router.get("todos/", response=page_of(DueTodoOut))
def todo_overview(
    request,
    *,
    project_id: int | None = None,
    list_id: int | None = None,
    assignee: str | None = None,
    completed: bool = False,
    visible_to_clients: bool | None = None,
    due_group: Literal["overdue", "today", "this_week", "later", "none"] | None = None,
    cursor: str | None = None,
    page_size: int | None = None,
):
    """To-dos across all projects the person sees, by due date (to-dos
    without one last); ``completed`` the completed ones, the latest first.
    ``assignee`` is ``me``, ``nobody`` or a person's ID, ``due_group`` one
    of the groups of the page. Archived projects and lists are left out.
    Clients only ever get what is visible to them."""
    project = project_for(request, project_id) if project_id is not None else None
    todolist = item_for(request, list_id, Kind.LIST) if list_id is not None else None
    if assignee not in {None, "", "me", "nobody"} and not assignee.isdecimal():
        bad_request(_("assignee is me, nobody or a person's ID."))
    qs = due.todos(
        request.user,
        project=project,
        todolist=todolist,
        assignee=assignee or None,
        completed=completed,
        visible_to_clients=visible_to_clients,
        group=due_group,
    )
    today = schedules.today()
    ordering = ("-completed_key", "-pk") if completed else ("due_key", "pk")
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
            }
        ),
        ordering=ordering,
        cursor=cursor,
        page_size=page_size,
    )


@router.get("todos/{todo_id}/", response=TodoOut)
def todo_detail(request, todo_id: int):
    return todo_out(item_for(request, todo_id, Kind.TODO), request.user)


class TodoPatch(Schema):
    title: str | None = None
    notes: str | None = None
    due_on: dt.date | None = None
    assignees: list[int] | None = None
    recurrence: str | None = None
    recurrence_ends_on: dt.date | None = None
    recurrence_count: int | None = None


@router.patch("todos/{todo_id}/", response=TodoOut)
def todo_update(request, todo_id: int, data: TodoPatch):
    """Changes the fields given; ``assignees`` is the complete new set,
    ``"due_on": null`` removes the due date. ``recurrence`` is a preset name
    (counting from the due date) or an RRULE; ``null`` or ``""`` removes it
    and its end and count."""
    item = item_for(request, todo_id, Kind.TODO)
    given = data.model_fields_set
    changes = {
        field: getattr(data, field)
        for field in ["title", "notes", "due_on"]
        if field in given
    }
    if changes.get("title", "x") in {None, ""}:
        bad_request(_("The title can't be empty."))
    if "notes" in changes and changes["notes"] is None:
        changes["notes"] = ""
    for field in {"title", "notes"} & changes.keys():
        changes[field] = resolve_mentions(item, changes[field])
    if "assignees" in given:
        changes["assignees"] = _assignees(item, data.assignees or [])
    if "recurrence" in given:
        anchor = changes.get("due_on", item.todo.due_on)
        changes["recurrence"] = _rule(data.recurrence, anchor)
    for field in ["recurrence_ends_on", "recurrence_count"]:
        if field in given:
            changes[field] = getattr(data, field)
    _count(changes.get("recurrence_count"))
    ops.update_todo(item, actor=request.user, **changes)
    return todo_out(item_for(request, todo_id, Kind.TODO), request.user)


@router.post("todos/{todo_id}/complete/", response=TodoOut)
def todo_complete(request, todo_id: int):
    item = item_for(request, todo_id, Kind.TODO)
    ops.complete(item, actor=request.user)
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
    todos = {
        todo.pk: todo
        for todo in Item.objects
        .visible_to(request.user)
        .filter(pk__in=data.todo_ids, kind=Kind.TODO, project=target.project_id)
        .select_related("todo")
    }
    if not data.todo_ids or len(todos) != len(set(data.todo_ids)):
        raise HttpError(404, _("Not all of these to-dos were found."))
    group = None
    if data.group_id is not None:
        group = get_object_or_404(Group, pk=data.group_id, todolist=target.todolist)
    ops.move_todos(
        [todos[pk] for pk in data.todo_ids],
        todolist=target,
        group=group,
        index=data.index,
        actor=request.user,
    )
    return [
        todo_out(item_for(request, pk, Kind.TODO), request.user) for pk in data.todo_ids
    ]


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
        item, author=request.user, content=resolve_mentions(item, data.content)
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
    unsubscribe(request.user, item)
    return {"item_id": item.pk, "subscribed": False}


class SwitchIn(Schema):
    visible_to_clients: bool


@router.put("items/{item_id}/visibility/", response=ItemOut)
def visibility_switch(request, item_id: int, data: SwitchIn):
    """The visibility switch, staff only, on items which have one"""
    if request.user.is_client:
        raise HttpError(403, _("Only staff can change what clients see."))
    item = item_for(request, item_id)
    if not item.has_switch:
        bad_request(
            _("Only top-level lists, folders, messages and docs have a switch.")
        )
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
