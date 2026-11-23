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
from biwak.files import attachments, models as file_models, operations as file_ops
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

# Basecamp's weekdays, 0 is Sunday
WEEKDAYS = ["SU", "MO", "TU", "WE", "TH", "FR", "SA"]

# Links to other recordings in texts: <account>/buckets/<project>/<path>/<id>
LINK = re.compile(
    r"https://3\.basecamp\.com/\d+/buckets/\d+/"
    r"(todos|todolists|messages|documents|uploads|vaults|card_tables/cards"
    r"|card_tables|questions|inbox_forwards)/(\d+)[^\s)\]\"']*"
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
    "inbox_forwards": "Inbox::Forward",
}


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
        # (Basecamp type, ID) of the recordings unchanged since the last run
        self._skipped = set()
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
        model = ContentType.objects.get_for_id(mapped.content_type_id).model_class()
        target = model._base_manager.filter(pk=mapped.object_id).first()
        if target is None:
            mapped.delete()
            self._mappings[key] = None
            return None, None
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
        self, bc_type, rec, item, *, comments=True, subscriptions=True, replies=None
    ):
        """The comments and subscribers of a recording (two requests), not
        for one unchanged since the last run; then its state is stored.
        ``replies``: where an email forward's replies are, its comments"""
        if (bc_type, rec["id"]) in self._skipped:
            return
        if replies:
            self._comments(rec, item, path=replies, bc_type="Inbox::Reply")
        elif comments:
            self._comments(rec, item)
        if subscriptions and item is not None:
            self._subscriptions(rec, item)
        if item is not None:
            self._settle(bc_type, rec)

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
        """Inactive people (created by an import, or deactivated) who turn up
        in a project but aren't among the account's people anymore have
        left: ``left_at`` is the run's date (specs/activation.md). Those
        marked so who are among them again are back: ``left_at`` is cleared
        (decided 2026-11-22). The account's people are read once per run;
        inactive people still in the account wait to be activated, active
        ones aren't touched."""
        self._account_ids()
        new = [pid for pid in self._persons if pid not in self._looked_at]
        self._looked_at.update(new)
        gone = {pid: self._users.get(pid) for pid in new}
        back = {pid: gone.pop(pid) for pid in list(gone) if pid in self._account_people}
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

    def _md(self, html, rec_attachments, *, project, author, plain=False):
        """Markdown of a Basecamp text; files in it are downloaded and
        uploaded as ``author``, who saves the text next. ``plain``: a
        forwarded mail's plain lines"""
        self._text = {
            "attachments": rec_attachments or [],
            "project": project,
            "author": author,
        }
        try:
            text = (plain_to_markdown if plain else to_markdown)(html, self)
        finally:
            self._text = None
        if LINK.search(text):
            # Targets which aren't imported yet: fixed when the run is done
            self._links_to_fix.append(text)
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
            self.say(f"  {len(people)} people")
            for person in people:
                self._people_by_sgid[person.get("attachable_sgid")] = person["id"]
            for person in people:
                user = self._user(person)
                self._image(person, user)
                if user is not None and project is not None:
                    with importing(at=parse_time(rec["created_at"])):
                        self._add_member(project, user)
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
        self._archived_recordings(bucket_id)
        if not self.dry:
            self._fix_links(project)
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
            project_ops.update_project(
                template,
                actor=self.actor,
                name=rec["name"],
                description=rec.get("description") or "",
            )

        template = self._upsert(TEMPLATE, rec, create=create, update=update)
        if template is not None and rec.get("status") == "archived":
            if template.archived_at is None:
                project_ops.archive_project(template, actor=self.actor)
        elif template is not None and template.archived_at is not None:
            project_ops.unarchive_project(template, actor=self.actor)
        return template

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
            found = ops.create_group(
                todolist=item.todolist, title=group.title, color=group.color
            )
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
        """Lists stay archived (to-dos are completed, not archived)"""
        archived = rec.get("status") == "archived"
        with importing(at=parse_time(rec.get("updated_at"))):
            if archived and item.status == Status.ACTIVE:
                ops.archive(item, actor=item.creator)
            elif not archived and item.status == Status.ARCHIVED:
                ops.unarchive(item, actor=item.creator)

    def _comments(self, rec, item, *, path=None, bc_type="Comment"):
        """``path`` and ``bc_type``: an email forward's replies"""
        if self.since and self._skip(rec):
            return
        if comment_count(rec) == 0:
            return
        try:
            comments = list(
                self.client.paginate(path or f"/recordings/{rec['id']}/comments.json")
            )
        except api.NotFound:
            return
        self._preload(bc_type, comments)
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

            self._upsert(bc_type, comment, create=create)

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

        item = self._upsert("Todolist", rec, create=create, update=update, follow=True)
        if item is not None:
            self._top_visibility(item, visible, rec)
            self._status(item, rec)
            self._stamp(item, rec)
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
            with importing(at=parse_time(rec.get("updated_at"))):
                ops.update_todo(
                    todo,
                    actor=todo.creator,
                    title=title,
                    notes=notes(),
                    **dates(),
                    **repeat,
                )

        todo = self._upsert(bc_type, rec, create=create, update=update, follow=True)
        if (bc_type, rec["id"]) in self._skipped:
            self._fill_schedule(todo, repeat, rec)
        if todo is not None:
            # Basecamp doesn't say when somebody was assigned: a new to-do's
            # assignees at its creation, before its comments; those added
            # since the last run when Basecamp last changed it
            assigned_at = rec["created_at"] if created else rec.get("updated_at")
            with importing(at=parse_time(assigned_at)):
                self._sync_assignees(todo, rec.get("assignees", []), todo.creator)
            with importing(at=parse_time(rec.get("updated_at"))):
                self._completion(todo, rec)
            self._stamp(todo, rec)
        self._follow(bc_type, rec, todo)

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
        with importing(at=parse_time(rec.get("updated_at"))):
            ops.update_todo(item, actor=item.creator, **repeat)

    def _completion(self, todo, rec):
        """Archived to-dos come in completed (specs/archiving.md), at the
        time Basecamp last changed them (the archiving), by the importing
        person: the API doesn't say who archived"""
        done = Todo.objects.get(item=todo).is_completed
        archived = rec.get("status") == "archived"
        if (rec.get("completed") or archived) and not done:
            completion = rec.get("completion") or {}
            when = parse_time(completion.get("created_at")) or parse_time(
                rec["updated_at"]
            )
            by = self._user(completion.get("creator")) or (
                self.actor if archived and not rec.get("completed") else todo.creator
            )
            with importing(at=when):
                ops.complete(todo, actor=by)
            Todo.objects.filter(pk=todo.pk).update(completed_at=when)
        elif not (rec.get("completed") or archived) and done:
            with importing():
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

        item = self._upsert(
            "Kanban::Board", rec, create=create, update=update, follow=True
        )
        if item is not None:
            self._top_visibility(item, visible, rec)
            self._stamp(item, rec)
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

        item = self._upsert("Message", rec, create=create, update=update, follow=True)
        if item is not None:
            self._top_visibility(item, visible, rec)
            self._stamp(item, rec)
        self._follow("Message", rec, item)
        if item is not None:
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

        def content(author):
            text = self._md(
                rec.get("content"),
                rec.get("content_attachments"),
                project=project,
                author=author,
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
            with importing(at=parse_time(rec.get("updated_at"))):
                file_ops.update_message(
                    item,
                    actor=item.creator,
                    title=title,
                    content=content(item.creator),
                    category=self._category_named(*FORWARDS_CATEGORY),
                )

        item = self._upsert(
            "Inbox::Forward", rec, create=create, update=update, follow=True
        )
        if item is not None:
            # Internal also when a client forwarded it
            self._top_visibility(item, visible=False, rec=rec)
            self._stamp(item, rec)
        self._follow(
            "Inbox::Forward",
            rec,
            item,
            replies=f"/buckets/{bucket_id}/inbox_forwards/{rec['id']}/replies.json",
        )
        if item is not None:
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

        item = self._upsert("Vault", rec, create=create, follow=True)
        if item is not None:
            self._top_visibility(item, visible, rec)
            self._stamp(item, rec)
        self._follow("Vault", rec, item, comments=False)
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
                    item,
                    actor=item.creator,
                    content=with_heading(rec["title"], content()),
                )

        item = self._upsert("Document", rec, create=create, update=update, follow=True)
        if item is not None:
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
            with importing(at=parse_time(rec.get("updated_at"))):
                file_ops.update_upload(
                    item, actor=item.creator, description=description()
                )

        try:
            item = self._upsert(
                "Upload", rec, create=create, update=update, follow=True
            )
        except _Skip:
            return
        if item is not None:
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

        item = self._upsert("Question", rec, create=create, follow=True)
        answers = list(self.client.paginate(f"/questions/{rec['id']}/answers.json"))
        self._preload("Question::Answer", answers)
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
                        actor=item.creator,
                    )
        self._follow("Question", rec, item, comments=False)

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

        try:
            item = self._upsert("Question::Answer", rec, create=create, follow=True)
        except _Skip:
            return user
        if item is not None:
            self._stamp(item, rec)
        self._follow("Question::Answer", rec, item, subscriptions=False)
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
        recordings = defaultdict(list)
        for bookmark in bookmarks:
            recordings[bookmark["recording"]["type"]].append(bookmark["recording"])
        for bc_type, listed in recordings.items():
            self._preload(bc_type, listed)
        for bookmark in bookmarks:
            recording = bookmark["recording"]
            item = self._find(recording["type"], recording["id"])
            if isinstance(item, Item) and item.project_id == project.pk:
                bookmark_ops.add_bookmark(self.actor, item=item)


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
