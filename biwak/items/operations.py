"""Creating and changing items (specs/core.md)

Every change goes through here: it writes the item and its detail row
together, keeps positions and the stored visibility right, and records the
event and the subscriptions. Views, the API and imports call these, they
don't save items themselves.
"""

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from biwak.activity.models import Action
from biwak.activity.operations import record, subscribe
from biwak.items import visibility
from biwak.items.models import (
    Comment,
    Doc,
    Folder,
    Group,
    Item,
    Kind,
    Message,
    Status,
    Todo,
    TodoList,
)


def _next_position(qs):
    return (qs.aggregate(m=Max("position"))["m"] or 0) + 1


def _create_item(*, project, kind, title, creator, parent=None, visible=False):
    siblings = Item.objects.filter(project=project, parent=parent, kind=kind)
    item = Item(
        project=project,
        parent=parent,
        kind=kind,
        title=title,
        creator=creator,
        position=_next_position(siblings),
        visible_to_clients=visible,
    )
    item.save()
    visibility.recompute(item)
    return item


def _created(item, creator):
    subscribe(creator, item)
    record(actor=creator, action=Action.CREATED, project=item.project, item=item)


@transaction.atomic
def create_list(*, project, title, creator, description="", visible=False):
    item = _create_item(
        project=project, kind=Kind.LIST, title=title, creator=creator, visible=visible
    )
    TodoList.objects.create(item=item, description=description)
    _created(item, creator)
    return item


@transaction.atomic
def create_group(*, todolist, title):
    return Group.objects.create(
        todolist=todolist,
        title=title,
        position=_next_position(todolist.groups.all()),
    )


def _todos_in(todolist_item, group):
    """The open to-dos of a list's group (or the ungrouped ones), in order"""
    return Item.objects.filter(
        parent=todolist_item,
        kind=Kind.TODO,
        todo__group=group,
        todo__completed_at__isnull=True,
    ).exclude(status=Status.TRASHED)


@transaction.atomic
def create_todo(
    *, todolist, title, creator, group=None, notes="", due_on=None, assignees=()
):
    """``todolist`` is the list's item"""
    TodoList.objects.select_for_update().get(item=todolist)
    if group is not None and group.todolist_id != todolist.pk:
        raise ValueError("The group belongs to another list")
    item = Item(
        project=todolist.project,
        parent=todolist,
        kind=Kind.TODO,
        title=title,
        creator=creator,
        position=_next_position(_todos_in(todolist, group)),
    )
    item.save()
    visibility.recompute(item)
    Todo.objects.create(item=item, group=group, notes=notes, due_on=due_on)
    _created(item, creator)
    if assignees:
        assign(item, assignees, actor=creator)
    return item


@transaction.atomic
def create_message(*, project, title, creator, content="", visible=False):
    item = _create_item(
        project=project,
        kind=Kind.MESSAGE,
        title=title,
        creator=creator,
        visible=visible,
    )
    Message.objects.create(item=item, content=content)
    _created(item, creator)
    return item


@transaction.atomic
def create_folder(*, project, title, creator, parent=None, visible=False):
    item = _create_item(
        project=project,
        kind=Kind.FOLDER,
        title=title,
        creator=creator,
        parent=parent,
        visible=visible and parent is None,
    )
    Folder.objects.create(item=item)
    _created(item, creator)
    return item


@transaction.atomic
def create_doc(*, project, title, creator, parent=None, content="", visible=False):
    item = _create_item(
        project=project,
        kind=Kind.DOC,
        title=title,
        creator=creator,
        parent=parent,
        visible=visible and parent is None,
    )
    Doc.objects.create(item=item, content=content)
    _created(item, creator)
    return item


@transaction.atomic
def add_comment(item, *, author, content):
    comment = Comment.objects.create(item=item, author=author, content=content)
    subscribe(author, item, explicit=False)
    record(
        actor=author,
        action=Action.COMMENTED,
        project=item.project,
        item=item,
        comment=comment.pk,
    )
    return comment


def can_be_assigned(user, item):
    """Clients only on to-dos visible to them (specs/access.md)"""
    return Item.objects.visible_to(user).filter(pk=item.pk).exists()


@transaction.atomic
def assign(item, users, *, actor):
    """Adds assignees; returns those newly assigned"""
    todo = item.todo
    users = [u for u in users if not todo.assignees.filter(pk=u.pk).exists()]
    for user in users:
        if not can_be_assigned(user, item):
            raise ValueError(f"{user} can't see {item}")
    todo.assignees.add(*users)
    for user in users:
        subscribe(user, item, added_by=actor)
    if users:
        record(
            actor=actor,
            action=Action.ASSIGNED,
            project=item.project,
            item=item,
            assignees=[u.pk for u in users],
        )
    return users


@transaction.atomic
def unassign(item, users, *, actor):
    item.todo.assignees.remove(*users)


@transaction.atomic
def complete(item, *, actor):
    """Completes the to-do for all its assignees"""
    todo = Todo.objects.select_for_update().get(item=item)
    if todo.is_completed:
        return
    todo.completed_at = timezone.now()
    todo.completed_by = actor
    todo.save(update_fields=["completed_at", "completed_by"])
    record(actor=actor, action=Action.COMPLETED, project=item.project, item=item)


@transaction.atomic
def reopen(item, *, actor):
    """Back at the end of its group"""
    todo = Todo.objects.select_for_update().get(item=item)
    if not todo.is_completed:
        return
    item.position = _next_position(_todos_in(item.parent, todo.group))
    item.save(update_fields=["position"])
    todo.completed_at = None
    todo.completed_by = None
    todo.save(update_fields=["completed_at", "completed_by"])
    record(actor=actor, action=Action.REOPENED, project=item.project, item=item)


def _renumber(items):
    for position, item in enumerate(items, start=1):
        if item.position != position:
            Item.objects.filter(pk=item.pk).update(position=position)
            item.position = position


@transaction.atomic
def move_todo(item, *, todolist, group=None, index=None, actor):
    """Moves a to-do into a list's group (or ungrouped) at ``index`` (0-based,
    None: at the end). Locks the lists, so concurrent moves don't mix up
    positions. Moving into another list recomputes its visibility."""
    source = item.parent
    lists = sorted({source.pk, todolist.pk})
    list(TodoList.objects.select_for_update().filter(item__in=lists).order_by("pk"))
    if group is not None and group.todolist_id != todolist.pk:
        raise ValueError("The group belongs to another list")
    if todolist.project_id != item.project_id:
        raise ValueError("Moving to-dos between projects isn't possible")

    todo = item.todo
    old_group = todo.group
    siblings = [i for i in _todos_in(todolist, group) if i.pk != item.pk]
    if index is None or index > len(siblings):
        index = len(siblings)
    siblings.insert(index, item)

    if source.pk != todolist.pk:
        item.parent = todolist
        item.save(update_fields=["parent"])
    todo.group = group
    todo.save(update_fields=["group"])
    _renumber(siblings)
    if source.pk != todolist.pk or old_group != group:
        _renumber(list(_todos_in(source, old_group)))
    if source.pk != todolist.pk:
        visibility.recompute(item)
        record(
            actor=actor,
            action=Action.MOVED,
            project=item.project,
            item=item,
            to=todolist.title,
        )


@transaction.atomic
def move_group(group, *, index):
    """Moves a group with its to-dos as a block: only its position changes"""
    TodoList.objects.select_for_update().get(pk=group.todolist_id)
    groups = [g for g in group.todolist.groups.all() if g.pk != group.pk]
    groups.insert(min(index, len(groups)), group)
    for position, g in enumerate(groups, start=1):
        if g.position != position:
            Group.objects.filter(pk=g.pk).update(position=position)
            g.position = position


@transaction.atomic
def delete_group(group):
    """Its to-dos stay, ungrouped at the end"""
    todolist = TodoList.objects.select_for_update().get(pk=group.todolist_id)
    todos = list(_todos_in(todolist.item, group))
    Todo.objects.filter(group=group).update(group=None)
    ungrouped = list(
        _todos_in(todolist.item, None).exclude(pk__in=[t.pk for t in todos])
    )
    _renumber(ungrouped + todos)
    group.delete()


@transaction.atomic
def reorder(items):
    """Top-level items of one kind (e.g. the lists on the project page) in
    the given order"""
    _renumber(items)


@transaction.atomic
def move_item(item, *, parent, actor):
    """Moves a folder, doc (or another item) into another folder or to the
    top level, with its subtree; recomputes visibility"""
    item.parent = parent
    item.position = _next_position(
        Item.objects.filter(project=item.project, parent=parent, kind=item.kind)
    )
    if parent is not None:
        item.visible_to_clients = False
    item.save()
    visibility.recompute(item)
    record(actor=actor, action=Action.MOVED, project=item.project, item=item)


@transaction.atomic
def set_visibility(item, *, visible, actor):
    visibility.set_switch(item, visible=visible)
    record(
        actor=actor,
        action=Action.VISIBILITY_CHANGED,
        project=item.project,
        item=item,
        visible=visible,
    )


@transaction.atomic
def trash(item, *, actor):
    """Soft and recoverable; active descendants follow, and come back with
    it, those trashed earlier stay trashed"""
    item.status = Status.TRASHED
    item.trashed_at = timezone.now()
    item.save(update_fields=["status", "trashed_at"])
    Item.objects.filter(
        pk__in=list(Item.objects.descendants(item).values_list("pk", flat=True)),
        status=Status.ACTIVE,
    ).update(status=Status.TRASHED, trashed_at=item.trashed_at)
    record(actor=actor, action=Action.TRASHED, project=item.project, item=item)


@transaction.atomic
def restore(item, *, actor):
    Item.objects.filter(
        pk__in=list(
            Item.objects.descendants(item, include_self=True).values_list(
                "pk", flat=True
            )
        ),
        trashed_at=item.trashed_at,
    ).update(status=Status.ACTIVE, trashed_at=None)
    item.refresh_from_db()
    record(actor=actor, action=Action.RESTORED, project=item.project, item=item)
