"""Lists, groups, to-dos, comments and subscriptions (specs/core.md,
specs/api-cli.md). The same operations as the web interface, so writes
create the same events and subscriptions."""

import datetime as dt

from django.db.models import F
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _
from ninja import Router, Schema, Status
from ninja.errors import HttpError

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
from biwak.items import operations as ops
from biwak.items.models import Group, Item, Kind, Status as ItemStatus
from biwak.items.views import assignable_people
from biwak.projects.api import project_for


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


class GroupIn(Schema):
    title: str


@router.post("lists/{list_id}/groups/", response={201: GroupOut})
def group_create(request, list_id: int, data: GroupIn):
    item = item_for(request, list_id, Kind.LIST)
    group = ops.create_group(todolist=item.todolist, title=data.title[:200])
    return Status(
        201, {"id": group.pk, "title": group.title, "position": group.position}
    )


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


def todo_out(item):
    todo = item.todo
    group = todo.group
    return item_out(item) | {
        "list_id": item.parent_id,
        "group": group
        and {"id": group.pk, "title": group.title, "position": group.position},
        "position": item.position,
        "notes": todo.notes,
        "notes_html": html(todo.notes),
        "starts_on": todo.starts_on,
        "due_on": todo.due_on,
        "completed_at": todo.completed_at,
        "completed_by": person_out(todo.completed_by),
        "assignees": [person_out(user) for user in todo.assignees.all()],
    }


def _todos(request, list_item):
    return (
        Item.objects
        .visible_to(request.user)
        .filter(parent=list_item, kind=Kind.TODO)
        .select_related("creator", "todo__group", "todo__completed_by")
        .prefetch_related("todo__assignees")
    )


@router.get("lists/{list_id}/todos/", response=list[TodoOut])
def todo_list(request, list_id: int):
    """The open to-dos in the list's order: ungrouped first, then by group"""
    item = item_for(request, list_id, Kind.LIST)
    todos = _todos(request, item).filter(todo__completed_at__isnull=True)
    groups = {g.pk: g.position for g in item.todolist.groups.all()}
    return [
        todo_out(todo)
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
        todo_out,
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


@router.post("lists/{list_id}/todos/", response={201: TodoOut})
def todo_create(request, list_id: int, data: TodoIn):
    item = item_for(request, list_id, Kind.LIST)
    group = None
    if data.group_id is not None:
        group = get_object_or_404(Group, pk=data.group_id, todolist=item.todolist)
    todo = ops.create_todo(
        todolist=item,
        title=data.title,
        creator=request.user,
        group=group,
        notes=data.notes,
        due_on=data.due_on,
        assignees=_assignees(item, data.assignees),
    )
    return Status(201, todo_out(Item.objects.get(pk=todo.pk)))


@router.get("todos/{todo_id}/", response=TodoOut)
def todo_detail(request, todo_id: int):
    return todo_out(item_for(request, todo_id, Kind.TODO))


class TodoPatch(Schema):
    title: str | None = None
    notes: str | None = None
    due_on: dt.date | None = None
    assignees: list[int] | None = None


@router.patch("todos/{todo_id}/", response=TodoOut)
def todo_update(request, todo_id: int, data: TodoPatch):
    """Changes the fields given; ``assignees`` is the complete new set,
    ``"due_on": null`` removes the due date"""
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
    if "assignees" in given:
        changes["assignees"] = _assignees(item, data.assignees or [])
    ops.update_todo(item, actor=request.user, **changes)
    return todo_out(item_for(request, todo_id, Kind.TODO))


@router.post("todos/{todo_id}/complete/", response=TodoOut)
def todo_complete(request, todo_id: int):
    item = item_for(request, todo_id, Kind.TODO)
    ops.complete(item, actor=request.user)
    return todo_out(item_for(request, todo_id, Kind.TODO))


@router.post("todos/{todo_id}/reopen/", response=TodoOut)
def todo_reopen(request, todo_id: int):
    item = item_for(request, todo_id, Kind.TODO)
    ops.reopen(item, actor=request.user)
    return todo_out(item_for(request, todo_id, Kind.TODO))


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
    return todo_out(Item.objects.get(pk=todo_id))


# Comments and subscriptions -------------------------------------------------


class CommentOut(Schema):
    id: int
    item_id: int
    author: PersonOut
    content: str
    content_html: str
    created_at: dt.datetime
    visible_to_clients: bool


@router.get("items/{item_id}/comments/", response=page_of(CommentOut))
def comment_list(
    request, item_id: int, cursor: str | None = None, page_size: int | None = None
):
    """Oldest first, like on the page"""
    item = item_for(request, item_id)
    return paginated(
        request,
        item.comments.select_related("author"),
        lambda comment: comment_out(comment, item),
        ordering=("created_at", "pk"),
        cursor=cursor,
        page_size=page_size,
    )


def comment_out(comment, item):
    return {
        "id": comment.pk,
        "item_id": item.pk,
        "author": person_out(comment.author),
        "content": comment.content,
        "content_html": html(comment.content),
        "created_at": comment.created_at,
        "visible_to_clients": item.is_client_visible,
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
    comment = ops.add_comment(item, author=request.user, content=data.content)
    return Status(201, comment_out(comment, item))


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
