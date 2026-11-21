"""Importing a Basecamp 4 account, project by project (specs/import-basecamp.md)

Everything is written by the operations of the apps (``biwak.items``,
``biwak.files``, ``biwak.checkins``, ``biwak.projects``), inside
``importing()``, which keeps the events from telling anybody and gives them
the original time. Afterwards the original timestamps are set on what the
operations wrote. ``ImportedObject`` remembers Basecamp's IDs, so a second
run updates what exists.

A dry run reads everything (the API is only read) and writes nothing: it
counts per kind, lists the people who would be created and the problems.
"""

import datetime as dt
import re
from collections import Counter, defaultdict
from zoneinfo import ZoneInfo

from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from biwak import schedules
from biwak.accounts.models import User
from biwak.activity import mentions
from biwak.activity.models import Subscription
from biwak.activity.notify import who_can_see
from biwak.activity.operations import importing, subscribe
from biwak.bookmarks import operations as bookmark_ops
from biwak.checkins import operations as checkin_ops
from biwak.files import attachments, operations as file_ops
from biwak.importer import client as api
from biwak.importer.convert import Resolver, to_markdown
from biwak.importer.models import ImportedObject
from biwak.items import operations as ops
from biwak.items.models import (
    Comment,
    Item,
    Kind,
    MessageCategory,
    Status,
    Todo,
    TodoList,
)
from biwak.organizations.models import Organization, normalize_name
from biwak.projects import operations as project_ops
from biwak.projects.models import Project


PERSON, PROJECT, ATTACHMENT = "Person", "Project", "Attachment"
GROUP, COLUMN = "Todolist::Group", "Kanban::Column"

# Our names for what the counts and problems talk about
KINDS = {
    "Project": "projects",
    "Person": "people",
    "Todolist": "lists",
    "Todolist::Group": "groups",
    "Todo": "to-dos",
    "Kanban::Board": "card tables",
    "Kanban::Column": "columns",
    "Kanban::Card": "cards",
    "Message": "messages",
    "Vault": "folders",
    "Vault::Internal": "internal folders",
    "Todolist::Internal": "internal lists",
    "Document": "docs",
    "Upload": "files",
    "Question": "check-in questions",
    "Question::Answer": "check-in answers",
    "Comment": "comments",
    "Attachment": "attachments",
}

# Basecamp's weekdays, 0 is Sunday
WEEKDAYS = ["SU", "MO", "TU", "WE", "TH", "FR", "SA"]

# Links to other recordings in texts: <account>/buckets/<project>/<path>/<id>
LINK = re.compile(
    r"https://3\.basecamp\.com/\d+/buckets/\d+/"
    r"(todos|todolists|messages|documents|uploads|vaults|card_tables/cards"
    r"|card_tables|questions)/(\d+)[^\s)\]\"']*"
)
LINK_TYPES = {
    "todos": "Todo",
    "todolists": "Todolist",
    "messages": "Message",
    "documents": "Document",
    "uploads": "Upload",
    "vaults": "Vault",
    "card_tables/cards": "Kanban::Card",
    "card_tables": "Kanban::Board",
    "questions": "Question",
}


class Report:
    """What a run did (or, in a dry run, would do)"""

    def __init__(self, *, dry_run):
        self.dry_run = dry_run
        self.counts = defaultdict(Counter)
        self.people = []  # the people created (or to create)
        self.problems = []
        # Internal items inside containers visible to clients, which go
        # into internal containers of their own
        self.internal = []

    def as_text(self):
        lines = ["Dry run, nothing was written." if self.dry_run else "Imported."]
        for label in KINDS.values():
            if counts := self.counts.get(label):
                lines.append(
                    f"  {label}: {counts['created']} new, {counts['updated']} existing"
                )
        if self.people:
            lines.append(
                "People created inactive:" if not self.dry_run else "People to create:"
            )
            lines += [f"  {person}" for person in self.people]
        if self.internal:
            lines.append("Internal inside containers visible to clients, moved:")
            lines += [f"  {line}" for line in self.internal]
        if self.problems:
            lines.append("Problems:")
            lines += [f"  {problem}" for problem in self.problems]
        return "\n".join(lines)


def parse_time(value):
    return dt.datetime.fromisoformat(value) if value else None


class Importer(Resolver):
    def __init__(self, client, *, actor, dry_run=False, since=None):
        """``actor``: the Biwak person running the import (staff), who
        creates the projects and owns the bookmarks"""
        self.client = client
        self.actor = actor
        self.dry = dry_run
        self.since = since
        self.report = Report(dry_run=dry_run)
        self._users = {}  # Basecamp person ID: User, or None
        self._people_by_sgid = {}
        # While converting a text: its project, author and file entries
        self._text = None
        self._links_to_fix = []
        # The list or card table being imported, and the internal lists made
        # for them in this run
        self._container = None
        self._container_is_board = False
        self._container_project = None
        self._internal_lists = {}

    # Reporting -----------------------------------------------------------

    def problem(self, message):
        self.report.problems.append(message)

    def _count(self, bc_type, what):
        self.report.counts[KINDS.get(bc_type, bc_type)][what] += 1

    # The mapping -----------------------------------------------------------

    def _find(self, bc_type, bc_id):
        """The Biwak object of a Basecamp ID, or None (also when it was
        deleted since)"""
        mapped = ImportedObject.objects.filter(
            basecamp_type=bc_type, basecamp_id=bc_id
        ).first()
        if mapped is None:
            return None
        target = mapped.target
        if target is None:
            mapped.delete()
        return target

    def _remember(self, bc_type, bc_id, obj):
        ImportedObject.objects.update_or_create(
            basecamp_type=bc_type,
            basecamp_id=bc_id,
            defaults={
                "content_type": ContentType.objects.get_for_model(obj),
                "object_id": obj.pk,
                "imported_at": timezone.now(),
            },
        )

    def _upsert(self, bc_type, rec, *, create, update=None):
        """Creates the Biwak object of the recording or updates the one
        imported before; in a dry run only counts. Each in a transaction
        of its own with the mapping, so an interrupted run continues."""
        found = self._find(bc_type, rec["id"])
        self._count(bc_type, "updated" if found else "created")
        if self.dry:
            return found
        with transaction.atomic():
            if found is None:
                found = create()
                self._remember(bc_type, rec["id"], found)
            elif update is not None:
                update(found)
        return found

    def _skip(self, rec):
        """``--since``: what wasn't changed since isn't looked at again"""
        updated = parse_time(rec.get("updated_at"))
        return bool(self.since and updated and updated < self.since)

    # People ------------------------------------------------------------------

    def _user(self, person):
        """The Biwak person of a Basecamp person: by the mapping, by email
        address, or created (inactive, staff or client as in Basecamp).
        None in a dry run for people who would be created."""
        if not person:
            return None
        pid = person["id"]
        if pid in self._users:
            return self._users[pid]
        user = self._find(PERSON, pid)
        if user is None:
            user = self._match_or_create(person)
            if user is not None and not self.dry:
                self._remember(PERSON, pid, user)
        self._users[pid] = user
        return user

    def _match_or_create(self, person):
        email = (person.get("email_address") or "").strip()
        name = person.get("name") or ""
        redacted = not email or "•" in email
        if redacted:
            # Only administrators get addresses; keep the name at least
            self.problem(
                f"No email address for {name} (Basecamp ID {person['id']}):"
                " imported as a placeholder, the token needs an administrator"
            )
            email = f"basecamp-{person['id']}@import.invalid"
        user = User.objects.filter(email__iexact=email).first()
        if user is not None:
            return user
        client = bool(person.get("client"))
        company = (person.get("company") or {}).get("name", "")
        label = f"{name} <{email}> ({'client' if client else 'staff'})"
        self.report.people.append(label)
        if self.dry:
            return None
        return User.objects.create_user(
            email,
            full_name=name,
            is_client=client,
            organization=self._organization(company) if client else None,
            is_active=False,
        )

    def _organization(self, name):
        """Basecamp's company as an organization, by name (ignoring case and
        spaces)"""
        name = normalize_name(name)
        if not name:
            return None
        return Organization.objects.named(name) or Organization.objects.create(
            name=name
        )

    def user_for_sgid(self, sgid):
        pid = self._people_by_sgid.get(sgid)
        if pid is None:
            # The signed global ID names the person: gid://bc3/Person/ID
            import base64

            try:
                raw = base64.b64decode(sgid.split("--")[0] + "==", validate=False)
            except ValueError:
                raw = b""
            found = re.search(rb"gid://bc3/Person/(\d+)", raw)
            pid = int(found[1]) if found else None
        return self._users.get(pid) if pid else None

    def _add_member(self, project, user):
        # Inactive people too (``importing()``): once somebody activates
        # them they are members
        project_ops.add_member(project, user, actor=self.actor)

    # Texts ---------------------------------------------------------------------

    def mention(self, sgid, label):
        user = self.user_for_sgid(sgid)
        return mentions.syntax(user) if user else None

    def attachment(self, element):
        text = self._text
        entries = text["attachments"] if text else []
        sgid = element.get("sgid")
        entry = next(
            (e for e in entries if e.get("sgid") and e["sgid"] == sgid), None
        ) or next(
            (
                e
                for e in entries
                if e.get("filename") and e["filename"] == element.get("filename")
            ),
            None,
        )
        if entry is None or self.dry or text["project"] is None:
            return None
        known = self._find(ATTACHMENT, entry["id"])
        if known is None:
            try:
                data = self.client.download(entry["download_url"])
            except (api.NotFound, api.ApiError, KeyError) as exc:
                self.problem(f"File {entry.get('filename')} not downloaded: {exc}")
                return None
            name = entry.get("filename") or "file"
            known = attachments.upload(
                project=text["project"],
                file=ContentFile(data, name=name),
                uploaded_by=text["author"],
            )
            self._remember(ATTACHMENT, entry["id"], known)
            self._count(ATTACHMENT, "created")
        else:
            self._count(ATTACHMENT, "updated")
        bang = "!" if known.is_image else ""
        return f"{bang}[{known.name}](attachment:{known.key})"

    def link(self, href):
        found = LINK.fullmatch(href)
        if found:
            target = self._find(LINK_TYPES[found[1]], int(found[2]))
            if isinstance(target, Item):
                return target.get_absolute_url()
        return href

    def _md(self, html, rec_attachments, *, project, author):
        """Markdown of a Basecamp text; files in it are downloaded and
        uploaded as ``author``, who saves the text next"""
        self._text = {
            "attachments": rec_attachments or [],
            "project": project,
            "author": author,
        }
        try:
            text = to_markdown(html, self)
        finally:
            self._text = None
        if LINK.search(text):
            # Targets which aren't imported yet: fixed when the run is done
            self._links_to_fix.append(text)
        return text

    # A run --------------------------------------------------------------------------

    def run(self, project_id):
        """Imports one project; returns the report"""
        rec = self.client.get(f"/projects/{project_id}.json")
        with importing():
            project = self._project(rec)
            people = list(self.client.paginate(f"/projects/{project_id}/people.json"))
            for person in people:
                self._people_by_sgid[person.get("attachable_sgid")] = person["id"]
            for person in people:
                user = self._user(person)
                if user is not None and project is not None:
                    with importing(at=parse_time(rec["created_at"])):
                        self._add_member(project, user)
            self._dock(rec, project)
            if not self.dry:
                self._fix_links(project)
                self._bookmarks(project)
                project_ops.recompute_activity()
        return self.report

    def _project(self, rec):
        def create():
            project = project_ops.create_project(
                name=rec["name"],
                description=rec.get("description") or "",
                is_all_access=bool(rec.get("all_access", True)),
                actor=self.actor,
            )
            Project.objects.filter(pk=project.pk).update(
                created_at=parse_time(rec["created_at"])
            )
            return project

        def update(project):
            project_ops.update_project(
                project,
                actor=self.actor,
                name=rec["name"],
                description=rec.get("description") or "",
                is_all_access=bool(rec.get("all_access", True)),
            )

        project = self._upsert(PROJECT, rec, create=create, update=update)
        if project is not None and rec.get("status") == "archived":
            if project.archived_at is None:
                project_ops.archive_project(project, actor=self.actor)
        elif project is not None and project.archived_at is not None:
            project_ops.unarchive_project(project, actor=self.actor)
        return project

    def _dock(self, rec, project):
        for tool in rec.get("dock", []):
            if not tool.get("enabled"):
                continue
            match tool["name"]:
                case "todoset":
                    self._todoset(tool["id"], project)
                case "kanban_board":
                    self._card_table(tool["id"], project)
                case "message_board":
                    self._message_board(tool["id"], project)
                case "vault":
                    self._vault(
                        tool["id"], project, None, parent_visible=False, nested=False
                    )
                case "questionnaire":
                    self._questionnaire(tool["id"], project)
                # The schedule, chat, pings and forwards aren't imported

    # Shared by the kinds --------------------------------------------------------

    def _inherits(self, rec, parent_visible, label):
        """Whether a child of a visible container may be imported as it is:
        Biwak shows children of visible containers to clients and they have
        no switch of their own, so what was internal there goes into an
        internal container of its own (specs/import-basecamp.md)"""
        return not (parent_visible and not rec.get("visible_to_clients"))

    def _moved(self, label, rec, container, kind):
        self.report.internal.append(
            f"{label} {rec['id']} ({rec.get('title', '')!r}) into"
            f' {kind} "{container["title"]} (internal)"'
        )

    def _internal_folder(self, container, project, creator):
        """A function returning the top-level folder "<title> (internal)"
        for a folder visible to clients, created when first needed (None in
        a dry run, when it doesn't exist)"""
        found = []

        def get():
            if not found:

                def create():
                    with importing(at=parse_time(container["created_at"])):
                        item = ops.create_folder(
                            project=project,
                            title=f"{container['title']} (internal)",
                            creator=creator,
                            parent=None,
                            visible=False,
                        )
                    self._stamp(item, container)
                    return item

                found.append(self._upsert("Vault::Internal", container, create=create))
            return found[0]

        get.container = container
        return get

    def _place(self, rec, label, parent, parent_visible, nested, internal):
        """Where a folder, doc or file goes: (parent, visible). Internal
        ones inside a visible folder go to its internal folder."""
        if not nested:
            return parent, bool(rec.get("visible_to_clients"))
        if self._inherits(rec, parent_visible, label):
            return parent, parent_visible
        self._moved(label, rec, internal.container, "folder")
        return internal(), False

    def _internal_list(self, todo_rec, group, creator):
        """The internal list "<list> (internal)" of the list (or card
        table) being imported, and the group of that title in it (created
        when needed); None, None in a dry run"""
        container = self._container
        bc_type = "Kanban::Board" if self._container_is_board else "Todolist"
        key = (bc_type, container["id"])
        if key not in self._internal_lists:

            def create():
                with importing(at=parse_time(container["created_at"])):
                    item = ops.create_list(
                        project=self._container_project,
                        title=f"{container['title']} (internal)",
                        creator=creator,
                        visible=False,
                    )
                    if self._container_is_board:
                        ops.update_list(item, actor=creator, view=TodoList.View.BOARD)
                self._stamp(item, container)
                return item

            self._internal_lists[key] = self._upsert(
                "Todolist::Internal", container, create=create
            )
        item = self._internal_lists[key]
        self._moved("to-do", todo_rec, container, "list")
        if item is None or group is None:
            return item, None
        found = item.todolist.groups.filter(title=group.title).first()
        if found is None:
            found = ops.create_group(todolist=item.todolist, title=group.title)
        return item, found

    def _stamp(self, item, rec):
        """The original times; the operations wrote now"""
        Item.objects.filter(pk=item.pk).update(
            created_at=parse_time(rec["created_at"]),
            updated_at=parse_time(rec.get("updated_at") or rec["created_at"]),
        )

    def _top_visibility(self, item, visible, rec):
        """What the operations created is visible as the creator is a
        client (messages); the importer sets what Basecamp had"""
        item.refresh_from_db()
        if item.has_switch and item.visible_to_clients != visible:
            with importing(at=parse_time(rec.get("updated_at"))):
                ops.set_visibility(item, visible=visible, actor=item.creator)

    def _status(self, item, rec):
        archived = rec.get("status") == "archived"
        with importing(at=parse_time(rec.get("updated_at"))):
            if archived and item.status == Status.ACTIVE:
                ops.archive(item, actor=item.creator)
            elif not archived and item.status == Status.ARCHIVED:
                ops.unarchive(item, actor=item.creator)

    def _comments(self, rec, item):
        if self.since and self._skip(rec):
            return
        if rec.get("comments_count") == 0 or rec.get("comment_count") == 0:
            return
        try:
            comments = list(
                self.client.paginate(f"/recordings/{rec['id']}/comments.json")
            )
        except api.NotFound:
            return
        for comment in comments:
            if self._skip(comment):
                continue
            author = self._user(comment.get("creator"))
            when = parse_time(comment["created_at"])

            def create(comment=comment, author=author, when=when):
                content = self._md(
                    comment.get("content"),
                    comment.get("content_attachments"),
                    project=item.project,
                    author=author,
                )
                with importing(at=when):
                    created = ops.add_comment(item, author=author, content=content)
                Comment.objects.filter(pk=created.pk).update(
                    created_at=when,
                    updated_at=parse_time(comment.get("updated_at")) or when,
                )
                return created

            self._upsert("Comment", comment, create=create)

    def _subscriptions(self, rec, item):
        """Subscribers as in Basecamp, who can see the item"""
        if self.dry or not rec.get("subscription_url"):
            return
        try:
            data = self.client.get(f"/recordings/{rec['id']}/subscription.json")
        except api.NotFound:
            return
        users = [self._user(p) for p in data.get("subscribers", [])]
        users = [
            u
            for u in users
            if u and (not u.is_client or Item.objects.get(pk=item.pk).is_client_visible)
        ]
        Subscription.objects.filter(item=item).exclude(user__in=users).delete()
        for user in users:
            subscribe(user, item, added_by=self.actor)

    def _sync_assignees(self, item, people, actor):
        wanted = [u for u in (self._user(p) for p in people) if u]
        current = set(item.todo.assignees.all())
        for user in wanted:
            if user in current:
                continue
            try:
                ops.assign(item, [user], actor=actor)
            except ValueError as exc:
                self.problem(f"Not assigned: {exc}")
        removed = current - set(wanted)
        if removed:
            ops.unassign(item, list(removed), actor=actor)

    # To-do lists --------------------------------------------------------------------

    def _todoset(self, todoset_id, project):
        lists = []
        for status in ({}, {"status": "archived"}):
            lists += self.client.paginate(
                f"/todosets/{todoset_id}/todolists.json", **status
            )
        for rec in sorted(lists, key=lambda r: r.get("position", 0)):
            self._todolist(rec, project)

    def _todolist(self, rec, project):
        creator = self._user(rec.get("creator"))
        visible = bool(rec.get("visible_to_clients"))

        def create():
            with importing(at=parse_time(rec["created_at"])):
                return ops.create_list(
                    project=project,
                    title=rec["title"],
                    creator=creator,
                    description=self._md(
                        rec.get("description"),
                        rec.get("description_attachments"),
                        project=project,
                        author=creator,
                    ),
                    visible=visible,
                )

        def update(item):
            with importing(at=parse_time(rec.get("updated_at"))):
                ops.update_list(
                    item,
                    actor=item.creator,
                    title=rec["title"],
                    description=self._md(
                        rec.get("description"),
                        rec.get("description_attachments"),
                        project=project,
                        author=item.creator,
                    ),
                )

        item = self._upsert("Todolist", rec, create=create, update=update)
        if item is not None:
            self._top_visibility(item, visible, rec)
            self._status(item, rec)
            self._stamp(item, rec)
        self._list_content(rec, item, visible, project)
        if item is not None:
            self._subscriptions(rec, item)

    def _list_content(self, rec, item, visible, project):
        """Its to-dos and the groups with theirs"""
        self._container, self._container_is_board = rec, False
        self._container_project = project
        self._todos(rec["id"], item, None, visible, project)
        try:
            groups = list(self.client.paginate(f"/todolists/{rec['id']}/groups.json"))
        except api.NotFound:
            groups = []
        for group_rec in sorted(groups, key=lambda r: r.get("position", 0)):
            self._group(group_rec, item, visible, project, rec_type=GROUP)

    def _group(self, rec, item, visible, project, *, rec_type, cards=False):
        todolist = item.todolist if item is not None else None

        def create():
            return ops.create_group(todolist=todolist, title=rec["title"])

        def update(group):
            if group.title != rec["title"]:
                ops.rename_group(group, title=rec["title"])

        group = self._upsert(rec_type, rec, create=create, update=update)
        if cards:
            self._cards(rec["id"], item, group, visible, project)
        else:
            self._todos(rec["id"], item, group, visible, project)

    def _todos(self, list_id, item, group, parent_visible, project):
        found = []
        for params in ({}, {"completed": "true"}, {"status": "archived"}):
            try:
                found += self.client.paginate(
                    f"/todolists/{list_id}/todos.json", **params
                )
            except api.NotFound:
                pass
        seen = set()
        for rec in found:
            if rec["id"] in seen:
                continue
            seen.add(rec["id"])
            self._todo(rec, item, group, parent_visible, project, "Todo")

    def _todo(self, rec, item, group, parent_visible, project, bc_type):
        if self._skip(rec):
            return
        creator = self._user(rec.get("creator"))
        if not self._inherits(rec, parent_visible, "to-do"):
            item, group = self._internal_list(rec, group, creator)
        title = rec["title"]

        def notes():
            text = self._md(
                rec.get("description"),
                rec.get("description_attachments"),
                project=project,
                author=creator,
            )
            steps = "\n".join(
                f"- [{'x' if step.get('completed') else ' '}] {step['title']}"
                for step in rec.get("steps", [])
            )
            return f"{text}\n\n{steps}".strip()

        def create():
            with importing(at=parse_time(rec["created_at"])):
                return ops.create_todo(
                    todolist=item,
                    title=title,
                    creator=creator,
                    group=group,
                    notes=notes(),
                    due_on=rec.get("due_on") and dt.date.fromisoformat(rec["due_on"]),
                )

        def update(todo):
            with importing(at=parse_time(rec.get("updated_at"))):
                ops.update_todo(
                    todo,
                    actor=todo.creator,
                    title=title,
                    notes=notes(),
                    due_on=rec.get("due_on") and dt.date.fromisoformat(rec["due_on"]),
                )

        todo = self._upsert(bc_type, rec, create=create, update=update)
        if todo is None:
            self._comments(rec, None)
            return
        with importing(at=parse_time(rec.get("updated_at"))):
            self._sync_assignees(todo, rec.get("assignees", []), todo.creator)
            self._completion(todo, rec)
            self._status(todo, rec)
        self._stamp(todo, rec)
        self._comments(rec, todo)
        self._subscriptions(rec, todo)

    def _completion(self, todo, rec):
        done = Todo.objects.get(item=todo).is_completed
        if rec.get("completed") and not done:
            completion = rec.get("completion") or {}
            when = parse_time(completion.get("created_at")) or parse_time(
                rec["updated_at"]
            )
            by = self._user(completion.get("creator")) or todo.creator
            with importing(at=when):
                ops.complete(todo, actor=by)
            Todo.objects.filter(pk=todo.pk).update(completed_at=when)
        elif not rec.get("completed") and done:
            ops.reopen(todo, actor=todo.creator)

    # Card tables -----------------------------------------------------------------------

    def _card_table(self, table_id, project):
        try:
            rec = self.client.get(f"/card_tables/{table_id}.json")
        except api.NotFound:
            return
        creator = self._user(rec.get("creator"))
        visible = bool(rec.get("visible_to_clients"))

        def create():
            with importing(at=parse_time(rec["created_at"])):
                item = ops.create_list(
                    project=project,
                    title=rec["title"],
                    creator=creator,
                    visible=visible,
                )
                ops.update_list(item, actor=creator, view=TodoList.View.BOARD)
            return item

        def update(item):
            with importing(at=parse_time(rec.get("updated_at"))):
                ops.update_list(item, actor=item.creator, title=rec["title"])

        item = self._upsert("Kanban::Board", rec, create=create, update=update)
        if item is not None:
            self._top_visibility(item, visible, rec)
            self._stamp(item, rec)
        self._container, self._container_is_board = rec, True
        self._container_project = project
        for column in rec.get("lists", []):
            self._group(column, item, visible, project, rec_type=COLUMN, cards=True)
        if item is not None:
            self._subscriptions(rec, item)

    def _cards(self, column_id, item, group, parent_visible, project):
        try:
            cards = list(
                self.client.paginate(f"/card_tables/lists/{column_id}/cards.json")
            )
        except api.NotFound:
            return
        for rec in cards:
            self._todo(rec, item, group, parent_visible, project, "Kanban::Card")

    # Messages -------------------------------------------------------------------------------

    def _category(self, rec):
        category = rec.get("category")
        if not category or self.dry:
            return None
        found = MessageCategory.objects.filter(name__iexact=category["name"]).first()
        if found is None:
            last = MessageCategory.objects.order_by("-position").first()
            found = MessageCategory.objects.create(
                name=category["name"],
                emoji=category.get("icon") or "",
                position=(last.position + 1) if last else 0,
            )
        return found

    def _message_board(self, board_id, project):
        messages = list(
            self.client.paginate(f"/message_boards/{board_id}/messages.json")
        )
        # Oldest first: the board lists newest first by creation
        for rec in sorted(messages, key=lambda r: r["created_at"]):
            self._message(rec, project)

    def _message(self, rec, project):
        if self._skip(rec):
            return
        creator = self._user(rec.get("creator"))
        visible = bool(rec.get("visible_to_clients"))

        def content():
            return self._md(
                rec.get("content"),
                rec.get("content_attachments"),
                project=project,
                author=creator,
            )

        def create():
            with importing(at=parse_time(rec["created_at"])):
                return ops.create_message(
                    project=project,
                    title=rec.get("subject") or rec["title"],
                    creator=creator,
                    content=content(),
                    visible=visible,
                    category=self._category(rec),
                )

        def update(item):
            with importing(at=parse_time(rec.get("updated_at"))):
                file_ops.update_message(
                    item,
                    actor=item.creator,
                    title=rec.get("subject") or rec["title"],
                    content=content(),
                    category=self._category(rec),
                )

        item = self._upsert("Message", rec, create=create, update=update)
        if item is None:
            self._comments(rec, None)
            return
        self._top_visibility(item, visible, rec)
        self._stamp(item, rec)
        self._comments(rec, item)
        self._subscriptions(rec, item)

    # Docs & Files -------------------------------------------------------------------------------

    def _vault(
        self, vault_id, project, parent, *, parent_visible, nested, internal=None
    ):
        """The children of a vault: the root vault is the project's root"""
        folders = self.client.paginate(f"/vaults/{vault_id}/vaults.json")
        for rec in sorted(folders, key=lambda r: r.get("position", 0)):
            self._folder(rec, project, parent, parent_visible, nested, internal)
        for rec in self.client.paginate(f"/vaults/{vault_id}/documents.json"):
            self._document(rec, project, parent, parent_visible, nested, internal)
        for rec in self.client.paginate(f"/vaults/{vault_id}/uploads.json"):
            self._upload(rec, project, parent, parent_visible, nested, internal)

    def _folder(self, rec, project, parent, parent_visible, nested, internal):
        parent, visible = self._place(
            rec, "folder", parent, parent_visible, nested, internal
        )
        creator = self._user(rec.get("creator"))
        if not nested and visible:
            internal = self._internal_folder(rec, project, creator)

        def create():
            with importing(at=parse_time(rec["created_at"])):
                return ops.create_folder(
                    project=project,
                    title=rec["title"],
                    creator=creator,
                    parent=parent,
                    visible=visible,
                )

        item = self._upsert("Vault", rec, create=create)
        if item is not None:
            self._top_visibility(item, visible, rec)
            self._stamp(item, rec)
            self._subscriptions(rec, item)
        self._vault(
            rec["id"],
            project,
            item,
            parent_visible=visible,
            nested=True,
            internal=internal,
        )

    def _document(self, rec, project, parent, parent_visible, nested, internal):
        if self._skip(rec):
            return
        parent, visible = self._place(
            rec, "doc", parent, parent_visible, nested, internal
        )
        creator = self._user(rec.get("creator"))

        def content():
            return self._md(
                rec.get("content"),
                rec.get("content_attachments"),
                project=project,
                author=creator,
            )

        def create():
            with importing(at=parse_time(rec["created_at"])):
                return ops.create_doc(
                    project=project,
                    title=rec["title"],
                    creator=creator,
                    parent=parent,
                    content=content(),
                    visible=visible,
                )

        def update(item):
            with importing(at=parse_time(rec.get("updated_at"))):
                file_ops.update_doc(
                    item, actor=item.creator, title=rec["title"], content=content()
                )

        item = self._upsert("Document", rec, create=create, update=update)
        if item is None:
            self._comments(rec, None)
            return
        self._top_visibility(item, visible, rec)
        self._stamp(item, rec)
        self._comments(rec, item)
        self._subscriptions(rec, item)

    def _upload(self, rec, project, parent, parent_visible, nested, internal):
        if self._skip(rec):
            return
        parent, visible = self._place(
            rec, "file", parent, parent_visible, nested, internal
        )
        creator = self._user(rec.get("creator"))

        def description():
            return self._md(
                rec.get("description"),
                rec.get("description_attachments"),
                project=project,
                author=creator,
            )

        def create():
            try:
                data = self.client.download(rec["download_url"])
            except (api.NotFound, api.ApiError, KeyError) as exc:
                self.problem(f"File {rec.get('filename')} not downloaded: {exc}")
                raise _Skip from exc
            name = rec.get("filename") or rec["title"]
            with importing(at=parse_time(rec["created_at"])):
                return ops.create_upload(
                    project=project,
                    file=ContentFile(data, name=name),
                    creator=creator,
                    parent=parent,
                    description=description(),
                    visible=visible,
                )

        def update(item):
            with importing(at=parse_time(rec.get("updated_at"))):
                file_ops.update_upload(
                    item, actor=item.creator, description=description()
                )

        try:
            item = self._upsert("Upload", rec, create=create, update=update)
        except _Skip:
            return
        if item is None:
            self._comments(rec, None)
            return
        self._top_visibility(item, visible, rec)
        self._stamp(item, rec)
        self._comments(rec, item)
        self._subscriptions(rec, item)

    # Check-ins ------------------------------------------------------------------------------------

    def _questionnaire(self, questionnaire_id, project):
        for rec in self.client.paginate(
            f"/questionnaires/{questionnaire_id}/questions.json"
        ):
            self._question(rec, project)

    def _question(self, rec, project):
        creator = self._user(rec.get("creator"))
        visible = bool(rec.get("visible_to_clients"))
        try:
            rule, starts_on, time_of_day = schedule_of(rec["schedule"])
        except (ValueError, KeyError, schedules.InvalidRule) as exc:
            self.problem(f"Skipped check-in {rec['title']!r} ({rec['id']}): {exc}")
            return

        def create():
            with importing(at=parse_time(rec["created_at"])):
                item = checkin_ops.create_question(
                    project=project,
                    title=rec["title"],
                    creator=creator,
                    rule=rule,
                    starts_on=starts_on,
                    time_of_day=time_of_day,
                    visible=visible,
                )
                # Never asked again from here: Basecamp keeps asking
                checkin_ops.pause(item, actor=creator)
            return item

        item = self._upsert("Question", rec, create=create)
        answers = list(self.client.paginate(f"/questions/{rec['id']}/answers.json"))
        if item is not None:
            self._stamp(item, rec)
        asked = []
        for answer in answers:
            if self._skip(answer):
                continue
            user = self._answer(answer, rec, item, visible)
            if user is not None and user not in asked:
                asked.append(user)
        if item is not None and asked:
            who = [u for u in asked if u.is_active]
            allowed = who_can_see(item).filter(pk__in=[u.pk for u in who])
            if allowed:
                with importing():
                    checkin_ops.set_people(
                        item,
                        sorted(
                            set(allowed) | set(item.question.people.all()),
                            key=lambda u: u.pk,
                        ),
                        actor=item.creator,
                    )
        if item is not None:
            self._subscriptions(rec, item)

    def _answer(self, rec, question_rec, question, visible):
        if not self._inherits(rec, visible, "check-in answer"):
            # Answers can't be moved elsewhere
            self.problem(
                f"Skipped check-in answer {rec['id']}: internal in Basecamp,"
                " inside a question visible to clients"
            )
            return None
        user = self._user(rec.get("creator"))
        day = dt.date.fromisoformat(rec.get("group_on") or rec["created_at"][:10])

        def create():
            with importing(at=parse_time(rec["created_at"])):
                schedule = question.question
                asked_at = dt.datetime.combine(
                    day, schedule.time_of_day, tzinfo=ZoneInfo(schedule.time_zone)
                )
                occurrence = checkin_ops.add_occurrence(
                    question, date=day, asked_at=asked_at
                )
                if occurrence.answers.filter(author=user).exists():
                    self.problem(
                        f"Skipped answer {rec['id']}: {user} answered on {day} already"
                    )
                    raise _Skip
                return checkin_ops.create_answer(
                    question,
                    user,
                    self._md(
                        rec.get("content"),
                        rec.get("content_attachments"),
                        project=question.project,
                        author=user,
                    ),
                    occurrence,
                )

        try:
            item = self._upsert("Question::Answer", rec, create=create)
        except _Skip:
            return user
        if item is not None:
            self._stamp(item, rec)
            self._comments(rec, item)
        else:
            self._comments(rec, None)
        return user

    # After the project --------------------------------------------------------------------

    def _fix_links(self, project):
        """Links to recordings imported later in the run: the texts get
        their Biwak URLs now"""
        if not self._links_to_fix:
            return
        with importing():
            for item in Item.objects.filter(project=project).select_related("creator"):
                self._fix_item_links(item)
            for comment in Comment.objects.filter(item__project=project):
                fixed = self._rewrite(comment.content)
                if fixed != comment.content:
                    # There's no operation changing comments
                    Comment.objects.filter(pk=comment.pk).update(content=fixed)

    def _rewrite(self, text):
        return LINK.sub(lambda m: self.link(m[0]), text or "")

    def _fix_item_links(self, item):
        detail = item.detail
        original = item.updated_at
        with importing(at=original):
            self._rewrite_item(item, detail)
        Item.objects.filter(pk=item.pk).update(updated_at=original)

    def _rewrite_item(self, item, detail):
        match item.kind:
            case Kind.TODO:
                fixed = self._rewrite(detail.notes)
                if fixed != detail.notes:
                    ops.update_todo(item, actor=item.creator, notes=fixed)
            case Kind.LIST:
                fixed = self._rewrite(detail.description)
                if fixed != detail.description:
                    ops.update_list(item, actor=item.creator, description=fixed)
            case Kind.MESSAGE:
                fixed = self._rewrite(detail.content)
                if fixed != detail.content:
                    file_ops.update_message(item, actor=item.creator, content=fixed)
            case Kind.DOC:
                fixed = self._rewrite(detail.content)
                if fixed != detail.content:
                    file_ops.update_doc(item, actor=item.creator, content=fixed)
            case Kind.FILE:
                fixed = self._rewrite(detail.description)
                if fixed != detail.description:
                    file_ops.update_upload(item, actor=item.creator, description=fixed)
            case Kind.ANSWER:
                fixed = self._rewrite(detail.content)
                if fixed != detail.content:
                    checkin_ops.update_answer(detail, fixed, actor=item.creator)

    def _bookmarks(self, project):
        """The bookmarks of the person whose token it is"""
        try:
            bookmarks = list(self.client.paginate("/my/bookmarks.json"))
        except api.NotFound:
            return
        for bookmark in bookmarks:
            recording = bookmark["recording"]
            item = self._find(recording["type"], recording["id"])
            if isinstance(item, Item) and item.project_id == project.pk:
                bookmark_ops.add_bookmark(self.actor, item=item)


class _Skip(Exception):
    """Leaves the transaction of one object without writing it"""


def schedule_of(schedule):
    """Basecamp's check-in schedule as (RRULE, first date, time of day)
    in the canonical form (``schedules.validate()``); ``ValueError`` for
    what we don't know"""
    start = dt.date.fromisoformat(schedule["start_date"])
    time_of_day = dt.time(schedule.get("hour", 0), schedule.get("minute", 0))
    days = [WEEKDAYS[int(day)] for day in schedule.get("days") or []]
    days = days or [WEEKDAYS[(start.weekday() + 1) % 7]]
    frequency = schedule["frequency"]
    if frequency == "every_day":
        everyday = len(days) in {0, 7} or not schedule.get("days")
        rule = "FREQ=DAILY" if everyday else f"FREQ=WEEKLY;BYDAY={','.join(days)}"
    elif frequency in {"every_week", "on_certain_days"}:
        rule = f"FREQ=WEEKLY;BYDAY={','.join(days)}"
    elif frequency == "every_other_week":
        rule = f"FREQ=WEEKLY;INTERVAL=2;BYDAY={','.join(days)}"
    elif frequency == "every_month":
        interval = schedule.get("month_interval") or 1
        if schedule.get("week_instance") is not None:
            rule = (
                f"FREQ=MONTHLY;INTERVAL={interval};BYDAY={days[0]};"
                f"BYSETPOS={schedule['week_instance']}"
            )
        elif start.day >= 29:
            rule = (
                f"FREQ=MONTHLY;INTERVAL={interval};BYMONTHDAY=28,29,30,31;BYSETPOS=-1"
            )
        else:
            rule = f"FREQ=MONTHLY;INTERVAL={interval};BYMONTHDAY={start.day}"
    else:
        raise ValueError(f"unknown frequency {frequency!r}")
    return schedules.validate(rule), start, time_of_day
