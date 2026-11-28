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
import time
from collections import Counter, defaultdict
from contextlib import contextmanager, suppress
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.db import DatabaseError, transaction
from django.db.models import Max
from django.utils import timezone, translation

from biwak import schedules
from biwak.accounts import operations as account_ops
from biwak.accounts.languages import language_for
from biwak.accounts.models import User
from biwak.activity import mentions
from biwak.activity.models import Action, Event, Subscription
from biwak.activity.notify import who_can_see
from biwak.activity.operations import importing, subscribe
from biwak.bookmarks import operations as bookmark_ops
from biwak.checkins import operations as checkin_ops
from biwak.checkins.models import Answer
from biwak.files import attachments, models as file_models, operations as file_ops
from biwak.files.models import Attachment, new_key
from biwak.files.titles import with_heading
from biwak.forwarding.models import ForwardedMail
from biwak.forwarding.operations import forwarded_line
from biwak.importer import client as api
from biwak.importer.convert import Resolver, plain_to_markdown, to_markdown
from biwak.importer.images import looks_generated
from biwak.importer.models import ImportedObject
from biwak.items import operations as ops
from biwak.items.models import (
    Comment,
    Group,
    Item,
    Kind,
    MessageCategory,
    Status,
    Todo,
    TodoList,
)
from biwak.organizations import activation, operations as org_ops
from biwak.organizations.models import Organization, normalize_name
from biwak.projects import operations as project_ops
from biwak.projects.models import Project


PERSON, PROJECT, ATTACHMENT = "Person", "Project", "Attachment"
# The internal twins of visible containers' lists and folders, and of
# their groups: "<type>::Internal" (``Importer._twin()``)
INTERNAL = "::Internal"
COMPANY = "Company"
GROUP, COLUMN = "Todolist::Group", "Kanban::Column"
# Project templates and the to-do list library's bucket (specs/templates.md)
TEMPLATE = "Template"
# The library's name, whatever Basecamp names its bucket: one library
# (decided 2026-11-22, specs/templates.md)
LIBRARY_NAME = "To-do list library"

# Our names for what the counts and problems talk about
KINDS = {
    "Project": "projects",
    "Template": "templates",
    "Person": "people",
    "Todolist": "lists",
    "Todolist::Group": "groups",
    "Todo": "to-dos",
    "Kanban::Board": "card tables",
    "Kanban::Column": "columns",
    "Kanban::Card": "cards",
    "Message": "messages",
    "Inbox::Forward": "email forwards",
    "Inbox::Reply": "replies to email forwards",
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

# What isn't imported when archived (the recordings' ``status`` filter works
# on the recordings of the project)
# Not "Question": /projects/recordings.json refuses it (400, checked
# 2026-11-22), so archived check-in questions aren't listed
ARCHIVED_SKIPPED = {
    "Message": "message",
    "Document": "doc",
    "Upload": "file",
}

# What is trashed in Biwak when trashed in Basecamp (decided 2026-11-28):
# the types the recordings' listing takes (not "Question", "Inbox::Forward";
# groups are "Todolist" there, but mapped as ``GROUP``), less comments, which
# Biwak can't trash
TRASHED = {
    "Todolist": "list",
    "Todo": "to-do",
    "Kanban::Card": "card",
    "Message": "message",
    "Vault": "folder",
    "Document": "doc",
    "Upload": "file",
    "Question::Answer": "check-in answer",
}

# Mappings whose object is made again when it was deleted in Biwak: not
# recordings (people, companies) and files in texts, which a text changed
# in Basecamp needs. Everything else deleted in Biwak isn't imported again
# (decided 2026-11-28).
REMADE = {PERSON, COMPANY, ATTACHMENT}

# Basecamp's weekdays, 0 is Sunday
WEEKDAYS = ["SU", "MO", "TU", "WE", "TH", "FR", "SA"]

# The kinds of ``/people.json`` entries that are the account's people
ACCOUNT_PEOPLE = {"User", "Client"}

# Basecamp projects never imported, whoever asks (decided 2026-11-22 by
# the user)
EXCLUDED = {24268932}

# Email forwards: messages in this category, created when missing (decided
# 2026-11-23 by the user)
FORWARDS_CATEGORY = ("Email forwards", "\N{INCOMING ENVELOPE}")

# Basecamp's sample people (its demo project's, example.com): never imported
SAMPLE = "DummyUser"


# Basecamp's colors of card table columns (bc3-api, "Change color of a
# column") and the nearest of the palette (specs/import-basecamp.md,
# decided 2026-11-23 by the user); white, none and unknown ones: no color.
# Yellow is the clients' amber's, which the palette leaves out.
BASECAMP_COLORS = {
    "red": "ember",
    "orange": "ember",
    "yellow": "moss",
    "green": "forest",
    "blue": "lake",
    "aqua": "glacier",
    "purple": "heather",
    "gray": "slate",
    "pink": "alpenglow",
    "brown": "bark",
}


def group_color(basecamp_color):
    """The palette name for a column's color, "" for none"""
    return BASECAMP_COLORS.get(basecamp_color or "", "")


class ImportRefused(Exception):
    """Something that must not be imported turned up; nothing more is
    written"""


class Report:
    """What a run did (or, in a dry run, would do)"""

    def __init__(self, *, dry_run):
        self.dry_run = dry_run
        self.counts = defaultdict(Counter)
        self.people = []  # the people created (or to create)
        # Inactive people who turn up in a project but aren't among the
        # account's people anymore: marked as having left (or, dry, to mark)
        self.left = []
        # Those marked so who are among the account's people again: cleared
        self.back = []
        self.images = []  # the people whose profile image was imported
        self.generated = []  # those whose image Basecamp generated: skipped
        self.problems = []
        self.archived = []  # archived recordings which aren't imported
        self.archived_projects = []  # archived in Basecamp after the import
        # Trashed in Basecamp since an earlier run: trashed (dry: to trash)
        self.trashed = []
        # Internal items inside containers visible to clients, which go
        # into internal containers of their own
        self.internal = []
        # Files over the upload limit: not imported, listed with where they
        # would have gone and their link in Basecamp
        self.too_large = []
        # Several tools of a kind, merged: "project, kind: titles"
        self.several = []
        # Tools switched off in Basecamp, not imported, with what's in them
        self.switched_off = []
        # Repeating to-dos imported before their schedules were, unchanged
        # since: the schedule added (or, dry, to add)
        self.schedules = []
        # Files "downloaded", "cached" (from the cache), "not redirected"
        # (not cacheable): the client's counts
        self.files = Counter()
        # JSON answers "cached" (from the cache): the client's counts
        self.answers = Counter()

    def as_text(self):
        lines = ["Dry run, nothing was written." if self.dry_run else "Imported."]
        for label in KINDS.values():
            if counts := self.counts.get(label):
                line = (
                    f"  {label}: {counts['created']} new, {counts['updated']} updated"
                )
                if counts["unchanged"]:
                    line += f", {counts['unchanged']} unchanged"
                if counts["deleted"]:
                    line += f", {counts['deleted']} deleted in Biwak"
                lines.append(line)
        if self.files["downloaded"] or self.files["cached"]:
            line = (
                f"  Files: {self.files['downloaded']} downloaded,"
                f" {self.files['cached']} from the cache"
            )
            if self.files["not redirected"]:
                line += (
                    f" ({self.files['not redirected']} answered without a"
                    " redirect, not cached)"
                )
            lines.append(line)
        if self.answers["cached"]:
            lines.append(f"  Basecamp answers: {self.answers['cached']} from the cache")
        limit = file_models.MAX_SIZE // 2**20
        sections = [
            (
                "People to create:" if self.dry_run else "People created inactive:",
                self.people,
            ),
            ("People who left Basecamp:", self.left),
            ("Back in Basecamp:", self.back),
            ("Profile images imported:", self.images),
            ("Profile images skipped, generated by Basecamp:", self.generated),
            ("Internal inside containers visible to clients, moved:", self.internal),
            (
                f"Too large to import (at most {limit} MB), put them elsewhere:",
                self.too_large,
            ),
            ("Several tools of a kind, merged:", self.several),
            (
                (
                    "Switched off in Basecamp, not imported (--include-disabled"
                    " imports them):"
                ),
                self.switched_off,
            ),
            (
                "Schedules to add to to-dos imported before:"
                if self.dry_run
                else "Schedules added to to-dos imported before:",
                self.schedules,
            ),
            (
                "Trashed in Basecamp, to trash here:"
                if self.dry_run
                else "Trashed in Basecamp, trashed here:",
                self.trashed,
            ),
            ("Archived in Basecamp, skipped:", self.archived),
            (
                "Projects to archive in Basecamp:"
                if self.dry_run
                else "Projects archived in Basecamp:",
                self.archived_projects,
            ),
            ("Problems:", self.problems),
        ]
        for heading, entries in sections:
            if entries:
                lines.append(heading)
                lines += [f"  {entry}" for entry in entries]
        return "\n".join(lines)


def parse_time(value):
    return dt.datetime.fromisoformat(value) if value else None


def comment_count(rec):
    """Recordings say ``comments_count``, cards ``comment_count``, email
    forwards ``replies_count`` (their replies are the comments)"""
    count = rec.get(
        "comments_count", rec.get("comment_count", rec.get("replies_count"))
    )
    return int(count) if count is not None else None


PROGRESS_EVERY = 25  # items between progress lines
TOOL_NAMES = {
    "todoset": "To-dos",
    "kanban_board": "Card table",
    "message_board": "Message board",
    "vault": "Docs & files",
    "questionnaire": "Check-ins",
    "inbox": "Email forwards",
}
# Where a tool is, for what's in it
TOOL_PATHS = {
    "todoset": "/todosets",
    "kanban_board": "/card_tables",
    "message_board": "/message_boards",
    "vault": "/vaults",
    "questionnaire": "/questionnaires",
    "inbox": "/inboxes",
}


def _amount(count, one, many):
    return f"{count} {one if count == 1 else many}"


def tool_contents(name, rec):
    """What's in a tool, from its own record ("2 lists, 5 to-dos"), empty
    when there's nothing"""
    match name:
        case "todoset":
            # "completed/all" to-dos
            total = int((rec.get("completed_ratio") or "0/0").partition("/")[2] or 0)
            amounts = [
                (rec.get("todolists_count") or 0, "list", "lists"),
                (total, "to-do", "to-dos"),
            ]
        case "kanban_board":
            cards = sum(
                column.get("cards_count") or 0 for column in rec.get("lists") or []
            )
            amounts = [(cards, "card", "cards")]
        case "message_board":
            amounts = [(rec.get("messages_count") or 0, "message", "messages")]
        case "vault":
            amounts = [
                (rec.get("vaults_count") or 0, "folder", "folders"),
                (rec.get("documents_count") or 0, "doc", "docs"),
                (rec.get("uploads_count") or 0, "file", "files"),
            ]
        case "questionnaire":
            amounts = [
                (rec.get("questions_count") or 0, "question", "questions"),
            ]
        case "inbox":
            amounts = [(rec.get("forwards_count") or 0, "forward", "forwards")]
    return ", ".join(_amount(*amount) for amount in amounts if amount[0])


# Not looked up yet (``Importer._mappings``)
UNKNOWN = object()


class Importer(Resolver):
    def __init__(
        self,
        client,
        *,
        actor,
        dry_run=False,
        since=None,
        full=False,
        include_disabled=False,
        archive=False,
        progress=None,
        clock=time.monotonic,
    ):
        """``actor``: the Biwak person running the import (staff), who
        creates the projects and owns the bookmarks; ``archive``: archive
        each project in Basecamp once it was imported; ``full``: read
        recordings unchanged since the last run too; ``include_disabled``:
        import tools switched off in Basecamp; ``progress``: called with a
        line of text while importing (the command prints them)"""
        self.client = client
        self._progress = progress
        self._clock = clock
        self._started = None
        self._items = 0
        self._project_name = ""
        self.actor = actor
        self.dry = dry_run
        self.since = since
        self.full = full
        self.include_disabled = include_disabled
        self.archive = archive
        # (Basecamp type, ID) of the recordings unchanged since the last run,
        # and of those created in this one
        self._skipped = set()
        self._created = set()
        # (Basecamp type, ID) of those deleted in Biwak: nothing in them is
        # imported either
        self._gone = set()
        self.report = Report(dry_run=dry_run)
        self.report.files = client.file_counts
        self.report.answers = client.answer_counts
        self._users = {}  # Basecamp person ID: User, or None
        # (Basecamp type, ID): ``ImportedObject``, None when not imported
        # (``_preload()``); for one project at a time, people's for the run
        self._mappings = {}
        # ({ID: User}, {address in upper case: User}), read once (``_people()``)
        self._everybody = None
        self._persons = {}  # Basecamp person ID: the person's record
        # The IDs of the account's people (``/people.json``), read once
        self._account_people = None
        self._own_company_ids = set()
        # Basecamp person IDs already compared with the account's people
        self._looked_at = set()
        self._today = timezone.localdate()
        self._people_by_sgid = {}
        self._imaged = set()  # Basecamp person IDs whose image was looked at
        # While converting a text: its project, author and file entries
        self._text = None
        # The list or card table being imported, and the internal lists made
        # for them in this run
        self._container = None
        self._container_is_board = False
        self._container_project = None
        self._internal_lists = {}
        # (Basecamp type, ID) of the group or column being imported, for its
        # twin in the internal list
        self._group_key = None

    # Reporting -----------------------------------------------------------

    def problem(self, message):
        self.report.problems.append(message)

    def _too_large(self, name, size, where, url):
        """Records a file over the upload limit (``size`` in bytes, None when
        unknown before downloading); True when it is one"""
        if size is not None and size <= file_models.MAX_SIZE:
            return False
        megabytes = f"{size / 2**20:.0f} MB, " if size else ""
        self.report.too_large.append(f"{name} ({megabytes}in {where}): {url}")
        return True

    def _count(self, bc_type, what):
        self.report.counts[KINDS.get(bc_type, bc_type)][what] += 1
        self._items += 1
        if self._items % PROGRESS_EVERY == 0:
            self.say(f"    {self._items} items, {self._so_far()}")

    def say(self, line):
        if self._progress is not None:
            self._progress(line)

    def _so_far(self):
        seconds = int(self._clock() - (self._started or self._clock()))
        cached = self.client.answer_counts["cached"]
        return (
            f"{self.client.request_count} requests,"
            + (f" {cached} answers from the cache," if cached else "")
            + f" {seconds // 60}m {seconds % 60:02d}s"
        )

    # The mapping -----------------------------------------------------------

    def _find(self, bc_type, bc_id):
        """The Biwak object of a Basecamp ID, or None (also when it was
        deleted since)"""
        return self._mapping(bc_type, bc_id)[1]

    def _preload(self, bc_type, records):
        """The mappings of a listing's records, with one query instead of
        one per record (decided 2026-11-23: the import may run against
        production through a tunnel). Kept in ``_mappings`` for the
        project: None for what wasn't imported, ``_remember()`` keeps it
        up to date."""
        ids = {
            rec["id"] for rec in records if (bc_type, rec["id"]) not in self._mappings
        }
        if not ids:
            return
        self._mappings |= dict.fromkeys(((bc_type, bc_id) for bc_id in ids), None)
        for mapped in ImportedObject.objects.filter(
            basecamp_type=bc_type, basecamp_id__in=ids
        ):
            self._mappings[bc_type, mapped.basecamp_id] = mapped

    def _forget_mappings(self):
        """Before the next project: only the people's are kept"""
        self._mappings = {
            key: mapped for key, mapped in self._mappings.items() if key[0] == PERSON
        }

    def _mapping(self, bc_type, bc_id):
        """(``ImportedObject``, its Biwak object), or (None, None). The
        object is read from the database each time, the mapping only once
        per project."""
        key = (bc_type, bc_id)
        if key in self._mappings:
            mapped = self._mappings[key]
        else:
            mapped = self._mappings[key] = ImportedObject.objects.filter(
                basecamp_type=bc_type, basecamp_id=bc_id
            ).first()
        if mapped is None:
            return None, None
        if mapped.deleted_at is not None:
            return mapped, None
        model = ContentType.objects.get_for_id(mapped.content_type_id).model_class()
        target = model._base_manager.filter(pk=mapped.object_id).first()
        if target is None and bc_type in REMADE:
            mapped.delete()
            self._mappings[key] = None
            return None, None
        if target is None:
            # Deleted in Biwak: never imported again (decided 2026-11-28)
            mapped.deleted_at = timezone.now()
            if not self.dry:
                mapped.save(update_fields=["deleted_at"])
        return mapped, target

    def _remember(self, bc_type, bc_id, obj):
        key = (bc_type, bc_id)
        fields = {
            "content_type": ContentType.objects.get_for_model(obj),
            "object_id": obj.pk,
            "imported_at": timezone.now(),
        }
        mapped = self._mappings.get(key, UNKNOWN)
        if mapped is UNKNOWN:
            mapped, _created = ImportedObject.objects.update_or_create(
                basecamp_type=bc_type, basecamp_id=bc_id, defaults=fields
            )
        elif mapped is None:
            mapped = ImportedObject.objects.create(
                basecamp_type=bc_type, basecamp_id=bc_id, **fields
            )
        else:
            for name, value in fields.items():
                setattr(mapped, name, value)
            mapped.save(update_fields=list(fields))
        self._mappings[key] = mapped

    def _upsert(self, bc_type, rec, *, create, update=None, follow=False):
        """Creates the Biwak object of the recording or updates the one
        imported before; in a dry run only counts. Each in a transaction
        of its own with the mapping, so an interrupted run continues.

        One unchanged since the last run (``updated_at`` and comment count
        as stored, not ``--full``) isn't updated. ``follow``: the caller
        fetches its comments and subscribers with ``_follow()``, which
        stores its state once they're done; otherwise it is stored here."""
        mapped, found = self._mapping(bc_type, rec["id"])
        if mapped is not None and found is None:
            self._count(bc_type, "deleted")
            self._gone.add((bc_type, rec["id"]))
            return None
        if found is not None and self._unchanged(mapped, rec):
            self._count(bc_type, "unchanged")
            self._skipped.add((bc_type, rec["id"]))
            return found
        self._count(bc_type, "updated" if found else "created")
        if self.dry:
            return found
        with transaction.atomic():
            if found is None:
                found = create()
                self._remember(bc_type, rec["id"], found)
                self._created.add((bc_type, rec["id"]))
            elif update is not None:
                update(found)
            if not follow:
                self._settle(bc_type, rec)
        return found

    def _unchanged(self, mapped, rec):
        """Whether the recording is as when it was last read completely"""
        updated = parse_time(rec.get("updated_at"))
        return (
            not self.full
            and updated is not None
            and mapped.basecamp_updated_at == updated
            and mapped.basecamp_comments_count == comment_count(rec)
        )

    def _settle(self, bc_type, rec):
        """Stores the state of the recording, read completely now"""
        if self.dry:
            return
        state = {
            "basecamp_updated_at": parse_time(rec.get("updated_at")),
            "basecamp_comments_count": comment_count(rec),
        }
        ImportedObject.objects.filter(
            basecamp_type=bc_type, basecamp_id=rec["id"]
        ).update(**state)
        if mapped := self._mappings.get((bc_type, rec["id"])):
            for name, value in state.items():
                setattr(mapped, name, value)

    def _follow(
        self,
        bc_type,
        rec,
        item,
        *,
        comments=True,
        subscriptions=True,
        replies=None,
        settle=True,
    ):
        """The comments and subscribers of a recording (two requests), not
        for one unchanged since the last run; then its state is stored,
        unless ``--since`` skipped older comments (found 2026-11-28: they
        came only with ``--full``). ``replies``: where an email forward's
        replies are, its comments. Whether it was read completely;
        ``settle=False`` leaves storing that to the caller."""
        if (bc_type, rec["id"]) in self._skipped | self._gone:
            return False
        complete = True
        if replies:
            complete = self._comments(rec, item, path=replies, bc_type="Inbox::Reply")
        elif comments:
            complete = self._comments(rec, item)
        if subscriptions and item is not None:
            self._subscriptions(rec, item)
        done = item is not None and complete
        if done and settle:
            self._settle(bc_type, rec)
        return done

    def _skip(self, rec):
        """``--since``: what wasn't changed since isn't looked at again"""
        updated = parse_time(rec.get("updated_at"))
        return bool(self.since and updated and updated < self.since)

    # People ------------------------------------------------------------------

    def _user(self, person):
        """The Biwak person of a Basecamp person: by the mapping, by email
        address, or created (staff or client as in Basecamp; own staff
        active in Basecamp active, everybody else inactive).
        None in a dry run for people who would be created."""
        if not person:
            return None
        pid = person["id"]
        if pid in self._users:
            return self._users[pid]
        self._persons[pid] = person
        user = self._known_person(pid)
        if user is None:
            user = self._match_or_create(person)
            if user is not None and not self.dry:
                self._remember(PERSON, pid, user)
        self._users[pid] = user
        return user

    def _match_or_create(self, person):
        if person.get("personable_type") == SAMPLE:
            raise ImportRefused(
                f"{person.get('name')} (Basecamp ID {person['id']}) is one of"
                " Basecamp's sample people: nothing of them is imported"
            )
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
        user = self._people()[1].get(email.upper())
        if user is not None:
            return user
        client = bool(person.get("client"))
        company = (person.get("company") or {}).get("name", "")
        # Basecamp's employees are the account's own company; other staff
        # ("collaborators") are externals (specs/organizations.md)
        external = not client and not person.get("employee", True)
        kind = "client" if client else "external" if external else "staff"
        # Own staff active in Basecamp can work in Biwak at once; clients
        # and externals wait to be activated (decided 2026-11-22)
        active = kind == "staff" and not redacted and self._active_in_basecamp(person)
        # Without a company (people removed from Basecamp have none) the
        # address's domain decides, as for invitations (decided 2026-11-23)
        by_domain = (
            self._organization_by_domain(email)
            if (client or external) and not company
            else None
        )
        if by_domain is not None and by_domain.is_own and external:
            kind = "staff"
        label = f"{name} <{email}> ({kind}{', active' if active else ''}"
        label += f"{', ' + company if company else ''}"
        label += f"{', ' + by_domain.name + ' by the address' if by_domain else ''})"
        self.report.people.append(label)
        if self.dry:
            return None
        if by_domain is not None:
            organization = by_domain
        elif client or external:
            organization = self._organization(person.get("company") or {})
        else:
            organization = Organization.objects.own()
        user = User.objects.create_user(
            email,
            full_name=name,
            is_client=client,
            organization=organization,
            is_active=active,
        )
        by_pk, by_email = self._people()
        by_pk[user.pk] = user
        by_email.setdefault(user.email.upper(), user)
        return user

    def _people(self):
        """Everybody, by ID and by address (``iexact`` compares in upper
        case; the first by ID when two differ only in case), and the
        mapping of the Basecamp people imported before: read once per run
        (decided 2026-11-23), instead of a few queries per person"""
        if self._everybody is None:
            by_pk, by_email = {}, {}
            for user in User.objects.order_by("pk"):
                by_pk[user.pk] = user
                by_email.setdefault(user.email.upper(), user)
            self._everybody = by_pk, by_email
            for mapped in ImportedObject.objects.filter(basecamp_type=PERSON):
                self._mappings[PERSON, mapped.basecamp_id] = mapped
        return self._everybody

    def _known_person(self, pid):
        """The Biwak person a Basecamp person was imported as, or None"""
        by_pk = self._people()[0]
        mapped = self._mappings.setdefault((PERSON, pid), None)
        if mapped is None:
            return None
        user = by_pk.get(mapped.object_id)
        if user is None:
            # Deleted since
            mapped.delete()
            self._mappings[PERSON, pid] = None
        return user

    def _active_in_basecamp(self, person):
        """Still among the account's people, not a removed one's tombstone"""
        if person.get("personable_type") == "Tombstone":
            return False
        return person["id"] in self._account_ids()

    def _account_ids(self):
        """The IDs of the account's people, read once per run. ``/people.json``
        also lists removed people (``Tombstone``), people from outside
        (``Outsider``) and placeholders (``DummyUser``, ``Integration``):
        only users are in the account (checked 2026-11-22)."""
        self._read_account()
        return self._account_people

    def _own_companies(self):
        """The Basecamp IDs of the account's own company: its employees'"""
        self._read_account()
        return self._own_company_ids

    def _read_account(self):
        if self._account_people is not None:
            return
        people = [
            person
            for person in self.client.paginate("/people.json")
            if person.get("personable_type", "User") in ACCOUNT_PEOPLE
        ]
        self._account_people = {person["id"] for person in people}
        self._own_company_ids = {
            person["company"]["id"]
            for person in people
            if person.get("employee") and (person.get("company") or {}).get("id")
        }

    def _people_who_left(self):
        """Inactive people (created by an import, or deactivated) imported
        from the account who aren't among its people anymore have left:
        ``left_at`` is the run's date (specs/activation.md). Those marked so
        who are among them again are back: ``left_at`` is cleared (decided
        2026-11-22). The account's people are read once per run; inactive
        people still in the account wait to be activated, active ones
        aren't touched.

        Everybody imported before counts, not only the people met in this
        run (fixed 2026-11-28): later runs skip unchanged recordings, so
        somebody met only on those in a run that stopped halfway would never
        be looked at again."""
        self._account_ids()
        by_pk = self._people()[0]
        people = {
            pid: by_pk[mapped.object_id]
            for (bc_type, pid), mapped in self._mappings.items()
            if bc_type == PERSON and mapped is not None and mapped.object_id in by_pk
        }
        # Met in this run (created now, or would be in a dry run)
        people.update(self._users)
        new = [pid for pid in people if pid not in self._looked_at]
        self._looked_at.update(new)
        # Somebody removed and added again comes back with a new Basecamp
        # ID, the old one a tombstone: among the account's people under any
        # of their IDs, they haven't left (found 2026-11-28: marked left and
        # cleared in every run)
        present = {
            user.pk
            for pid, user in people.items()
            if user is not None and pid in self._account_people
        }
        gone, back = {}, {}
        for pid in new:
            user = people[pid]
            if pid in self._account_people:
                # Once per person
                if user is None or user not in back.values():
                    back[pid] = user
            elif user is None or user.pk not in present:
                gone[pid] = user
        users = [user for user in gone.values() if user is not None]
        if self.dry:
            marked = {
                user.pk for user in users if not user.is_active and user.left_at is None
            }
        else:
            marked = {user.pk for user in activation.mark_left(users, on=self._today)}
        for pid, user in gone.items():
            # In a dry run, people who would be created would also have left
            if (user is None and self.dry) or (user is not None and user.pk in marked):
                self.report.left.append(self._label(pid, user))
        users = [user for user in back.values() if user is not None]
        if self.dry:
            cleared = {
                user.pk
                for user in users
                if not user.is_active
                and user.left_at is not None
                and user.left_in_basecamp
            }
        else:
            cleared = {user.pk for user in activation.clear_left(users)}
        for pid, user in back.items():
            if user is not None and user.pk in cleared:
                self.report.back.append(self._label(pid, user))

    def _label(self, pid, user):
        """ "Name <address>" of a Basecamp person, the Biwak person's if any"""
        if user is None:
            person = self._persons[pid]
            name, email = person.get("name"), person.get("email_address")
        else:
            name, email = user.get_full_name(), user.email
        return f"{name or pid} <{email}>"

    def _image(self, person, user):
        """The person's profile image, once: only for people without one
        (never overwriting what was set in Biwak), and not what Basecamp
        generated (``looks_generated``). ``people.json`` has no
        ``avatar_url``, so the person is fetched. A dry run fetches
        nothing."""
        if self.dry or user is None or user.image or person["id"] in self._imaged:
            return
        self._imaged.add(person["id"])
        name = user.get_full_name() or person.get("name") or user.email
        try:
            data = self._avatar(person)
            generated = data is not None and looks_generated(data)
            if data is not None and not generated:
                account_ops.store_image(user, data)
        except (api.NotFound, api.ApiError, account_ops.InvalidImage, OSError) as exc:
            self.problem(f"Profile image of {name} not imported: {exc}")
            return
        if generated:
            self.report.generated.append(name)
        elif data is not None:
            self.report.images.append(name)

    def _avatar(self, person):
        """The bytes of the person's image, None without one"""
        rec = self.client.get(f"/people/{person['id']}.json")
        if not rec.get("avatar_url"):
            return None
        # Not cached: the URL is the person's, whatever the image
        return self.client.download(
            rec["avatar_url"], accept="image/png, image/webp", cache=False
        )

    def _organization(self, company):
        """Basecamp's company as an organization: the one it was imported as
        before (merges move that, ``organizations.operations.merge()``), else
        by name (ignoring case and spaces, like the migration from texts),
        else a new one. Never the own organization, which only admins give
        people: the account's own company (its employees', whatever either
        is called, decided 2026-11-22) and a company named like the own
        organization give none."""
        cid = company.get("id")
        name = normalize_name(company.get("name") or "")
        if cid is not None and cid in self._own_companies():
            return None
        found = self._find(COMPANY, cid) if cid is not None else None
        if found is None and name:
            found = Organization.objects.named(name)
            if found is None:
                found = Organization.objects.create(name=name)
        if found is None or found.is_own:
            return None
        if cid is not None:
            self._remember(COMPANY, cid, found)
        return found

    def _organization_by_domain(self, email):
        """The organization whose domains include the address's (free-mail
        domains never match), if the importing person may put people there
        (``org_ops.can_touch()``, as invitations: the own and external
        organizations only for admins)"""
        org = org_ops.for_new_person(email)
        if org is not None and not org_ops.can_touch(self.actor, org):
            return None
        return org

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

    def _done(self, bc_type, bc_id):
        """The mapping of a project (or template) and its ``done``, to
        note what isn't done again; (None, {}) in a dry run of a new one"""
        mapped, _found = self._mapping(bc_type, bc_id)
        return mapped, (mapped.done if mapped is not None else {})

    def _members(self, rec, project, people):
        """Basecamp's people of the project become members once each
        (decided 2026-11-28, verification round 2: every run added
        everybody again, also who was removed in Biwak since). Noted per
        person on the project's mapping, so a run stopped among them goes
        on. The first import's are added at the project's creation by who
        imports, as before; people new in Basecamp later by nobody, now,
        as the import's (Basecamp doesn't say who added them, or when).
        Projects imported before this was noted: everybody once more."""
        mapped, done = self._done(PROJECT, rec["id"])
        members = set(done.get("members", ()))
        first = not done.get("members_complete")
        for person in people:
            user = self._user(person)
            self._image(person, user)
            if user is None or project is None or self.dry or mapped is None:
                continue
            if person["id"] in members:
                continue
            # Inactive people too (``importing()``): once somebody
            # activates them they are members
            with transaction.atomic():
                if first:
                    with importing(at=parse_time(rec["created_at"])):
                        project_ops.add_member(project, user, actor=self.actor)
                else:
                    with importing(noted="basecamp"):
                        project_ops.add_member(project, user, actor=None)
                members.add(person["id"])
                mapped.done = mapped.done | {"members": sorted(members)}
                mapped.save(update_fields=["done"])
        if first and mapped is not None and not self.dry:
            mapped.done = mapped.done | {"members_complete": True}
            mapped.save(update_fields=["done"])

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
        if entry is None:
            return None
        name = entry.get("filename") or "file"
        where = f"a text in {self._project_name}"
        url = entry.get("download_url", "")
        if self._too_large(name, entry.get("byte_size") or 0, where, url):
            return f"{name} (not imported: too large)"
        if self.dry or text["project"] is None:
            return None
        known = self._find(ATTACHMENT, entry["id"])
        if known is None:
            try:
                data = self.client.download(entry["download_url"])
            except (api.NotFound, api.ApiError, KeyError) as exc:
                self.problem(f"File {entry.get('filename')} not downloaded: {exc}")
                return None
            try:
                known = attachments.upload(
                    project=text["project"],
                    file=ContentFile(data, name=name),
                    uploaded_by=text["author"],
                )
            except attachments.UploadError:
                self._too_large(name, None, where, url)
                return f"{name} (not imported: too large)"
            self._remember(ATTACHMENT, entry["id"], known)
            self._count(ATTACHMENT, "created")
        else:
            known = self._own_attachment(known, text)
        bang = "!" if known.is_image else ""
        return f"{bang}[{known.name}](attachment:{known.key})"

    def _own_attachment(self, known, text):
        """The row of a file imported before for the text's item: texts
        show only their own item's attachments, so a file in texts of
        several items (or projects) gets a row per item, sharing the stored
        file, which goes with its last row (specs/files.md; found
        2026-11-28: the second text showed a plain "attachment"). A new
        item's (``text["item"]`` None) is linked by the operation creating
        it, as the author's upload."""
        item, author = text["item"], text["author"]
        if item is not None and known.item_id == item.pk:
            self._count(ATTACHMENT, "updated")
            return known
        if (
            known.item_id is None
            and known.uploaded_by_id == (author.pk if author else None)
            and known.project_id == text["project"].pk
        ):
            # Not linked yet: the text being converted (or the one before
            # it, for the same new item) has it
            self._count(ATTACHMENT, "updated")
            return known
        if item is not None and (
            found := Attachment.objects.filter(item=item, file=known.file.name).first()
        ):
            self._count(ATTACHMENT, "updated")
            return found
        self._count(ATTACHMENT, "created")
        return Attachment.objects.create(
            project=text["project"],
            item=item,
            key=new_key(),
            file=known.file.name,
            name=known.name,
            size=known.size,
            content_type=known.content_type,
            uploaded_by=author,
        )

    def _link(self, item, text, author):
        """Links the files of a text changed in Basecamp: the operations link
        their actor's uploads, and Basecamp's changes name nobody, while the
        files were uploaded as ``author`` (``_md()``); unlinked, the cleanup
        deleted them a day later (found 2026-11-28)"""
        attachments.link(item, text, actor=author)

    def _md(self, html, rec_attachments, *, project, author, item=None, plain=False):
        """Markdown of a Basecamp text; files in it are downloaded and
        uploaded as ``author``, who saves the text next. ``item``: the
        text's item, None for one not created yet. ``plain``: a forwarded
        mail's plain lines"""
        self._text = {
            "attachments": rec_attachments or [],
            "project": project,
            "author": author,
            "item": item,
        }
        try:
            text = (plain_to_markdown if plain else to_markdown)(html, self)
        finally:
            self._text = None
        # Links to recordings keep Basecamp's address: shown leading to the
        # import (biwak/importer/links.py)
        return text

    # A run --------------------------------------------------------------------------

    def run(self, project_id):
        """Imports one project; returns the report"""
        if self._started is None:
            self._started = self._clock()
        self._items = 0
        self._forget_mappings()
        rec = self.client.get(f"/projects/{project_id}.json")
        self._project_name = rec["name"]
        if int(project_id) in EXCLUDED:
            self.problem(
                f"Skipped {rec['name']} ({project_id}): excluded from importing"
            )
            return self.report
        archived = ", archived" if rec.get("status") == "archived" else ""
        self.say(f"{rec['name']} ({project_id}{archived})")
        people = list(self.client.paginate(f"/projects/{project_id}/people.json"))
        if any(person.get("personable_type") == SAMPLE for person in people):
            # Basecamp's demo: made-up people and content
            self.problem(
                f"Skipped {rec['name']} ({project_id}): Basecamp's sample"
                " project, its people are made up"
            )
            return self.report
        with importing(), self._recomputing():
            project = self._project(rec)
            if (PROJECT, rec["id"]) in self._gone:
                self.problem(
                    f"Skipped {rec['name']} ({project_id}): deleted in Biwak, not"
                    " imported again"
                )
                return self.report
            self.say(f"  {len(people)} people")
            for person in people:
                self._people_by_sgid[person.get("attachable_sgid")] = person["id"]
            self._members(rec, project, people)
            self._dock(rec, project)
            self._finish(project_id, project)
        if self.archive and rec.get("status") != "archived":
            # Only reached when the import went through: a failure raises
            if not self.dry:
                self.client.archive_project(project_id)
            self.report.archived_projects.append(rec["name"])
        self.say(f"  done: {self._items} items, {self._so_far()}")
        return self.report

    @contextmanager
    def _recomputing(self):
        """Events recorded while importing don't touch the projects' activity
        times (one UPDATE each); ``_finish()`` recomputes them, and so does
        an import stopping halfway, so they are as far as it got (decided
        2026-11-23)"""
        try:
            yield
        except BaseException:
            if not self.dry:
                # Not hiding why it stopped (a connection gone, say)
                with suppress(DatabaseError):
                    project_ops.recompute_activity()
            raise

    def _finish(self, bucket_id, project):
        """What follows a project's or template's tools"""
        self._trashed_recordings(bucket_id)
        self._archived_recordings(bucket_id)
        if not self.dry:
            self._bookmarks(project)
            project_ops.recompute_activity()
        self._people_who_left()

    def run_templates(self):
        """Basecamp's project templates and its to-do list library, as
        templates (specs/templates.md): served like projects, a bucket with
        a dock each, the library ``{bucket, todolists}``. No members:
        templates have none. Returns the report."""
        if self._started is None:
            self._started = self._clock()
        templates = list(self.client.paginate("/templates.json"))
        for number, listed in enumerate(templates, 1):
            rec = listed
            if "dock" not in listed:
                rec = self.client.get(f"/templates/{listed['id']}.json")
            self._items = 0
            self._forget_mappings()
            self._project_name = rec["name"]
            self.say(f"Template [{number}/{len(templates)}] {rec['name']}")
            with importing(), self._recomputing():
                template = self._template(rec)
                if (TEMPLATE, rec["id"]) in self._gone:
                    continue
                self._dock(rec, template)
                self._finish(rec["id"], template)
            self.say(f"  done: {self._items} items, {self._so_far()}")
        try:
            library = self.client.get("/template_library/todolists.json")
        except api.NotFound:
            library = None
        if library and library.get("todolists"):
            bucket = library.get("bucket") or {}
            rec = {
                "id": bucket["id"],
                "name": LIBRARY_NAME,
                "description": bucket.get("description") or "",
                "created_at": bucket.get("created_at"),
                "updated_at": bucket.get("updated_at"),
            }
            self._items = 0
            self._forget_mappings()
            self._project_name = rec["name"]
            self.say(f"The to-do list library ({len(library['todolists'])} lists)")
            with importing(), self._recomputing():
                template = self._template(rec)
                if (TEMPLATE, rec["id"]) in self._gone:
                    return self.report
                for list_rec in sorted(
                    library["todolists"], key=lambda r: r.get("position", 0)
                ):
                    self._todolist(list_rec, template)
                self._finish(rec["id"], template)
            self.say(f"  done: {self._items} items, {self._so_far()}")
        return self.report

    def _template(self, rec):
        """A template of a Basecamp template or the library's bucket"""

        def create():
            template = project_ops.create_template(
                name=rec["name"],
                description=rec.get("description") or "",
                actor=self.actor,
            )
            if created_at := parse_time(rec.get("created_at")):
                Project.objects.filter(pk=template.pk).update(created_at=created_at)
            return template

        def update(template):
            with self._from_basecamp(rec):
                project_ops.update_project(
                    template,
                    actor=None,
                    name=rec["name"],
                    description=rec.get("description") or "",
                )

        template = self._upsert(TEMPLATE, rec, create=create, update=update)
        if (TEMPLATE, rec["id"]) in self._created:
            # Only at the first import, like projects (decided 2026-11-28)
            self._archived(template, rec)
        return template

    def _trashed_recordings(self, bucket_id):
        """What was trashed in Basecamp since it was imported is trashed in
        Biwak (decided 2026-11-28), as Basecamp's change, once: restoring it
        in Biwak sticks. Basecamp's listings leave trashed recordings out;
        the recordings' listing has them with ``status=trashed``."""
        for bc_type, label in TRASHED.items():
            try:
                found = list(
                    self.client.paginate(
                        "/projects/recordings.json",
                        type=bc_type,
                        bucket=bucket_id,
                        status="trashed",
                    )
                )
            except api.NotFound:
                continue
            self._preload(bc_type, found)
            for rec in found:
                mapped, item = self._mapping(bc_type, rec["id"])
                if item is None or mapped.trashed_at is not None:
                    continue
                trash = item.status != Status.TRASHED
                if trash:
                    self.report.trashed.append(f"{label}: {item.title}")
                if self.dry:
                    continue
                with transaction.atomic():
                    if trash:
                        with self._from_basecamp(rec):
                            ops.trash(item, actor=None)
                    mapped.trashed_at = timezone.now()
                    mapped.save(update_fields=["trashed_at"])

    def _archived_recordings(self, project_id):
        """Archived messages, docs, files and questions aren't imported
        (specs/archiving.md); the report lists the messages, docs and files,
        in a dry run too (Basecamp doesn't list archived questions there)"""
        for bc_type, label in ARCHIVED_SKIPPED.items():
            try:
                found = list(
                    self.client.paginate(
                        "/projects/recordings.json",
                        type=bc_type,
                        bucket=project_id,
                        status="archived",
                    )
                )
            except api.NotFound:
                continue
            for rec in found:
                title = rec.get("title") or rec.get("subject") or str(rec["id"])
                self.report.archived.append(f"{label}: {title}")

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
            with self._from_basecamp(rec):
                project_ops.update_project(
                    project,
                    actor=None,
                    name=rec["name"],
                    description=rec.get("description") or "",
                    is_all_access=bool(rec.get("all_access", True)),
                )

        project = self._upsert(PROJECT, rec, create=create, update=update)
        if (PROJECT, rec["id"]) in self._created:
            # Archived only at the first import, both ways (decided
            # 2026-11-28): after ``--archive`` Basecamp says so of the
            # project people work in, and archiving in Biwak sticks
            self._archived(project, rec)
        return project

    def _archived(self, project, rec):
        """A new project or template archived as in Basecamp, by nobody at
        its time"""
        if rec.get("status") == "archived":
            with self._from_basecamp(rec):
                project_ops.archive_project(project, actor=None)

    def _dock(self, rec, project):
        """The tools we import (the schedule, chat and pings aren't); switched-off ones only with ``include_disabled``, otherwise
        the report tells what's in them"""
        tools = []
        for tool in rec.get("dock", []):
            if tool["name"] not in TOOL_NAMES:
                continue
            if tool.get("enabled") or self.include_disabled:
                tools.append(tool)
            else:
                self._switched_off(tool)
        self._several(tools)
        for tool in tools:
            self.say(f"  {TOOL_NAMES[tool['name']]}")
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
                case "inbox":
                    self._inbox(rec["id"], tool["id"], project)

    def _several(self, tools):
        """Several tools of a kind are merged; the report names them"""
        by_kind = defaultdict(list)
        for tool in tools:
            by_kind[tool["name"]].append(tool.get("title") or str(tool["id"]))
        for name, titles in by_kind.items():
            if len(titles) > 1:
                self.report.several.append(
                    f"{self._project_name}, {TOOL_NAMES[name]}: "
                    + ", ".join(f'"{title}"' for title in titles)
                )

    def _switched_off(self, tool):
        """What's in a tool switched off in Basecamp, with one request; the
        report lists those which aren't empty"""
        name, tool_id = tool["name"], tool["id"]
        try:
            rec = self.client.get(f"{TOOL_PATHS[name]}/{tool_id}.json")
        except (api.NotFound, api.ApiError) as exc:
            self.problem(
                f"Switched-off tool {tool.get('title')!r} ({tool_id}) in"
                f" {self._project_name} not checked: {exc}"
            )
            return
        contents = tool_contents(name, rec)
        if contents:
            self.report.switched_off.append(
                f'{self._project_name}, {TOOL_NAMES[name]} "{tool.get("title")}":'
                f" {contents}"
            )

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

    def _parent_gone(self, parent, nested):
        """Whether the folder something goes into was deleted in Biwak (a
        dry run has none for what it would create)"""
        return nested and parent is None and not self.dry

    def _internal_list(self, todo_rec, group, creator):
        """The internal list "<list> (internal)" of the list (or card
        table) being imported, and the group of that title in it (created
        when needed; in a dry run None for what doesn't exist)"""
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
        return item, self._internal_group(item, group)

    def _internal_group(self, item, group):
        """The twin of the group being imported in the internal list ``item``:
        by its mapping, so a group renamed in Basecamp isn't doubled (found
        2026-11-28); by its title for twins made before they had one; made
        when missing. None (ungrouped) when deleted in Biwak."""
        bc_type, bc_id = self._group_key
        mapped, found = self._mapping(bc_type + INTERNAL, bc_id)
        if mapped is not None and found is None:
            return None
        if found is None:
            found = item.todolist.groups.filter(title=group.title).first()
            if found is None and not self.dry:
                found = ops.create_group(
                    todolist=item.todolist, title=group.title, color=group.color
                )
            if found is not None and not self.dry:
                self._remember(bc_type + INTERNAL, bc_id, found)
        return found

    def _rename_twin(self, bc_type, rec, **fields):
        """The internal twin of a visible list, card table or folder (its
        group, column) renamed in Basecamp follows it (found 2026-11-28:
        it kept the old name), as Basecamp's change"""
        twin = self._find(bc_type + INTERNAL, rec["id"])
        if twin is None:
            return
        if isinstance(twin, Group):
            ops.update_group(twin, title=rec["title"], **fields)
            return
        title = f"{rec['title']} (internal)"
        with self._from_basecamp(rec):
            if twin.kind == Kind.FOLDER:
                file_ops.update_folder(twin, actor=None, title=title)
            else:
                ops.update_list(twin, actor=None, title=title)

    def _touch(self, bc_type, rec):
        """Whether what ``_upsert()`` returned for the recording may be
        written on (its visibility, completion, assignees, archiving, times):
        not in a dry run (found 2026-11-28: it wrote on what was imported
        before), and not when it was skipped as unchanged since the last
        run, which may have been changed in Biwak since and isn't touched at
        all (decided 2026-11-28: Biwak's change stays; found 2026-11-27:
        every rerun reset their times)"""
        return not self.dry and (bc_type, rec["id"]) not in self._skipped

    def _restamp(self, bc_type, item, rec):
        """``_stamp()`` after ``_upsert()``, not for what it skipped"""
        if self._touch(bc_type, rec):
            self._stamp(item, rec)

    def _stamp(self, item, rec):
        """The original times; the operations wrote now"""
        Item.objects.filter(pk=item.pk).update(
            created_at=parse_time(rec["created_at"]),
            updated_at=parse_time(rec.get("updated_at") or rec["created_at"]),
        )

    def _from_basecamp(self, rec):
        """A change brought over from Basecamp: at its time, without a
        person, noted as the import's (``importing(noted=)``). Basecamp says
        when a recording changed, never who changed it; in the creator's
        name, a to-do's creator who had left months before "edited" it
        (decided 2026-11-28)."""
        return importing(at=parse_time(rec.get("updated_at")), noted="basecamp")

    def _top_visibility(self, item, visible, rec):
        """What the operations created is visible as the creator is a
        client (messages); the importer sets what Basecamp had"""
        item.refresh_from_db()
        if item.has_switch and item.visible_to_clients != visible:
            # Undoing a switch in Biwak (``--full``: switching doesn't
            # change ``updated_at``) happens now, as for completions
            when = parse_time(rec.get("updated_at"))
            if self._undoes_biwak(item, [Action.VISIBILITY_CHANGED], when):
                changing = importing(at=timezone.now(), noted="basecamp")
            else:
                changing = self._from_basecamp(rec)
            with changing:
                ops.set_visibility(item, visible=visible, actor=None)

    def _status(self, item, rec):
        """Lists stay archived (to-dos are completed, not archived)"""
        archived = rec.get("status") == "archived"
        with self._from_basecamp(rec):
            if archived and item.status == Status.ACTIVE:
                ops.archive(item, actor=None)
            elif not archived and item.status == Status.ARCHIVED:
                ops.unarchive(item, actor=None)

    def _comments(self, rec, item, *, path=None, bc_type="Comment"):
        """``path`` and ``bc_type``: an email forward's replies. Whether
        all were read (``--since`` skips older ones)."""
        if self.since and self._skip(rec):
            return False
        count = comment_count(rec)
        if count == 0:
            return True
        path = path or f"/recordings/{rec['id']}/comments.json"
        try:
            # The listing may be fresher than the comments' cached answer
            # (``--answers-max-age``): changed after it, or with a count it
            # doesn't have, they're read again (found 2026-11-28: a comment
            # added in between was missed, the fresh count stored)
            comments = list(
                self.client.paginate(path, newer_than=parse_time(rec.get("updated_at")))
            )
            if count is not None and len(comments) != count:
                comments = list(self.client.paginate(path, newer_than=timezone.now()))
        except api.NotFound:
            return True
        self._preload(bc_type, comments)
        complete = True
        for comment in comments:
            if self._skip(comment):
                # Only one that isn't in Biwak as it is in Basecamp leaves
                # the recording unread (found 2026-11-28, round 2: those
                # imported before did too, so every later run took the
                # recording for changed and undid Biwak's work)
                mapped, _found = self._mapping(bc_type, comment["id"])
                if mapped is None or mapped.basecamp_updated_at != parse_time(
                    comment.get("updated_at")
                ):
                    complete = False
                continue
            author = self._user(comment.get("creator"))
            when = parse_time(comment["created_at"])

            def create(comment=comment, author=author, when=when):
                content = self._md(
                    comment.get("content"),
                    comment.get("content_attachments"),
                    project=item.project,
                    author=author,
                    item=item,
                )
                with importing(at=when):
                    created = ops.add_comment(item, author=author, content=content)
                Comment.objects.filter(pk=created.pk).update(
                    created_at=when,
                    updated_at=parse_time(comment.get("updated_at")) or when,
                )
                return created

            self._upsert(bc_type, comment, create=create)
        return complete

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
                # Basecamp doesn't say who assigned
                ops.assign(item, [user], actor=actor, assigned_by={})
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
        self._preload("Todolist", lists)
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
            text = self._md(
                rec.get("description"),
                rec.get("description_attachments"),
                project=project,
                author=item.creator,
                item=item,
            )
            with self._from_basecamp(rec):
                ops.update_list(item, actor=None, title=rec["title"], description=text)
            self._link(item, text, item.creator)
            self._rename_twin("Todolist", rec)

        item = self._upsert("Todolist", rec, create=create, update=update, follow=True)
        if item is not None and self._touch("Todolist", rec):
            self._top_visibility(item, visible, rec)
            self._status(item, rec)
            self._stamp(item, rec)
        if ("Todolist", rec["id"]) in self._gone:
            return
        self._list_content(rec, item, visible, project)
        self._follow("Todolist", rec, item, comments=False)

    def _list_content(self, rec, item, visible, project):
        """Its to-dos and the groups with theirs"""
        self._container, self._container_is_board = rec, False
        self._container_project = project
        self._todos(rec["id"], item, None, visible, project)
        try:
            groups = list(self.client.paginate(f"/todolists/{rec['id']}/groups.json"))
        except api.NotFound:
            groups = []
        self._preload(GROUP, groups)
        for group_rec in sorted(groups, key=lambda r: r.get("position", 0)):
            self._group(group_rec, item, visible, project, rec_type=GROUP)

    def _group(self, rec, item, visible, project, *, rec_type, cards=False):
        todolist = item.todolist if item is not None else None

        color = group_color(rec.get("color"))

        def create():
            return ops.create_group(todolist=todolist, title=rec["title"], color=color)

        def update(group):
            ops.update_group(group, title=rec["title"], color=color)
            self._rename_twin(rec_type, rec, color=color)

        group = self._upsert(rec_type, rec, create=create, update=update)
        self._group_key = (rec_type, rec["id"])
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
        self._preload("Todo", found)
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
        if item is None and not self.dry:
            # Its list was deleted in Biwak
            return
        title = rec["title"]

        def notes(todo=None):
            text = self._md(
                rec.get("description"),
                rec.get("description_attachments"),
                project=project,
                author=creator,
                item=todo,
            )
            steps = "\n".join(
                f"- [{'x' if step.get('completed') else ' '}] {step['title']}"
                for step in rec.get("steps", [])
            )
            return f"{text}\n\n{steps}".strip()

        def dates():
            """The due date and the start date (specs/start-dates.md); a
            start date without a due date or after it isn't brought"""
            due, starts = (
                dt.date.fromisoformat(value) if value else None
                for value in (rec.get("due_on"), rec.get("starts_on"))
            )
            if due is None or (starts and starts > due):
                starts = None
            return {"due_on": due, "starts_on": starts}

        repeat = self._repeat(rec, title)
        created = []

        def create():
            created.append(True)
            with importing(at=parse_time(rec["created_at"])):
                return ops.create_todo(
                    todolist=item,
                    title=title,
                    creator=creator,
                    group=group,
                    notes=notes(),
                    **dates(),
                    **repeat,
                )

        def update(todo):
            text = notes(todo)
            with self._from_basecamp(rec):
                ops.update_todo(
                    todo, actor=None, title=title, notes=text, **dates(), **repeat
                )
            self._link(todo, text, creator)

        todo = self._upsert(bc_type, rec, create=create, update=update, follow=True)
        if (bc_type, rec["id"]) in self._skipped:
            self._fill_schedule(todo, repeat, rec)
        if todo is not None and self._touch(bc_type, rec):
            # Basecamp doesn't say when somebody was assigned: a new to-do's
            # assignees at its creation, before its comments; those added
            # since the last run when Basecamp last changed it
            # (in the creator's name, at Basecamp's time, without a person
            # later: Basecamp doesn't say who assigned)
            if created:
                with importing(at=parse_time(rec["created_at"])):
                    self._sync_assignees(todo, rec.get("assignees", []), todo.creator)
            else:
                self._move_todo(todo, item, group, rec)
                with self._from_basecamp(rec):
                    self._sync_assignees(todo, rec.get("assignees", []), None)
            self._completion(todo, rec, new=bool(created))
            self._stamp(todo, rec)
        self._follow(bc_type, rec, todo)

    def _move_todo(self, todo, todolist, group, rec):
        """Moved in Basecamp to another list, group or card table column
        (decided 2026-11-28), with the new place's visibility"""
        todo.refresh_from_db()
        group_id = Todo.objects.get(item=todo).group_id
        if (todo.parent_id, group_id) != (todolist.pk, group.pk if group else None):
            with self._from_basecamp(rec):
                ops.move_todo(todo, todolist=todolist, group=group, actor=None)

    def _move_item(self, bc_type, item, parent, rec):
        """A folder, doc or file moved in Basecamp to another folder (decided
        2026-11-28), with the new place's visibility"""
        if (bc_type, rec["id"]) not in self._created and item.parent_id != (
            parent.pk if parent else None
        ):
            with self._from_basecamp(rec):
                ops.move_item(item, parent=parent, actor=None)

    def _repeat(self, rec, title):
        """Basecamp's schedule (``repetition_schedule``), which only the
        newest to-do of a series has (it moves on, as ours does,
        specs/todos.md). Only for an open one: completing one with a rule,
        as the import does with done and archived ones, would make a next
        one. What we don't know is a problem, and the to-do doesn't repeat."""
        none = {"recurrence": "", "recurrence_ends_on": None}
        schedule = rec.get("repetition_schedule")
        if not schedule or rec.get("completed") or rec.get("status") == "archived":
            return none
        try:
            rule, ends_on = recurrence_of(schedule)
        except (ValueError, KeyError, TypeError, schedules.InvalidRule) as exc:
            self.problem(
                f"To-do {title!r} ({rec['id']}) in {self._project_name} doesn't"
                f" repeat: its schedule isn't known ({exc})"
            )
            return none
        return {"recurrence": rule, "recurrence_ends_on": ends_on}

    def _fill_schedule(self, item, repeat, rec):
        """An unchanged to-do imported before schedules were (2026-11-23)
        gets its schedule, which the listing gives anyway: only an open one
        without a rule which never had one in Biwak (no edit of its repeat,
        by anybody or an import), so a rule removed on purpose stays
        removed. Listed in the report."""
        if not repeat["recurrence"] or item is None:
            return
        todo = Todo.objects.get(item=item)
        if todo.recurrence or todo.is_completed:
            return
        if item.following.exists():
            # Completed in Biwak, its rule went on to the next to-do;
            # reopened, it has none (found 2026-11-28, round 2)
            return
        if Event.objects.filter(
            item=item, action=Action.EDITED, data__fields__contains=["recurrence"]
        ).exists():
            return
        self.report.schedules.append(
            f"{self._project_name}: {item.title!r} ({rec['id']}),"
            f" {schedules.describe(repeat['recurrence'])}"
        )
        if self.dry:
            return
        with self._from_basecamp(rec):
            ops.update_todo(item, actor=None, **repeat)

    def _completion(self, todo, rec, *, new=False):
        """Archived to-dos come in completed (specs/archiving.md), at the
        time Basecamp last changed them (the archiving), by nobody as
        Basecamp's change: the API doesn't say who archived (decided
        2026-11-28). A ``new`` to-do has nothing done in Biwak to undo."""
        done = Todo.objects.get(item=todo).is_completed
        archived = rec.get("status") == "archived"
        if (rec.get("completed") or archived) and not done:
            completion = rec.get("completion") or {}
            when = parse_time(completion.get("created_at")) or parse_time(
                rec["updated_at"]
            )
            if not new and self._undoes_biwak(todo, [Action.REOPENED], when):
                with importing(at=timezone.now(), noted="basecamp"):
                    ops.complete(todo, actor=None)
                return
            if archived and not rec.get("completed"):
                # Archiving is Basecamp's change, which names nobody
                # (decided 2026-11-28)
                completing = self._from_basecamp(rec)
                by = None
            else:
                # Nobody when Basecamp doesn't say (decided 2026-11-28)
                completing = importing(at=when)
                by = self._user(completion.get("creator"))
            with completing:
                ops.complete(todo, actor=by)
            Todo.objects.filter(pk=todo.pk).update(completed_at=when)
        elif not (rec.get("completed") or archived) and done:
            # Basecamp doesn't say when it was reopened
            when = parse_time(rec.get("updated_at"))
            if self._undoes_biwak(
                todo, [Action.COMPLETED, Action.MARKED_OBSOLETE], when
            ):
                with importing(at=timezone.now(), noted="basecamp"):
                    ops.reopen(todo, actor=None)
                return
            with self._from_basecamp(rec):
                ops.reopen(todo, actor=None)

    def _undoes_biwak(self, todo, actions, when):
        """Whether the to-do's last ``actions`` event (reopening, or
        completing) is newer than Basecamp's change: then Basecamp's state
        undoes what was done in Biwak, which happens now, by Biwak, noted
        as the Basecamp import (decided 2026-11-27); at Basecamp's time it
        would sort before what it undoes"""
        last = Event.objects.filter(item=todo, action__in=actions).aggregate(
            last=Max("created_at")
        )["last"]
        return last is not None and (when is None or last > when)

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
            with self._from_basecamp(rec):
                ops.update_list(item, actor=None, title=rec["title"])
            # Its twin is a list too
            self._rename_twin("Todolist", rec)

        item = self._upsert(
            "Kanban::Board", rec, create=create, update=update, follow=True
        )
        if item is not None and self._touch("Kanban::Board", rec):
            self._top_visibility(item, visible, rec)
            self._stamp(item, rec)
        if ("Kanban::Board", rec["id"]) in self._gone:
            return
        self._container, self._container_is_board = rec, True
        self._container_project = project
        self._preload(COLUMN, rec.get("lists", []))
        for column in rec.get("lists", []):
            self._group(column, item, visible, project, rec_type=COLUMN, cards=True)
        self._follow("Kanban::Board", rec, item, comments=False)

    def _cards(self, column_id, item, group, parent_visible, project):
        try:
            cards = list(
                self.client.paginate(f"/card_tables/lists/{column_id}/cards.json")
            )
        except api.NotFound:
            return
        self._preload("Kanban::Card", cards)
        for rec in cards:
            self._todo(rec, item, group, parent_visible, project, "Kanban::Card")

    # Messages -------------------------------------------------------------------------------

    def _category(self, rec):
        category = rec.get("category")
        if not category:
            return None
        return self._category_named(category["name"], category.get("icon") or "")

    def _category_named(self, name, emoji):
        """The category by name, ignoring case; created last when missing"""
        if self.dry:
            return None
        found = MessageCategory.objects.filter(name__iexact=name).first()
        if found is None:
            last = MessageCategory.objects.order_by("-position").first()
            found = MessageCategory.objects.create(
                name=name,
                emoji=emoji,
                position=(last.position + 1) if last else 0,
            )
        return found

    def _message_board(self, board_id, project):
        messages = list(
            self.client.paginate(f"/message_boards/{board_id}/messages.json")
        )
        self._preload("Message", messages)
        # Oldest first: the board lists newest first by creation
        for rec in sorted(messages, key=lambda r: r["created_at"]):
            self._message(rec, project)

    def _message(self, rec, project):
        if self._skip(rec):
            return
        creator = self._user(rec.get("creator"))
        visible = bool(rec.get("visible_to_clients"))

        def content(item=None):
            return self._md(
                rec.get("content"),
                rec.get("content_attachments"),
                project=project,
                author=creator,
                item=item,
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
            text = content(item)
            with self._from_basecamp(rec):
                file_ops.update_message(
                    item,
                    actor=None,
                    title=rec.get("subject") or rec["title"],
                    content=text,
                    category=self._category(rec),
                )
            self._link(item, text, creator)

        item = self._upsert("Message", rec, create=create, update=update, follow=True)
        if item is not None and self._touch("Message", rec):
            self._top_visibility(item, visible, rec)
            self._stamp(item, rec)
        self._follow("Message", rec, item)
        if item is not None and not self.dry:
            # From the original times, for the board's order
            ops.refresh_message_activity(item)

    # Email forwards ---------------------------------------------------------------

    def _inbox(self, bucket_id, inbox_id, project):
        """Forwarded mails become internal messages (the API wants the
        bucket in the path here)"""
        try:
            forwards = list(
                self.client.paginate(
                    f"/buckets/{bucket_id}/inboxes/{inbox_id}/forwards.json"
                )
            )
        except api.NotFound:
            return
        self._preload("Inbox::Forward", forwards)
        for rec in sorted(forwards, key=lambda r: r["created_at"]):
            self._forward(bucket_id, rec, project)

    def _forward(self, bucket_id, rec, project):
        """By the forwarder, with the line about the original sender as
        when filing a forwarded mail (specs/forwarding.md), internal, in
        ``FORWARDS_CATEGORY``"""
        if self._skip(rec):
            return
        creator = self._user(rec.get("creator"))
        created = parse_time(rec["created_at"])
        title = rec.get("subject") or rec.get("title") or ""

        def content(author, item=None):
            text = self._md(
                rec.get("content"),
                rec.get("content_attachments"),
                project=project,
                author=author,
                item=item,
                plain=True,
            )
            mail = ForwardedMail(
                sender_email=rec.get("from") or "",
                sent_on=timezone.localdate(created),
            )
            with translation.override(language_for(author)):
                line = forwarded_line(mail)
            return "\n\n".join(part for part in [line, text] if part)

        def create():
            with importing(at=created):
                return ops.create_message(
                    project=project,
                    title=title,
                    creator=creator,
                    content=content(creator),
                    visible=False,
                    category=self._category_named(*FORWARDS_CATEGORY),
                )

        def update(item):
            text = content(item.creator, item)
            with self._from_basecamp(rec):
                file_ops.update_message(
                    item,
                    actor=None,
                    title=title,
                    content=text,
                    category=self._category_named(*FORWARDS_CATEGORY),
                )
            self._link(item, text, item.creator)

        item = self._upsert(
            "Inbox::Forward", rec, create=create, update=update, follow=True
        )
        if item is not None and self._touch("Inbox::Forward", rec):
            # Internal also when a client forwarded it
            self._top_visibility(item, visible=False, rec=rec)
            self._stamp(item, rec)
        self._follow(
            "Inbox::Forward",
            rec,
            item,
            replies=f"/buckets/{bucket_id}/inbox_forwards/{rec['id']}/replies.json",
        )
        if item is not None and not self.dry:
            ops.refresh_message_activity(item)

    # Docs & Files -------------------------------------------------------------------------------

    def _vault(
        self, vault_id, project, parent, *, parent_visible, nested, internal=None
    ):
        """The children of a vault: the root vault is the project's root"""
        folders = list(self.client.paginate(f"/vaults/{vault_id}/vaults.json"))
        self._preload("Vault", folders)
        for rec in sorted(folders, key=lambda r: r.get("position", 0)):
            self._folder(rec, project, parent, parent_visible, nested, internal)
        documents = list(self.client.paginate(f"/vaults/{vault_id}/documents.json"))
        self._preload("Document", documents)
        for rec in documents:
            self._document(rec, project, parent, parent_visible, nested, internal)
        uploads = list(self.client.paginate(f"/vaults/{vault_id}/uploads.json"))
        self._preload("Upload", uploads)
        for rec in uploads:
            self._upload(rec, project, parent, parent_visible, nested, internal)

    def _folder(self, rec, project, parent, parent_visible, nested, internal):
        parent, visible = self._place(
            rec, "folder", parent, parent_visible, nested, internal
        )
        if self._parent_gone(parent, nested):
            return
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

        def update(item):
            # Renamed in Basecamp (found 2026-11-28: neither it nor its
            # internal twin followed)
            with self._from_basecamp(rec):
                file_ops.update_folder(item, actor=None, title=rec["title"])
            if not nested:
                self._rename_twin("Vault", rec)

        item = self._upsert("Vault", rec, create=create, update=update, follow=True)
        if item is not None and self._touch("Vault", rec):
            self._move_item("Vault", item, parent, rec)
            self._top_visibility(item, visible, rec)
            self._stamp(item, rec)
        self._follow("Vault", rec, item, comments=False)
        if ("Vault", rec["id"]) in self._gone:
            return
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
        if self._parent_gone(parent, nested):
            return
        creator = self._user(rec.get("creator"))

        def content(item=None):
            return self._md(
                rec.get("content"),
                rec.get("content_attachments"),
                project=project,
                author=creator,
                item=item,
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
            # In the creator's name: a doc's versions need an author, its
            # edits are credited to who wrote them (collab.live.merge())
            with importing(at=parse_time(rec.get("updated_at"))):
                file_ops.update_doc(
                    item,
                    actor=item.creator,
                    content=with_heading(rec["title"], content(item)),
                )

        item = self._upsert("Document", rec, create=create, update=update, follow=True)
        if item is not None and self._touch("Document", rec):
            self._move_item("Document", item, parent, rec)
            self._top_visibility(item, visible, rec)
            self._stamp(item, rec)
        self._follow("Document", rec, item)

    def _upload(self, rec, project, parent, parent_visible, nested, internal):
        if self._skip(rec):
            return
        name = rec.get("filename") or rec["title"]
        folder = (rec.get("parent") or {}).get("title")
        where = " / ".join(filter(None, [self._project_name, folder]))
        if self._too_large(name, rec.get("byte_size") or 0, where, rec.get("app_url")):
            return
        parent, visible = self._place(
            rec, "file", parent, parent_visible, nested, internal
        )
        if self._parent_gone(parent, nested):
            return
        creator = self._user(rec.get("creator"))

        def description(item=None):
            return self._md(
                rec.get("description"),
                rec.get("description_attachments"),
                project=project,
                author=creator,
                item=item,
            )

        def create():
            try:
                data = self.client.download(rec["download_url"])
            except (api.NotFound, api.ApiError, KeyError) as exc:
                self.problem(f"File {rec.get('filename')} not downloaded: {exc}")
                raise _Skip from exc
            try:
                with importing(at=parse_time(rec["created_at"])):
                    return ops.create_upload(
                        project=project,
                        file=ContentFile(data, name=name),
                        creator=creator,
                        parent=parent,
                        description=description(),
                        visible=visible,
                    )
            except attachments.UploadError as exc:
                self._too_large(name, None, where, rec.get("app_url"))
                raise _Skip from exc

        def update(item):
            text = description(item)
            with self._from_basecamp(rec):
                file_ops.update_upload(item, actor=None, description=text)
            self._link(item, text, creator)

        try:
            item = self._upsert(
                "Upload", rec, create=create, update=update, follow=True
            )
        except _Skip:
            return
        if item is not None and self._touch("Upload", rec):
            self._move_item("Upload", item, parent, rec)
            self._top_visibility(item, visible, rec)
            self._stamp(item, rec)
        self._follow("Upload", rec, item)

    # Check-ins ------------------------------------------------------------------------------------

    def _questionnaire(self, questionnaire_id, project):
        questions = list(
            self.client.paginate(f"/questionnaires/{questionnaire_id}/questions.json")
        )
        self._preload("Question", questions)
        for rec in questions:
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

        def update(item):
            with self._from_basecamp(rec):
                checkin_ops.update_question(
                    item,
                    actor=None,
                    title=rec["title"],
                    rule=rule,
                    starts_on=starts_on,
                    time_of_day=time_of_day,
                )

        item = self._upsert("Question", rec, create=create, update=update, follow=True)
        if ("Question", rec["id"]) in self._gone:
            return
        answers = list(self.client.paginate(f"/questions/{rec['id']}/answers.json"))
        self._preload("Question::Answer", answers)
        if item is not None:
            self._restamp("Question", item, rec)
        # Those who answered since the last run are asked; who answered
        # before was asked then, and may have been taken off in Biwak since
        # (decided 2026-11-28: Biwak's change stays). An answer's state is
        # stored after its author is asked, so a run stopped in between
        # asks them the next time (found 2026-11-28, round 2: only answers
        # created in the same run counted, the others' authors were lost)
        asked = []
        read = []
        for answer in answers:
            if self._skip(answer):
                continue
            mapped, _found = self._mapping("Question::Answer", answer["id"])
            new = mapped is None or mapped.basecamp_updated_at is None
            user, done = self._answer(answer, rec, item, visible)
            if done:
                read.append(answer)
            gone = ("Question::Answer", answer["id"]) in self._gone
            if user is not None and new and not gone and user not in asked:
                asked.append(user)
        if item is not None and asked and not self.dry:
            who = [u for u in asked if u.is_active]
            allowed = who_can_see(item).filter(pk__in=[u.pk for u in who])
            if allowed:
                with importing(noted="basecamp"):
                    checkin_ops.set_people(
                        item,
                        # Those asked before who can't see it anymore
                        # (deactivated in Biwak meanwhile) aren't kept
                        sorted(
                            set(allowed)
                            | set(
                                who_can_see(item).filter(
                                    pk__in=item.question.people.values("pk")
                                )
                            ),
                            key=lambda u: u.pk,
                        ),
                        # Basecamp doesn't say who asked them
                        actor=None,
                    )
        for answer in read:
            self._settle("Question::Answer", answer)
        self._follow("Question", rec, item, comments=False)

    def _answer(self, rec, question_rec, question, visible):
        """(The author, whether the answer was read completely: its state
        is stored by ``_question()``)"""
        if not self._inherits(rec, visible, "check-in answer"):
            # Answers can't be moved elsewhere
            self.problem(
                f"Skipped check-in answer {rec['id']}: internal in Basecamp,"
                " inside a question visible to clients"
            )
            return None, False
        user = self._user(rec.get("creator"))
        day = dt.date.fromisoformat(rec.get("group_on") or rec["created_at"][:10])

        def create():
            with importing(at=parse_time(rec["created_at"])):
                schedule = question.question
                asked_at = dt.datetime.combine(
                    day, schedule.time_of_day, tzinfo=ZoneInfo(settings.TIME_ZONE)
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

        def update(item):
            text = self._md(
                rec.get("content"),
                rec.get("content_attachments"),
                project=item.project,
                author=item.creator,
                item=item,
            )
            with self._from_basecamp(rec):
                checkin_ops.update_answer(
                    Answer.objects.get(item=item), text, actor=None
                )
            self._link(item, text, item.creator)

        try:
            item = self._upsert(
                "Question::Answer", rec, create=create, update=update, follow=True
            )
        except _Skip:
            return user, False
        if item is not None:
            self._restamp("Question::Answer", item, rec)
        done = self._follow(
            "Question::Answer", rec, item, subscriptions=False, settle=False
        )
        return user, done

    # After the project --------------------------------------------------------------------

    def _bookmarks(self, project):
        """The bookmarks of the person whose token it is, once each (noted
        on the project's mapping like its members): one removed in Biwak
        doesn't come back"""
        bc_id = (
            ImportedObject.objects
            .filter(
                basecamp_type__in=[PROJECT, TEMPLATE],
                content_type=ContentType.objects.get_for_model(project),
                object_id=project.pk,
            )
            .values_list("basecamp_type", "basecamp_id")
            .first()
        )
        mapped, done = self._done(*bc_id) if bc_id else (None, {})
        marked = set(done.get("bookmarks", ()))
        try:
            bookmarks = list(self.client.paginate("/my/bookmarks.json"))
        except api.NotFound:
            return
        recordings = defaultdict(list)
        for bookmark in bookmarks:
            recordings[bookmark["recording"]["type"]].append(bookmark["recording"])
        for bc_type, listed in recordings.items():
            self._preload(bc_type, listed)
        for bookmark in bookmarks:
            recording = bookmark["recording"]
            item = self._find(recording["type"], recording["id"])
            key = f"{self.actor.pk}:{recording['id']}"
            if (
                isinstance(item, Item)
                and item.project_id == project.pk
                and key not in marked
            ):
                bookmark_ops.add_bookmark(self.actor, item=item)
                marked.add(key)
        if mapped is not None and marked != set(done.get("bookmarks", ())):
            mapped.done = mapped.done | {"bookmarks": sorted(marked)}
            mapped.save(update_fields=["done"])


def recurrence_of(schedule):
    """A to-do's ``repetition_schedule`` (not in Basecamp's documentation,
    seen in the API 2026-11-23) as (RRULE, end date); ``ValueError`` for
    what we don't know. Monthly by day of the month comes as
    ``every_day_of_month`` and ``custom_month`` (with ``month_interval``),
    whose ``days`` are days of the month; the rest are a check-in's shapes
    (``schedule_of()``), whose ``days`` are weekdays"""
    ends_on = schedule.get("end_date")
    ends_on = dt.date.fromisoformat(ends_on) if ends_on else None
    frequency = schedule.get("frequency")
    if frequency in {"every_day_of_month", "custom_month"}:
        interval = schedule.get("month_interval") or 1
        days = sorted({int(day) for day in schedule.get("days") or []})
        if not days:
            days = [dt.date.fromisoformat(schedule["start_date"]).day]
        if any(day < 1 or day > 31 for day in days):
            raise ValueError(f"days of the month {days!r}")
        if len(days) == 1 and days[0] >= 29:
            # The 29th to 31st: the last day of shorter months
            # (specs/todos.md), as for check-ins
            rule = (
                f"FREQ=MONTHLY;INTERVAL={interval};BYMONTHDAY=28,29,30,31;BYSETPOS=-1"
            )
        else:
            rule = f"FREQ=MONTHLY;INTERVAL={interval};BYMONTHDAY={','.join(map(str, days))}"
        return schedules.validate(rule), ends_on
    rule, _start, _time = schedule_of(schedule)
    return rule, ends_on


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
            # "The last Monday of the month" may come as -1 or as 5: the last
            # one either way (a 5th Monday doesn't exist every month)
            instance = int(schedule["week_instance"])
            instance = -1 if instance < 0 or instance >= 5 else instance
            rule = (
                f"FREQ=MONTHLY;INTERVAL={interval};BYDAY={days[0]};BYSETPOS={instance}"
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
