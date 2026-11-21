"""Creating and changing items (specs/core.md)

Every change goes through here: it writes the item and its detail row
together, keeps positions and the stored visibility right, and records the
event and the subscriptions. Views, the API and imports call these, they
don't save items themselves.
"""

import datetime as dt

from django.db import transaction
from django.db.models import Exists, Max, OuterRef, Q
from django.db.models.functions import Lower
from django.utils import timezone

from biwak import schedules
from biwak.accounts.models import User
from biwak.activity import mentions
from biwak.activity.models import Action
from biwak.activity.notify import notify_people
from biwak.activity.operations import record, subscribe
from biwak.files import attachments
from biwak.files.models import FileVersion, content_type_for
from biwak.items import visibility
from biwak.items.models import (
    Comment,
    Doc,
    DocVersion,
    Folder,
    Group,
    Item,
    Kind,
    Message,
    Status,
    Todo,
    TodoList,
    Upload,
)
from biwak.projects import operations as project_ops
from biwak.projects.models import Membership


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
    return record(actor=creator, action=Action.CREATED, project=item.project, item=item)


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


def _recurrence_fields(recurrence, ends_on, count):
    """The validated recurrence fields of a to-do; without a rule neither an
    end date nor a count. Raises ``schedules.InvalidRule``."""
    rule = schedules.validate(recurrence) if recurrence else ""
    return {
        "recurrence": rule,
        "recurrence_ends_on": ends_on if rule else None,
        "recurrence_count": count if rule else None,
    }


def _todos_in(todolist_item, group):
    """The open to-dos of a list's group (or the ungrouped ones), in order;
    the list and the group as objects or IDs"""
    return Item.objects.filter(
        parent=todolist_item,
        kind=Kind.TODO,
        todo__group=group,
        todo__completed_at__isnull=True,
    ).exclude(status=Status.TRASHED)


@transaction.atomic
def create_todo(
    *,
    todolist,
    title,
    creator,
    group=None,
    notes="",
    due_on=None,
    assignees=(),
    recurrence="",
    recurrence_ends_on=None,
    recurrence_count=None,
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
    Todo.objects.create(
        item=item,
        group=group,
        notes=notes,
        due_on=due_on,
        **_recurrence_fields(recurrence, recurrence_ends_on, recurrence_count),
    )
    attachments.link(item, notes, actor=creator)
    event = _created(item, creator)
    mentions.update(item, f"{title}\n\n{notes}", actor=creator, event=event)
    if assignees:
        assign(item, assignees, actor=creator)
    return item


@transaction.atomic
def create_message(
    *,
    project,
    title,
    creator,
    content="",
    visible=False,
    category=None,
    whom="nobody",
):
    """``whom`` to notify: ``"everybody"``, a list of people or
    ``"nobody"`` (``notify_people()``, specs/files.md)"""
    item = _create_item(
        project=project,
        kind=Kind.MESSAGE,
        title=title,
        creator=creator,
        visible=visible,
    )
    Message.objects.create(item=item, content=content, category=category)
    attachments.link(item, content, actor=creator)
    event = _created(item, creator)
    mentions.update(item, f"{title}\n\n{content}", actor=creator, event=event)
    notify_people(item, whom=whom, actor=creator)
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
def create_doc(
    *,
    project,
    title,
    creator,
    parent=None,
    content="",
    visible=False,
    whom="nobody",
):
    item = _create_item(
        project=project,
        kind=Kind.DOC,
        title=title,
        creator=creator,
        parent=parent,
        visible=visible and parent is None,
    )
    Doc.objects.create(item=item, content=content)
    DocVersion.objects.create(
        doc_id=item.pk, title=title, content=content, created_by=creator
    )
    attachments.link(item, content, actor=creator)
    event = _created(item, creator)
    mentions.update(item, f"{title}\n\n{content}", actor=creator, event=event)
    notify_people(item, whom=whom, actor=creator)
    return item


def new_version(upload, file, *, uploaded_by):
    """Stores ``file`` (an uploaded file) as the newest version of the
    upload; raises ``attachments.UploadError`` for files over the limit"""
    name = attachments.clean_name(file.name)
    attachments.check_size(file)
    version = FileVersion(
        upload=upload,
        name=name,
        size=file.size,
        content_type=content_type_for(name),
        uploaded_by=uploaded_by,
    )
    version.file.save(name, file, save=False)
    version.save()
    return version


@transaction.atomic
def create_upload(
    *,
    project,
    file,
    creator,
    parent=None,
    description="",
    visible=False,
    whom="nobody",
):
    """Uploads a file into the root or a folder; its title is the file's
    name. Raises ``attachments.UploadError`` for files over the limit."""
    attachments.check_size(file)
    item = _create_item(
        project=project,
        kind=Kind.FILE,
        title=attachments.clean_name(file.name),
        creator=creator,
        parent=parent,
        visible=visible and parent is None,
    )
    upload = Upload.objects.create(item=item, description=description)
    new_version(upload, file, uploaded_by=creator)
    attachments.link(item, description, actor=creator)
    event = _created(item, creator)
    mentions.update(item, f"{item.title}\n\n{description}", actor=creator, event=event)
    notify_people(item, whom=whom, actor=creator)
    return item


@transaction.atomic
def add_comment(item, *, author, content):
    comment = Comment.objects.create(item=item, author=author, content=content)
    attachments.link(item, content, actor=author)
    subscribe(author, item, explicit=False)
    event = record(
        actor=author,
        action=Action.COMMENTED,
        project=item.project,
        item=item,
        comment=comment.pk,
    )
    mentions.update(item, content, comment=comment, actor=author, event=event)
    return comment


def assignable_people(item, by=None):
    """Who can be assigned to the to-do: the active people who can see it
    (specs/access.md, specs/todos.md), the project's members first. Staff
    of all-access projects whether they're members or not (assigning makes
    them members), clients only members and only on visible to-dos. The
    one rule for the forms, the API and the next to-do of a recurring
    one. Clients (``by``) assign members only: they don't learn about other
    staff."""
    project = item.project
    members = Q(memberships__project=project)
    everybody = project.is_all_access and not (by and by.is_client)
    staff = Q(is_client=False) & (Q() if everybody else members)
    who = staff | (Q(is_client=True) & members) if item.is_client_visible else staff
    return (
        User.objects
        .active()
        .filter(who)
        .distinct()
        .annotate(
            is_member=Exists(
                Membership.objects.filter(project=project, user=OuterRef("pk"))
            )
        )
        .order_by("-is_member", Lower("full_name"), "email")
    )


def _assignable(item, by=None):
    """``{pk: is_member}`` of ``assignable_people()``, with the stored
    visibility, not what the object knew when it was loaded"""
    item.refresh_from_db(fields=["is_client_visible"])
    return dict(assignable_people(item, by).values_list("pk", "is_member"))


@transaction.atomic
def assign(item, users, *, actor):
    """Adds assignees (``assignable_people()``, ``ValueError`` for anybody
    else); staff who aren't members yet become members, recorded as added
    (decided 2026-11-21). Returns those newly assigned."""
    todo = item.todo
    users = [u for u in users if not todo.assignees.filter(pk=u.pk).exists()]
    allowed = _assignable(item, actor) if users else {}
    for user in users:
        if user.pk not in allowed:
            raise ValueError(f"{user} can't be assigned to {item}")
    for user in users:
        if not allowed[user.pk]:
            project_ops.add_member(item.project, user, actor=actor)
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


_UNCHANGED = object()


@transaction.atomic
def update_todo(
    item,
    *,
    actor,
    title=_UNCHANGED,
    notes=_UNCHANGED,
    due_on=_UNCHANGED,
    assignees=_UNCHANGED,
    recurrence=_UNCHANGED,
    recurrence_ends_on=_UNCHANGED,
    recurrence_count=_UNCHANGED,
):
    """Changes what's given (the to-do's page and the API); assignees are
    the complete new set. Removing the recurrence removes its end and
    count too."""
    todo = item.todo
    previous = f"{item.title}\n\n{todo.notes}"
    edited = False
    if title is not _UNCHANGED and title != item.title:
        item.title = title
        item.updated_at = timezone.now()
        item.save(update_fields=["title", "updated_at"])
        edited = True
    fields = []
    if notes is not _UNCHANGED and notes != todo.notes:
        todo.notes = notes
        fields.append("notes")
        attachments.link(item, notes, actor=actor)
    if due_on is not _UNCHANGED and due_on != todo.due_on:
        todo.due_on = due_on
        fields.append("due_on")
    given = {
        "recurrence": recurrence,
        "recurrence_ends_on": recurrence_ends_on,
        "recurrence_count": recurrence_count,
    }
    if any(value is not _UNCHANGED for value in given.values()):
        merged = {
            name: getattr(todo, name) if value is _UNCHANGED else value
            for name, value in given.items()
        }
        for name, value in _recurrence_fields(*merged.values()).items():
            if getattr(todo, name) != value:
                setattr(todo, name, value)
                fields.append(name)
    if fields:
        todo.save(update_fields=fields)
    if edited or fields:
        # Edits merge into one event per editing session (record())
        event = record(
            actor=actor, action=Action.EDITED, project=item.project, item=item
        )
        mentions.update(
            item,
            f"{item.title}\n\n{todo.notes}",
            actor=actor,
            event=event,
            previous=previous,
        )
    if assignees is not _UNCHANGED:
        new, old = set(assignees), set(todo.assignees.all())
        assign(item, list(new - old), actor=actor)
        unassign(item, list(old - new), actor=actor)
    return item


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
    if todo.recurrence:
        _create_next(item, todo, actor=actor)


def _create_next(item, todo, *, actor):
    """The next to-do of a recurring one: same list and group, at the end,
    same title, notes, assignees, subscribers and rule, due on the rule's
    next date after today, or after the due date when completed early
    (specs/todos.md). None when the count or the end
    date is used up, or one was made from this to-do already (reopening
    and completing again)."""
    if todo.recurrence_count is not None and todo.recurrence_count <= 0:
        return None
    # After the due date when completed early: a weekly to-do due Friday
    # and done on Wednesday is next due the Friday after
    after = max(filter(None, [schedules.today(), todo.due_on]))
    due_on = schedules.next_date(todo.recurrence, after, anchor=todo.due_on)
    if due_on is None or (
        todo.recurrence_ends_on is not None and due_on > todo.recurrence_ends_on
    ):
        return None
    if item.following.exclude(item__status=Status.TRASHED).exists():
        return None
    todolist = item.parent
    TodoList.objects.select_for_update().get(item=todolist)
    following = Item(
        project=item.project,
        parent=todolist,
        kind=Kind.TODO,
        title=item.title,
        creator=item.creator,
        position=_next_position(_todos_in(todolist, todo.group)),
    )
    following.save()
    visibility.recompute(following)
    Todo.objects.create(
        item=following,
        group=todo.group,
        notes=todo.notes,
        due_on=due_on,
        recurrence=todo.recurrence,
        recurrence_ends_on=todo.recurrence_ends_on,
        recurrence_count=None
        if todo.recurrence_count is None
        else todo.recurrence_count - 1,
        previous=item,
    )
    for subscription in item.subscriptions.select_related("user"):
        if subscription.user.is_active:
            subscribe(subscription.user, following, added_by=subscription.added_by)
    record(actor=actor, action=Action.CREATED, project=item.project, item=following)
    # Assignees removed from the project since aren't brought back
    allowed = _assignable(following)
    people = [u for u in todo.assignees.all() if allowed.get(u.pk)]
    if people:
        assign(following, people, actor=actor)
    return following


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
    None: at the end), see ``move_todos()``"""
    move_todos([item], todolist=todolist, group=group, index=index, actor=actor)


@transaction.atomic
def move_todos(items, *, todolist, group=None, index=None, actor):
    """Moves to-dos together (dragging several at once) into a list's group
    (or ungrouped), next to each other in the given order, starting at
    ``index`` among the others there (0-based, None: at the end). Locks the
    lists, so concurrent moves don't mix up positions. Moving into another
    list recomputes the visibility. Raises ``ValueError`` for a to-do given
    twice."""
    if not items:
        return
    if len({i.pk for i in items}) != len(items):
        raise ValueError("A to-do can't be moved twice at once")
    sources = {(i.parent_id, i.todo.group_id) for i in items}
    lists = sorted({todolist.pk} | {list_id for list_id, _group in sources})
    list(TodoList.objects.select_for_update().filter(item__in=lists).order_by("pk"))
    if group is not None and group.todolist_id != todolist.pk:
        raise ValueError("The group belongs to another list")
    if any(i.project_id != todolist.project_id for i in items):
        raise ValueError("Moving to-dos between projects isn't possible")

    moved = {i.pk for i in items}
    siblings = [i for i in _todos_in(todolist, group) if i.pk not in moved]
    if index is None or index > len(siblings):
        index = len(siblings)
    index = max(0, index)
    siblings[index:index] = items

    for item in items:
        changed_list = item.parent_id != todolist.pk
        if changed_list:
            item.parent = todolist
            item.save(update_fields=["parent"])
        changed_group = item.todo.group_id != (group.pk if group else None)
        if changed_group:
            item.todo.group = group
            item.todo.save(update_fields=["group"])
        if changed_group and not changed_list:
            # A board column; merged like edits (record())
            record(
                actor=actor,
                action=Action.MOVED,
                project=item.project,
                item=item,
                group=group.title if group else "",
                list=todolist.title,
            )
        if changed_list:
            visibility.recompute(item)
            record(
                actor=actor,
                action=Action.MOVED,
                project=item.project,
                item=item,
                to=todolist.title,
            )
    _renumber(siblings)
    for list_id, group_id in sources:
        if (list_id, group_id) != (todolist.pk, group.pk if group else None):
            _renumber(list(_todos_in(list_id, group_id)))


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
    """Moves a folder, doc or file (or another item) into another folder or
    to the top level, with its subtree; recomputes visibility. A folder
    can't go into itself or what's in it."""
    if parent is not None and (
        parent.pk == item.pk
        or Item.objects.descendants(item).filter(pk=parent.pk).exists()
    ):
        raise ValueError("A folder can't be moved into itself")
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
    it, those trashed earlier stay trashed. An archived item comes back
    archived."""
    item.archived_when_trashed = item.status == Status.ARCHIVED
    item.status = Status.TRASHED
    item.trashed_at = timezone.now()
    item.save(update_fields=["status", "trashed_at", "archived_when_trashed"])
    Item.objects.filter(
        pk__in=list(Item.objects.descendants(item).values_list("pk", flat=True)),
        status=Status.ACTIVE,
    ).update(status=Status.TRASHED, trashed_at=item.trashed_at)
    record(actor=actor, action=Action.TRASHED, project=item.project, item=item)


@transaction.atomic
def restore(item, *, actor):
    if item.status != Status.TRASHED:
        raise ValueError("The item isn't in the trash")
    if item.parent_id and item.parent.status == Status.TRASHED:
        raise ValueError("Restore the parent first")
    Item.objects.filter(
        pk__in=list(Item.objects.descendants(item).values_list("pk", flat=True)),
        trashed_at=item.trashed_at,
    ).update(status=Status.ACTIVE, trashed_at=None)
    item.status = Status.ARCHIVED if item.archived_when_trashed else Status.ACTIVE
    item.trashed_at = None
    item.archived_when_trashed = False
    item.save(update_fields=["status", "trashed_at", "archived_when_trashed"])
    item.refresh_from_db()
    record(actor=actor, action=Action.RESTORED, project=item.project, item=item)


# Changing, archiving and the trash (specs/core.md) -----------------------

# Trashed items are deleted for good after this (fairy_tasks)
TRASH_DAYS = 30


# What clients create where they can see (specs/access.md, decided
# 2026-11-20); comments too. Everything else is staff only.
CLIENTS_CREATE = {Kind.TODO, Kind.MESSAGE, Kind.ANSWER}


def can_create(user, kind):
    return not user.is_client or kind in CLIENTS_CREATE


def can_change(user, item):
    """Staff change everything they see; clients what they created
    (renaming, archiving, trashing; to-dos' fields stay open to everybody
    who sees them)"""
    return not user.is_client or item.creator_id == user.pk


@transaction.atomic
def update_list(
    item, *, actor, title=_UNCHANGED, description=_UNCHANGED, view=_UNCHANGED
):
    todolist = item.todolist
    if title is not _UNCHANGED and title != item.title:
        item.title = title
        item.updated_at = timezone.now()
        item.save(update_fields=["title", "updated_at"])
    fields = []
    if description is not _UNCHANGED:
        todolist.description = description
        fields.append("description")
    if view is not _UNCHANGED:
        todolist.view = view
        fields.append("view")
    if fields:
        todolist.save(update_fields=fields)
    record(actor=actor, action=Action.EDITED, project=item.project, item=item)
    return item


@transaction.atomic
def archive(item, *, actor):
    """Readable, but out of the way (lists, later folders and messages);
    archiving an archived item again changes nothing (a double submit)"""
    if item.status == Status.ARCHIVED:
        return
    if item.status != Status.ACTIVE:
        raise ValueError("Only active items can be archived")
    item.status = Status.ARCHIVED
    item.save(update_fields=["status"])
    record(actor=actor, action=Action.ARCHIVED, project=item.project, item=item)


@transaction.atomic
def unarchive(item, *, actor):
    if item.status == Status.ACTIVE:
        return
    if item.status != Status.ARCHIVED:
        raise ValueError("The item isn't archived")
    item.status = Status.ACTIVE
    item.save(update_fields=["status"])
    record(actor=actor, action=Action.UNARCHIVED, project=item.project, item=item)


@transaction.atomic
def rename_group(group, *, title):
    group.title = title
    group.save(update_fields=["title"])


def trashed_roots(items):
    """The trashed items to show in the trash: those whose parent isn't
    trashed too (the parent's restore brings them back)"""
    return (
        items
        .filter(status=Status.TRASHED)
        .exclude(parent__status=Status.TRASHED)
        .order_by("-trashed_at", "-pk")
    )


def purge_trash(*, now=None):
    """Deletes items trashed more than TRASH_DAYS ago, with their subtree,
    comments and events (cascading); returns how many trashed items were
    deleted for good"""
    cutoff = (now or timezone.now()) - dt.timedelta(days=TRASH_DAYS)
    old = Item.objects.filter(status=Status.TRASHED, trashed_at__lt=cutoff)
    count = old.count()
    # Roots first is enough: children cascade
    for item in old.exclude(parent__in=old).order_by("pk"):
        item.delete()
    return count
