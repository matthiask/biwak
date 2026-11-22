"""Creating and changing items (specs/core.md)

Every change goes through here: it writes the item and its detail row
together, keeps positions and the stored visibility right, and records the
event and the subscriptions. Views, the API and imports call these, they
don't save items themselves.
"""

import datetime as dt
import uuid

from django.core.exceptions import PermissionDenied
from django.core.files import File
from django.db import transaction
from django.db.models import Exists, F, Max, OuterRef, Q, TextChoices
from django.db.models.functions import Lower
from django.utils import timezone
from django.utils.translation import gettext, gettext_lazy as _, ngettext

from biwak import checklists, schedules
from biwak.accounts.models import User, own_staff
from biwak.activity import mentions
from biwak.activity.models import Action, Event, Subscription
from biwak.activity.notify import notify_people
from biwak.activity.operations import (
    is_importing,
    read_by_acting,
    record,
    subscribe,
)
from biwak.files import attachments
from biwak.files.models import (
    REFERENCE,
    Attachment,
    FileVersion,
    content_type_for,
    new_key,
)
from biwak.files.titles import doc_title, with_heading
from biwak.items import editing, visibility
from biwak.items.models import (
    Assignment,
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
from biwak.live import announce as live
from biwak.projects import operations as project_ops
from biwak.projects.models import Membership, knows_people_of
from biwak.public_links.operations import end_links
from biwak.text import line_breaks


def _next_position(qs):
    return (qs.aggregate(m=Max("position"))["m"] or 0) + 1


def create_item(
    *,
    project,
    kind,
    title,
    creator,
    parent=None,
    visible=False,
    position=None,
    draft=False,
):
    """The item of a new item with its stored visibility, for the
    ``create_*`` operations (of every app), which add the detail model and
    record the event (``created()``). ``position``: at the end of its
    siblings of the same kind unless given."""
    if position is None:
        siblings = Item.objects.filter(project=project, parent=parent, kind=kind)
        position = _next_position(siblings)
    item = Item(
        project=project,
        parent=parent,
        kind=kind,
        title=title,
        creator=creator,
        position=position,
        visible_to_clients=visible,
        is_draft=draft,
    )
    item.save()
    visibility.recompute(item)
    return item


def created(item, creator, **data):
    """The creator subscribed and the event recorded (returned), with
    ``data`` (a ``batch`` of files uploaded together). Not for folders:
    creating one is housekeeping, and following a folder brings every new
    file whatever the level (decided 2026-11-22, specs/notifications.md)"""
    if item.kind != Kind.FOLDER:
        subscribe(creator, item)
    return record(
        actor=creator, action=Action.CREATED, project=item.project, item=item, **data
    )


@transaction.atomic
def create_list(*, project, title, creator, description="", visible=False):
    item = create_item(
        project=project, kind=Kind.LIST, title=title, creator=creator, visible=visible
    )
    TodoList.objects.create(item=item, description=description)
    created(item, creator)
    return item


@transaction.atomic
def create_group(*, todolist, title):
    live.changed(todolist.item, action="grouped")
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


class InvalidDates(ValueError):
    """A start date without a due date or after it (specs/start-dates.md);
    the message says which"""


def check_dates(starts_on, due_on):
    """Raises ``InvalidDates`` unless ``starts_on`` is empty, or there's a
    due date and it isn't before the start: the one rule for the forms, the
    API and the operations"""
    if starts_on is None:
        return
    if due_on is None:
        raise InvalidDates(gettext("A start date needs a due date."))
    if starts_on > due_on:
        raise InvalidDates(gettext("The start date can't be after the due date."))


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
    starts_on=None,
    assignees=(),
    recurrence="",
    recurrence_ends_on=None,
    recurrence_count=None,
):
    """``todolist`` is the list's item; ``InvalidDates`` for a start date
    without a due date or after it"""
    check_dates(starts_on, due_on)
    TodoList.objects.select_for_update().get(item=todolist)
    if group is not None and group.todolist_id != todolist.pk:
        raise ValueError("The group belongs to another list")
    item = create_item(
        project=todolist.project,
        parent=todolist,
        kind=Kind.TODO,
        title=title,
        creator=creator,
        position=_next_position(_todos_in(todolist, group)),
    )
    Todo.objects.create(
        item=item,
        group=group,
        notes=notes,
        starts_on=starts_on,
        due_on=due_on,
        **_recurrence_fields(recurrence, recurrence_ends_on, recurrence_count),
    )
    attachments.link(item, notes, actor=creator)
    event = created(item, creator)
    mentioned = mentions.update(item, f"{title}\n\n{notes}", actor=creator, event=event)
    if assignees:
        assign(item, assignees, actor=creator, mentioned=(event, mentioned))
    return item


def message_visibility(creator, visible):
    """What clients post is visible to clients (specs/access.md)"""
    return bool(visible) or creator.is_client


@transaction.atomic
def create_message(
    *,
    project,
    title,
    creator,
    content="",
    visible=False,
    category=None,
    also=(),
):
    """Tells those told by default and ``also`` these people
    (``notify_people()``, specs/notifications.md)"""
    item = create_item(
        project=project,
        kind=Kind.MESSAGE,
        title=title,
        creator=creator,
        visible=message_visibility(creator, visible),
    )
    Message.objects.create(item=item, content=content, category=category)
    attachments.link(item, content, actor=creator)
    event = created(item, creator)
    mentions.update(item, f"{title}\n\n{content}", actor=creator, event=event)
    notify_people(item, actor=creator, also=also)
    return item


@transaction.atomic
def create_folder(*, project, title, creator, parent=None, visible=False, color=""):
    item = create_item(
        project=project,
        kind=Kind.FOLDER,
        title=title,
        creator=creator,
        parent=parent,
        visible=visible and parent is None,
    )
    Folder.objects.create(item=item, color=color)
    created(item, creator)
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
    also=(),
):
    """``content`` follows the heading made of ``title``: the doc's text
    starts with ``# title`` and its title is that first line
    (specs/doc-titles.md)"""
    content = with_heading(title, content)
    title = doc_title(content)
    item = create_item(
        project=project,
        kind=Kind.DOC,
        title=title,
        creator=creator,
        parent=parent,
        visible=visible and parent is None,
    )
    # The live editor counts a line break as one character (biwak/text.py)
    content = line_breaks(content)
    Doc.objects.create(item=item, content=content)
    DocVersion.objects.create(
        doc_id=item.pk, title=title, content=content, created_by=creator
    )
    attachments.link(item, content, actor=creator)
    event = created(item, creator)
    mentions.update(item, f"{title}\n\n{content}", actor=creator, event=event)
    notify_people(item, actor=creator, also=also)
    return item


# A draft has nothing beyond headings' "#"s (``is_blank()``)
DRAFT_TEXT = "# "


def is_blank(content):
    """Whether a draft's text is still nothing but ``# ``"""
    return not content.replace("#", "").strip()


@transaction.atomic
def create_draft(*, project, creator, parent=None):
    """ "New doc": a doc to write in at once, the editor needs one to sync
    (specs/files.md, "Docs"). Nobody's business until it has text
    beyond ``# `` (``files.operations._save()`` makes it a doc then): no
    event, only its creator sees it, its creator the only subscriber.
    Internal at the top level, in a folder as the folder says."""
    item = create_item(
        project=project,
        kind=Kind.DOC,
        title=doc_title(DRAFT_TEXT),
        creator=creator,
        parent=parent,
        draft=True,
    )
    Doc.objects.create(item=item, content=DRAFT_TEXT, tell_pending=True)
    subscribe(creator, item)
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
    attachments.store(version.file, name, file)
    version.save()
    return version


@attachments.cleans_up_files
@transaction.atomic
def create_upload(
    *,
    project,
    file,
    creator,
    parent=None,
    description="",
    visible=False,
    also=(),
    title=None,
    batch=None,
    more=False,
):
    """Uploads a file into the root or a folder; its title is the file's
    name unless ``title`` is given. ``batch``: files uploaded together
    share it on their events, which the lantern and the mails merge into
    one entry (specs/files.md, "Uploading files"); ``more``: more files
    of the batch follow, its mail waits for them. Raises
    ``attachments.UploadError`` for files over the limit."""
    attachments.check_size(file)
    item = create_item(
        project=project,
        kind=Kind.FILE,
        title=title or attachments.clean_name(file.name),
        creator=creator,
        parent=parent,
        visible=visible and parent is None,
    )
    upload = Upload.objects.create(item=item, description=description)
    new_version(upload, file, uploaded_by=creator)
    attachments.link(item, description, actor=creator)
    data = {"batch": batch} if batch else {}
    if batch and more:
        data["more"] = True
    event = created(item, creator, **data)
    mentions.update(item, f"{item.title}\n\n{description}", actor=creator, event=event)
    notify_people(item, actor=creator, also=also)
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
    read_by_acting(author, item)
    return comment


class ChecklistConflict(Exception):
    """The text changed since the page showed it; ``who`` changed it last
    (None if unknown), at ``when``"""

    def __init__(self, who=None, when=None):
        super().__init__(f"{who} changed it at {when}")
        self.who = who
        self.when = when


def can_tick(user, item):
    """Whoever may change the text; to-dos are shared work, so everybody
    who sees one (specs/access.md). Nobody in read-only docs
    (specs/collaboration.md)."""
    if item.kind == Kind.DOC and item.doc.read_only:
        return False
    return item.kind == Kind.TODO or can_change(user, item)


# Where each kind keeps the text that may have a task list: the name of the
# detail row (``Detail``'s related name) and the field
TEXT_FIELDS = {
    Kind.TODO: ("todo", "notes"),
    Kind.MESSAGE: ("message", "content"),
    Kind.DOC: ("doc", "content"),
    Kind.FILE: ("upload", "description"),
    Kind.ANSWER: ("answer", "content"),
}


def text_of(item):
    """The text of an item that may have a task list; its hash is the
    version a page sends back when ticking"""
    if item.kind not in TEXT_FIELDS:
        return ""
    name, field = TEXT_FIELDS[item.kind]
    return getattr(getattr(item, name), field)


@transaction.atomic
def tick(item, *, actor, index, version, comment=None, checked=None):
    """Toggles checkbox ``index`` of the item's text (or of ``comment``, one
    of its comments) through the operation that edits it, so it's an edit
    like any other. ``version`` is ``checklists.text_hash()`` of the text
    the person saw: ``ChecklistConflict`` if it changed since,
    ``editing.BeingEdited`` while anybody has the item's edit form open (the
    person's own too; docs never wait, their editors are live), ``PermissionDenied`` unless they may change that text,
    ``checklists.NoCheckbox`` if there's no such box. Returns the new text."""
    from biwak.checkins import operations as checkin_ops
    from biwak.files import operations as file_ops

    if comment is not None:
        comment = Comment.objects.select_for_update().get(pk=comment.pk, item=item)
        if actor.is_client and comment.author_id != actor.pk:
            raise PermissionDenied
        if checklists.text_hash(comment.content) != version:
            raise ChecklistConflict(comment.author, comment.updated_at)
        comment.content = checklists.tick(comment.content, index, checked)
        comment.updated_at = timezone.now()
        comment.save(update_fields=["content", "updated_at"])
        read_by_acting(actor, item)
        return comment.content
    if not can_tick(actor, item):
        raise PermissionDenied
    if item.kind not in TEXT_FIELDS:
        raise checklists.NoCheckbox(index)
    # Lock the detail row, so that two ticks can't both be based on one text
    name = TEXT_FIELDS[item.kind][0]
    getattr(item, name).__class__.objects.select_for_update().get(item=item)
    item = Item.objects.select_related(name).get(pk=item.pk)
    if item.kind == Kind.DOC:
        # Docs are edited live: ticks go into the open editors
        # (specs/editor.md, "Docs: ticks never wait")
        text = file_ops.tick_doc(
            item, actor=actor, index=index, version=version, checked=checked
        )
        read_by_acting(actor, item)
        return text
    if users := editing.holders(item):
        raise editing.BeingEdited(users)
    text = text_of(item)
    if checklists.text_hash(text) != version:
        raise ChecklistConflict(*editing.last_change(item))
    new = checklists.tick(text, index, checked)
    match item.kind:
        case Kind.TODO:
            update_todo(item, actor=actor, notes=new)
        case Kind.MESSAGE:
            file_ops.update_message(item, actor=actor, content=new)
        case Kind.FILE:
            file_ops.update_upload(item, actor=actor, description=new)
        case Kind.ANSWER:
            checkin_ops.update_answer(item.answer, new, actor=actor)
    read_by_acting(actor, item)
    return new


def assignable_people(item, by=None):
    """Who can be assigned to the to-do: the active people who can see it
    (specs/access.md, specs/todos.md), the project's members first. Staff
    of all-access projects whether they're members or not (assigning makes
    them members), clients only members and only on visible to-dos. The
    one rule for the forms, the API and the next to-do of a recurring
    one. Externals of all-access projects only as members (specs/access.md).
    Clients (``by``) assign members only: they don't learn about other
    staff; externals in the project know its people (decided 2026-11-21).
    """
    project = item.project
    members = Q(memberships__project=project)
    # Clients (``by``) don't learn about others than members; the importer
    # assigns as in Basecamp, also for a creator who's an external now
    everybody = project.is_all_access and (
        by is None or knows_people_of(by, project) or is_importing()
    )
    staff = Q(is_client=False) & members
    if everybody:
        # Own staff; externals only as members
        staff |= own_staff()
    who = staff | (Q(is_client=True) & members) if item.is_client_visible else staff
    # Inactive people only while importing (they have no account yet)
    people = User.objects.all() if is_importing() else User.objects.active()
    return _members_first(people.filter(who).distinct(), project)


def _members_first(people, project):
    return people.annotate(
        is_member=Exists(
            Membership.objects.filter(project=project, user=OuterRef("pk"))
        )
    ).order_by("-is_member", Lower("full_name"), "email")


def assignable_or_assigned(item, by=None):
    """``assignable_people()`` and those assigned already who aren't (a
    client on a to-do made internal): the to-do's edit form offers them, so
    saving never drops anybody silently"""
    assignable = assignable_people(item, by)
    assigned = item.todo.assignees.exclude(pk__in=assignable.values("pk"))
    if not assigned.exists():
        return assignable
    return _members_first(
        User.objects.filter(
            Q(pk__in=assignable.values("pk")) | Q(pk__in=assigned.values("pk"))
        ),
        item.project,
    )


def _assignable(item, by=None):
    """``{pk: is_member}`` of ``assignable_people()``, with the stored
    visibility, not what the object knew when it was loaded"""
    item.refresh_from_db(fields=["is_client_visible"])
    return dict(assignable_people(item, by).values_list("pk", "is_member"))


@transaction.atomic
def assign(item, users, *, actor, mentioned=None, assigned_by=None, batch=None):
    """Adds assignees (``assignable_people()``, ``ValueError`` for anybody
    else); staff who aren't members yet become members, recorded as added
    (decided 2026-11-21). Returns those newly assigned.

    ``mentioned``: ``(event, people)``, the event of the same change and
    those it newly mentions (what ``mentions.update()`` returned). Those
    both assigned and mentioned get one notification, the assignment's
    (decided 2026-11-21): the assignment event says it mentions them, the
    other event stops telling them (``notify.candidates()``).

    ``assigned_by`` is who gets stored as the assigner: the actor by
    default, or ``{user pk: assigner or None}`` to say otherwise (the next
    to-do of a repeating one keeps the assigners, the importer leaves them
    empty; decided 2026-11-21).

    ``batch``: the to-dos of one "Assign…" share it on their events, which
    the lantern and the mails merge into one entry per person told
    (specs/handover.md)."""
    todo = item.todo
    users = [u for u in users if not todo.assignees.filter(pk=u.pk).exists()]
    allowed = _assignable(item, actor) if users else {}
    for user in users:
        if user.pk not in allowed:
            raise ValueError(f"{user} can't be assigned to {item}")
    for user in users:
        if not allowed[user.pk]:
            project_ops.add_member(item.project, user, actor=actor)
    for user in users:
        by = actor if assigned_by is None else assigned_by.get(user.pk)
        todo.assignees.add(user, through_defaults={"assigned_by": by})
    for user in users:
        subscribe(user, item, added_by=actor)
    if users:
        both = set()
        if mentioned is not None:
            event, people = mentioned
            both = {u.pk for u in users} & {u.pk for u in people}
        extra = {"mentioned": sorted(both)} if both else {}
        if batch:
            extra["batch"] = batch
        record(
            actor=actor,
            action=Action.ASSIGNED,
            project=item.project,
            item=item,
            assignees=[u.pk for u in users],
            **extra,
        )
        if both:
            left = set(event.data.get("mentioned", ())) - both
            event.data["mentioned"] = sorted(left)
            if not left:
                del event.data["mentioned"]
            event.data["assigned"] = sorted(set(event.data.get("assigned", ())) | both)
            event.save(update_fields=["data"])
    return users


def assignable_to_all(items, by=None):
    """The people who can be assigned to every one of the to-dos
    (``assignable_people()`` of each), the members first when they're all
    in one project; for "Assign…" (specs/handover.md). A query per project
    and visibility, not per to-do."""
    common = None
    seen = set()
    for item in items:
        key = (item.project_id, item.is_client_visible)
        if key in seen:
            continue
        seen.add(key)
        pks = set(assignable_people(item, by).values_list("pk", flat=True))
        common = pks if common is None else common & pks
    people = User.objects.filter(pk__in=common or ())
    projects = {item.project_id for item in items}
    if len(projects) == 1:
        return _members_first(people, items[0].project)
    return people.order_by(Lower("full_name"), "email")


class AssignRefused(ValueError):
    """Assigning several to-dos at once changed nothing: somebody can't be
    assigned to some of them"""


@transaction.atomic
def assign_todos(items, users, *, actor, replace=False):
    """ "Assign…" for several to-dos (specs/handover.md): adds ``users`` to
    each to-do, or with ``replace`` makes them its only assignees (those
    taken out are recorded, nobody is told). One ``assign()`` and
    ``unassign()`` per to-do, so an event each; a new assignee is told
    once for all of them (their events share a ``batch``). All or nothing:
    ``AssignRefused`` when somebody can't be assigned to one of them.
    Returns ``{item: [newly assigned]}``."""
    items = list(items)
    users = list(users)
    allowed = {}
    refused = {}
    for item in items:
        item.refresh_from_db(fields=["is_client_visible"])
        key = (item.project_id, item.is_client_visible)
        if key not in allowed:
            allowed[key] = set(
                assignable_people(item, actor).values_list("pk", flat=True)
            )
        for user in users:
            if (
                user.pk not in allowed[key]
                and not item.todo.assignees.filter(pk=user.pk).exists()
            ):
                refused.setdefault(user, []).append(item)
    if refused:
        raise AssignRefused(
            " ".join(
                ngettext(
                    "%(person)s can't be assigned to %(count)s of the to-dos.",
                    "%(person)s can't be assigned to %(count)s of the to-dos.",
                    len(todos),
                )
                % {"person": user, "count": len(todos)}
                for user, todos in sorted(refused.items(), key=lambda r: str(r[0]))
            )
        )
    batch = uuid.uuid4().hex if len(items) > 1 else None
    done = {}
    keep = {user.pk for user in users}
    for item in items:
        if replace:
            unassign(
                item,
                [u for u in item.todo.assignees.all() if u.pk not in keep],
                actor=actor,
            )
        done[item] = assign(item, users, actor=actor, batch=batch)
    return done


@transaction.atomic
def unassign(item, users, *, actor):
    """Removes assignees; those who were assigned are recorded
    (``UNASSIGNED``, "Ada removed Bob" on the timeline, nobody is told)"""
    todo = item.todo
    removed = [u for u in users if todo.assignees.filter(pk=u.pk).exists()]
    if not removed:
        return []
    todo.assignees.remove(*removed)
    record(
        actor=actor,
        action=Action.UNASSIGNED,
        project=item.project,
        item=item,
        assignees=[u.pk for u in removed],
    )
    return removed


def unassign_dropped(user, *, actor, project=None):
    """Takes the person off the open to-dos (trashed ones too) of
    ``project``, or of every project: removed from the project (decided
    2026-11-21, specs/todos.md; deactivating keeps them since 2026-11-22,
    specs/handover.md). Through ``unassign()``,
    so the history shows it and nobody is told; completed to-dos are
    history and keep them."""
    items = Item.objects.filter(
        kind=Kind.TODO,
        todo__assignees=user,
        todo__completed_at__isnull=True,
    ).order_by("pk")
    if project is not None:
        items = items.filter(project=project)
    for item in items.select_related("todo", "project"):
        unassign(item, [user], actor=actor)


_UNCHANGED = object()


def _set_dates(todo, due_on, starts_on):
    """Sets the dates given (``_UNCHANGED`` keeps one; no due date, no
    start date), the fields changed; ``InvalidDates`` (in the transaction
    of the change, so nothing is saved)"""
    due_on = todo.due_on if due_on is _UNCHANGED else due_on
    if starts_on is _UNCHANGED:
        starts_on = todo.starts_on if due_on is not None else None
    check_dates(starts_on, due_on)
    changed = []
    for name, value in [("due_on", due_on), ("starts_on", starts_on)]:
        if getattr(todo, name) != value:
            setattr(todo, name, value)
            changed.append(name)
    return changed


@transaction.atomic
def update_todo(
    item,
    *,
    actor,
    title=_UNCHANGED,
    notes=_UNCHANGED,
    due_on=_UNCHANGED,
    starts_on=_UNCHANGED,
    assignees=_UNCHANGED,
    recurrence=_UNCHANGED,
    recurrence_ends_on=_UNCHANGED,
    recurrence_count=_UNCHANGED,
    base=None,
):
    """Changes what's given (the to-do's page and the API); assignees are
    the complete new set. Removing the recurrence removes its end and
    count too, removing the due date its start date (``InvalidDates`` for
    a start date without a due date or after it). ``base``: the
    ``editing.version()`` the form carried, so ``editing.StaleEdit`` if
    somebody saved since. Saving ends one's editing."""
    Todo.objects.select_for_update().get(item=item)
    editing.check_base(item, base, actor=actor)
    editing.stop(item, actor)
    todo = Todo.objects.get(item=item)
    item.todo = todo
    previous = f"{item.title}\n\n{todo.notes}"
    title_was, due_was, starts_was = item.title, todo.due_on, todo.starts_on
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
    fields += _set_dates(todo, due_on, starts_on)
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
        # Edits merge into one event per editing session (record()); what
        # changed and the new title and due date, for the timeline
        # (specs/timeline.md)
        changed = (["title"] if edited else []) + [
            "recurrence" if name.startswith("recurrence") else name for name in fields
        ]
        extra = {"fields": list(dict.fromkeys(changed))}
        # What it was before, so the timeline can tell a change which
        # went back (the first one stays when edits merge, record())
        if edited:
            extra["title_was"] = title_was
        if {"due_on", "starts_on"} & set(fields):
            # Both dates, what they are and were (specs/start-dates.md)
            for name, value in [
                ("due_on", todo.due_on),
                ("due_was", due_was),
                ("starts_on", todo.starts_on),
                ("starts_was", starts_was),
            ]:
                extra[name] = value.isoformat() if value else None
        event = record(
            actor=actor,
            action=Action.EDITED,
            project=item.project,
            item=item,
            **extra,
        )
        mentioned = mentions.update(
            item,
            f"{item.title}\n\n{todo.notes}",
            actor=actor,
            event=event,
            previous=previous,
        )
    if assignees is not _UNCHANGED:
        new, old = set(assignees), set(todo.assignees.all())
        assign(
            item,
            list(new - old),
            actor=actor,
            mentioned=(event, mentioned) if edited or fields else None,
        )
        unassign(item, list(old - new), actor=actor)
    if edited or fields or (assignees is not _UNCHANGED and new != old):
        read_by_acting(actor, item)
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
    read_by_acting(actor, item)


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
    # The same distance between start and due date (specs/start-dates.md)
    starts_on = None
    if todo.starts_on and todo.due_on:
        starts_on = due_on - (todo.due_on - todo.starts_on)
    if item.following.exclude(item__status=Status.TRASHED).exists():
        return None
    todolist = item.parent
    if todolist.status == Status.ARCHIVED:
        # Nothing new in an archived list (specs/archiving.md)
        return None
    TodoList.objects.select_for_update().get(item=todolist)
    following = create_item(
        project=item.project,
        parent=todolist,
        kind=Kind.TODO,
        title=item.title,
        creator=item.creator,
        position=_next_position(_todos_in(todolist, todo.group)),
    )
    Todo.objects.create(
        item=following,
        group=todo.group,
        notes=todo.notes,
        starts_on=starts_on,
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
    assignments = list(todo.assignment_set.select_related("user", "assigned_by"))
    people = [a.user for a in assignments if allowed.get(a.user_id)]
    if people:
        assign(
            following,
            people,
            actor=actor,
            assigned_by={a.user_id: a.assigned_by for a in assignments},
        )
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
    read_by_acting(actor, item)


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
        list_was, group_was = item.parent_id, item.todo.group_id
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
                # Where from and to, for leaving out moving back
                # (specs/timeline.md); merging keeps the first "was"
                group_id=group.pk if group else None,
                group_was=group_was,
            )
        if changed_list:
            visibility.recompute(item)
            record(
                actor=actor,
                action=Action.MOVED,
                project=item.project,
                item=item,
                to=todolist.title,
                to_id=todolist.pk,
                to_was=list_was,
                # The column it ends up in and came from: moving back
                # cancels out only if it's back in its column too
                group_id=group.pk if group else None,
                group_was=group_was,
            )
    _renumber(siblings)
    for list_id, group_id in sources:
        if (list_id, group_id) != (todolist.pk, group.pk if group else None):
            _renumber(list(_todos_in(list_id, group_id)))
    # The lists' open pages: reordered, and the lists the to-dos left
    live.changed(
        todolist,
        action="reordered",
        actor=actor,
        also={list_id for list_id, _group in sources},
    )


@transaction.atomic
def move_group(group, *, index):
    """Moves a group with its to-dos as a block: only its position changes"""
    todolist = TodoList.objects.select_for_update().get(pk=group.todolist_id)
    live.changed(todolist.item, action="grouped")
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
    live.changed(todolist.item, action="grouped")


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
    archived, its public links don't."""
    # Its public links (and those of what's in it) end for good
    # (specs/public-links.md)
    end_links(item=item)
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
        raise ValueError(gettext("The item isn't in the trash."))
    if item.parent_id and item.parent.status == Status.TRASHED:
        raise ValueError(gettext("Restore what it's in first."))
    # A change, for what comes back with it too: a doc whose "Tell people
    # about it?" is unanswered is told an hour after this, not at once
    # (trashing isn't a way around telling)
    now = timezone.now()
    Item.objects.filter(
        pk__in=list(Item.objects.descendants(item).values_list("pk", flat=True)),
        trashed_at=item.trashed_at,
    ).update(status=Status.ACTIVE, trashed_at=None, updated_at=now)
    item.status = Status.ARCHIVED if item.archived_when_trashed else Status.ACTIVE
    item.trashed_at = None
    item.archived_when_trashed = False
    item.updated_at = now
    item.save(
        update_fields=["status", "trashed_at", "archived_when_trashed", "updated_at"]
    )
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
    who sees them). Files also what a client of the same organization
    uploaded; an empty organization never matches (decided 2026-11-21)."""
    if not user.is_client or item.creator_id == user.pk:
        return True
    return bool(
        item.kind == Kind.FILE
        and user.organization_id is not None
        and item.creator.is_client
        and item.creator.organization_id == user.organization_id
    )


@transaction.atomic
def update_list(
    item, *, actor, title=_UNCHANGED, description=_UNCHANGED, view=_UNCHANGED
):
    """Changes what's given and differs; records an edit only then, like
    ``update_todo()``"""
    todolist = item.todolist
    edited = False
    if title is not _UNCHANGED and title != item.title:
        item.title = title
        item.updated_at = timezone.now()
        item.save(update_fields=["title", "updated_at"])
        edited = True
    fields = [
        name
        for name, value in [("description", description), ("view", view)]
        if value is not _UNCHANGED and value != getattr(todolist, name)
    ]
    for name in fields:
        setattr(todolist, name, description if name == "description" else view)
    if fields:
        todolist.save(update_fields=fields)
    if edited or fields:
        record(actor=actor, action=Action.EDITED, project=item.project, item=item)
        read_by_acting(actor, item)
    return item


@transaction.atomic
def archive(item, *, actor):
    """Readable, but out of the way: lists only (specs/archiving.md; to-dos
    are completed, not archived); archiving an archived list again changes
    nothing (a double submit)"""
    if item.kind != Kind.LIST:
        raise ValueError("Only lists can be archived")
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
    live.changed(group.todolist.item, action="grouped")


def trashed_roots(items):
    """The trashed items to show in the trash: those whose parent isn't
    trashed too (the parent's restore brings them back)"""
    return (
        items
        .filter(status=Status.TRASHED)
        .exclude(parent__status=Status.TRASHED)
        .order_by("-trashed_at", "-pk")
    )


# Drafts nobody wrote in are deleted after this (fairy_tasks)
DRAFT_DAYS = 1


def delete_drafts(*, now=None):
    """Deletes drafts left empty for a day (specs/files.md, "Docs");
    what was typed and not saved yet is saved first (``save_pending``
    runs before), making a doc of them. Each is checked again with its
    rows locked: one published meanwhile stays, so does one with typing
    not merged yet (``live_updates``); an open editor of a deleted draft
    is told (``live.check_access()``). Returns how many."""
    from biwak.collab import live
    from biwak.collab.models import LiveUpdate

    cutoff = (now or timezone.now()) - dt.timedelta(days=DRAFT_DAYS)
    old = Item.objects.filter(is_draft=True, created_at__lt=cutoff)
    count = 0
    for draft in old.order_by("pk"):
        with transaction.atomic():
            item = old.select_for_update().filter(pk=draft.pk).first()
            if item is None:
                continue
            # Typing arriving now (``live.append()``) waits for this lock
            # (its foreign key), so none slips in between the check and the
            # delete
            Doc.objects.select_for_update().filter(item=item).exists()
            if LiveUpdate.objects.filter(doc_id=item.pk).exists():
                continue
            item.delete()
            live.check_access(doc=draft.pk)
            count += 1
    return count


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


# Copying lists and moving across projects (specs/lists-across-projects.md) --

# What moves to another project: what's at the top of its project
# (anything in a folder moves with its folder)
MOVABLE = {Kind.LIST, Kind.MESSAGE, Kind.FOLDER, Kind.DOC, Kind.FILE}


class Dates(TextChoices):
    """What copying a list does with its to-dos' dates"""

    KEEP = "keep", _("Keep")
    SHIFT = "shift", _("Move by")
    REMOVE = "remove", _("Remove")


def staying(project, visible):
    """``Q()`` for the people who see an item of ``project`` (visible to
    clients or not) and stay assigned and subscribed when it's copied or
    moved there: its members (clients only if it's visible) and, in an
    all-access project, the own staff; inactive people too (they keep
    their assignments, specs/handover.md). ``notify.people_who_see()``
    without the active filter."""
    can_see = Q(is_client=False, memberships__project=project)
    if project.is_all_access:
        can_see |= own_staff()
    if visible:
        can_see |= Q(is_client=True, memberships__project=project)
    return Q(pk__in=User.objects.filter(can_see).values("pk"))


def people_plan(assignees, subscribers, project, visible):
    """Who copying or moving into ``project`` adds there and who it drops
    (decided 2026-11-22): assignees who don't see it there are added as
    members, staff and externals alike, if they're active; clients aren't,
    they're dropped with their assignments and subscriptions. Subscribers
    who don't see it there (and aren't added) are dropped. ``(added,
    dropped)``, querysets of people ordered by name."""
    seeing = User.objects.filter(staying(project, visible))
    added = (
        assignees
        .exclude(pk__in=seeing.values("pk"))
        .filter(is_client=False, is_active=True)
        .distinct()
    )
    kept = Q(pk__in=seeing.values("pk")) | Q(pk__in=added.values("pk"))
    dropped = User.objects.filter(
        Q(pk__in=assignees.values("pk")) | Q(pk__in=subscribers.values("pk"))
    ).exclude(kept)
    order = (Lower("full_name"), "email")
    return (
        User.objects.filter(pk__in=added.values("pk")).order_by(*order),
        dropped.order_by(*order),
    )


def copy_title(title, project):
    """The list's own title, " (copy)", " (copy 2)" … only when ``project``
    has a list of that name already, ignoring case (decided 2026-11-22);
    lists in the trash don't count"""
    taken = {
        t.lower()
        for t in Item.objects
        .filter(project=project, kind=Kind.LIST, parent=None)
        .exclude(status=Status.TRASHED)
        .values_list("title", flat=True)
    }
    candidate, number = title, 1
    while candidate.lower() in taken:
        suffix = (
            gettext(" (copy)")
            if number == 1
            else gettext(" (copy %(number)d)") % {"number": number}
        )
        candidate = title[: Item._meta.get_field("title").max_length - len(suffix)]
        candidate += suffix
        number += 1
    return candidate


def open_todos(list_item):
    """The open to-dos of a list, in the order of the list: ungrouped ones
    first, then group by group"""
    return (
        Item.objects
        .filter(parent=list_item, kind=Kind.TODO, todo__completed_at__isnull=True)
        .exclude(status=Status.TRASHED)
        .select_related("todo")
        .order_by(
            F("todo__group__position").asc(nulls_first=True),
            "todo__group",
            "position",
            "pk",
        )
    )


def copy_people(list_item, project, *, visible):
    """``people_plan()`` of copying the list's open to-dos into
    ``project``: those assignees added there, those left out"""
    return people_plan(
        User.objects.filter(assigned_todos__item__in=open_todos(list_item)),
        User.objects.none(),
        project,
        visible,
    )


def _copy_attachments(text, source, target, *, actor):
    """``text`` of ``source`` with the attachments it references copied
    (new files, not shared rows) for ``target``, and referencing those"""
    keys = set(REFERENCE.findall(text or ""))
    for attachment in Attachment.objects.filter(key__in=keys, item=source):
        copy = Attachment(
            project=target.project,
            item=target,
            key=new_key(),
            name=attachment.name,
            size=attachment.size,
            content_type=attachment.content_type,
            uploaded_by=actor,
        )
        with attachment.file.open("rb") as file:
            attachments.store(copy.file, attachment.name, File(file))
        copy.save()
        text = text.replace(f"attachment:{attachment.key}", f"attachment:{copy.key}")
    return text


@attachments.cleans_up_files
@transaction.atomic
def copy_list(item, *, project, title, actor, dates=Dates.KEEP, days=0, visible=False):
    """A copy of the list's open work in ``project`` (the same or another):
    its description, groups in order and open to-dos in order with their
    notes, checklists, recurrence and the assignees who are members of
    ``project`` or added to it (``copy_people()``; clients who aren't are
    left out). Not completed to-dos,
    comments, events, subscribers, reactions or public links. ``dates``
    keeps, shifts by ``days`` or removes the due dates. The copy gets
    ``project``'s visibility: internal unless ``visible``. One ``created``
    event for the list, the copier subscribed to it."""
    if item.kind != Kind.LIST:
        raise ValueError("Only lists are copied")
    if project.archived_at is not None:
        raise ValueError(gettext("Nothing can be added to an archived project."))
    source = item.todolist
    copy = create_item(
        project=project,
        kind=Kind.LIST,
        title=copy_title(title, project),
        creator=actor,
        visible=visible,
    )
    TodoList.objects.create(
        item=copy,
        description=_copy_attachments(source.description, item, copy, actor=actor),
        view=source.view,
    )
    groups = {
        group.pk: Group.objects.create(
            todolist=copy.todolist, title=group.title, position=group.position
        )
        for group in source.groups.all()
    }
    added, _dropped = copy_people(item, project, visible=visible)
    for user in added:
        project_ops.add_member(project, user, actor=actor)
    staying_ids = set(
        User.objects.filter(staying(project, visible)).values_list("pk", flat=True)
    )
    now = timezone.now()
    positions = {}
    for todo_item in open_todos(item).prefetch_related("todo__assignment_set"):
        todo = todo_item.todo
        group = groups.get(todo.group_id)
        positions[group] = position = positions.get(group, 0) + 1
        new = Item(
            project=project,
            parent=copy,
            kind=Kind.TODO,
            title=todo_item.title,
            creator=actor,
            position=position,
            is_client_visible=copy.is_client_visible,
        )
        new.save()
        due_on = todo.due_on
        starts_on = todo.starts_on
        ends_on = todo.recurrence_ends_on
        if dates == Dates.SHIFT:
            delta = dt.timedelta(days=days)
            due_on = due_on and due_on + delta
            starts_on = starts_on and starts_on + delta
            ends_on = ends_on and ends_on + delta
        elif dates == Dates.REMOVE:
            # A start date needs a due date (start-dates.md)
            due_on = starts_on = None
        Todo.objects.create(
            item=new,
            group=group,
            notes=_copy_attachments(todo.notes, todo_item, new, actor=actor),
            due_on=due_on,
            starts_on=starts_on,
            recurrence=todo.recurrence,
            recurrence_ends_on=ends_on,
            recurrence_count=todo.recurrence_count,
        )
        assignees = [
            a.user_id for a in todo.assignment_set.all() if a.user_id in staying_ids
        ]
        Assignment.objects.bulk_create([
            Assignment(todo_id=new.pk, user_id=pk, assigned_by=actor, assigned_at=now)
            for pk in assignees
        ])
        # Assigned means subscribed (specs/subscribers.md), told by nobody:
        # one event for the copy
        for user in User.objects.filter(pk__in=assignees):
            subscribe(user, new, explicit=False)
    created(copy, actor)
    return copy


def move_people(item, project):
    """``people_plan()`` of moving the item into ``project``: the assignees
    of its open to-dos added there, those assignees and subscribers of it
    and what's in it dropped"""
    items = Item.objects.descendants(item, include_self=True)
    return people_plan(
        User.objects.filter(
            assigned_todos__item__in=items.filter(
                kind=Kind.TODO, todo__completed_at__isnull=True
            )
        ),
        User.objects.filter(subscriptions__item__in=items),
        project,
        item.is_client_visible,
    )


def new_clients(item, project):
    """The active clients of ``project`` who would see the item there and
    don't see it now (no members of its project): moving asks first"""
    if not item.is_client_visible:
        return User.objects.none()
    return (
        User.objects
        .active()
        .filter(is_client=True, memberships__project=project)
        .exclude(memberships__project=item.project_id)
        .distinct()
    )


@transaction.atomic
def move_to_project(item, *, project, actor):
    """Moves a top-level list, message, folder, doc or file with everything
    in it, comments, reactions, events and history to the top level of
    another project. Assignees who don't see it there are added as members
    or, clients, dropped; subscribers who don't are dropped
    (``move_people()``); the item keeps its switch. Records a ``moved``
    event naming both projects, notifying nobody, and a trace in the old
    project (an event without item, for its staff)."""
    if item.kind not in MOVABLE or item.parent_id is not None:
        raise ValueError(gettext("Only what's at the top of a project moves there."))
    source = item.project
    if project.pk == source.pk:
        raise ValueError(gettext("It's in this project already."))
    if source.archived_at is not None or project.archived_at is not None:
        raise ValueError(gettext("Nothing moves into or out of an archived project."))
    pks = list(
        Item.objects.descendants(item, include_self=True).values_list("pk", flat=True)
    )
    added, dropped = (list(people) for people in move_people(item, project))
    for user in added:
        project_ops.add_member(project, user, actor=actor)
    if dropped:
        todos = Item.objects.filter(
            pk__in=pks,
            kind=Kind.TODO,
            todo__completed_at__isnull=True,
            todo__assignees__in=dropped,
        ).distinct()
        for todo in todos.select_related("todo", "project"):
            unassign(todo, dropped, actor=actor)
        Subscription.objects.filter(item__in=pks, user__in=dropped).delete()
    Item.objects.filter(pk__in=pks).update(project=project)
    Event.objects.filter(item__in=pks).update(project=project)
    Attachment.objects.filter(item__in=pks).update(project=project)
    item.project = project
    item.position = _next_position(
        Item.objects.filter(project=project, parent=None, kind=item.kind)
    )
    item.save(update_fields=["project", "position"])
    visibility.recompute(item)
    from biwak.collab import live as collab

    # The open editors of docs in it check again (specs/collaboration.md)
    collab.check_access(project=source.pk)
    # The trace in the old project (decided 2026-11-22: hard to find
    # otherwise), for its staff: what moved stays out of clients' sight
    record(
        actor=actor,
        action=Action.MOVED,
        project=source,
        title=item.title,
        kind=item.kind,
        to_project=project.name,
        to_project_id=project.pk,
    )
    return record(
        actor=actor,
        action=Action.MOVED,
        project=project,
        item=item,
        from_project=source.name,
        from_project_id=source.pk,
        to_project=project.name,
        to_project_id=project.pk,
    )
