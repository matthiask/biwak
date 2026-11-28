"""The Basecamp importer against recorded shapes with made-up data
(specs/import-basecamp.md)"""

import datetime as dt
import io
import re
from unittest import mock
from urllib.parse import unquote

from django.core import mail
from django.core.management import CommandError, call_command
from django.db import connection
from django.db.models import Max
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from biwak.accounts.models import User
from biwak.activity.models import Action, Event, Notification, Subscription
from biwak.bookmarks.models import Bookmark
from biwak.checkins.models import Answer, Occurrence, Question
from biwak.files.models import Attachment
from biwak.importer import client as client_api, importer as importer_module, support
from biwak.importer.importer import Importer, ImportRefused
from biwak.importer.models import ImportedObject
from biwak.items import operations as ops, visibility
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
from biwak.organizations.models import Organization
from biwak.projects.models import Membership, Project
from biwak.templatetags.biwak import render_markdown
from biwak.test_utils import organization, person


def at(text):
    return dt.datetime.fromisoformat(text)


class ImportCase(TestCase):
    """Ada (staff) runs the import; Bob and Cleo don't have accounts yet"""

    def setUp(self):
        self.ada = person("Ada", is_admin=True)
        self.client_ = support.FakeClient()

    def run_import(self, *, dry_run=False, since=None):
        importer = Importer(self.client_, actor=self.ada, dry_run=dry_run, since=since)
        return importer.run(support.PROJECT)

    def titles(self, qs):
        return {item.title for item in qs}

    @property
    def project(self):
        return Project.objects.get()

    def names(self, users):
        return {str(user) for user in users}

    def item(self, title, kind=None):
        found = Item.objects.filter(title=title, **({"kind": kind} if kind else {}))
        return found.get()


class ImportEveryKindTest(ImportCase):
    def test_every_row_of_the_mapping(self):
        self.run_import()
        project = self.project
        self.assertEqual(project.name, "Camp kitchen")
        self.assertFalse(project.is_all_access)
        self.assertEqual(project.created_at, at("2026-01-05T09:00:00+00:00"))

        # To-do lists, groups, to-dos
        kinds = lambda kind: self.titles(Item.objects.filter(kind=kind))  # noqa: E731
        self.assertEqual(
            kinds(Kind.LIST),
            {
                "Kitchen plan",
                "Kitchen plan (internal)",
                "Budget",
                "Old ideas",
                "Planning board",
            },
        )
        plan = self.item("Kitchen plan")
        self.assertEqual(plan.todolist.view, TodoList.View.LIST)
        # Eve has no account here: plain text
        self.assertEqual(
            plan.todolist.description, "What we cook, @Eve knows the rest."
        )
        self.assertEqual(self.item("Planning board").todolist.view, TodoList.View.BOARD)
        self.assertEqual(self.item("Old ideas").status, Status.ARCHIVED)
        self.assertEqual(
            kinds(Kind.TODO),
            {
                "Buy giraffe food",
                "Pick a camp date",
                "Peel potatoes",
                "Negotiate the price",
                "Whale watching",
                "New menu",
                "Order pots",
                "Raise the rate for Cleo",
            },
        )
        self.assertEqual(
            list(
                Group.objects.order_by("pk").values_list(
                    "todolist__item__title", "title", "color"
                )
            ),
            [
                ("Kitchen plan", "Week 1", ""),
                # The columns' colors, nearest in the palette; white is none
                ("Planning board", "Triage", ""),
                ("Planning board", "Cooking", "ember"),
                ("Planning board", "Done", ""),
            ],
        )
        peel = self.item("Peel potatoes")
        self.assertEqual(peel.todo.group.title, "Week 1")
        self.assertEqual(self.item("New menu").todo.group.title, "Triage")
        self.assertEqual(self.item("Order pots").todo.group.title, "Done")
        self.assertTrue(self.item("Order pots").todo.is_completed)
        self.assertIn("- [x] Find inspiration", self.item("New menu").todo.notes)
        self.assertIn("- [ ] Write it down", self.item("New menu").todo.notes)

        food = self.item("Buy giraffe food")
        self.assertEqual(food.todo.due_on, dt.date(2026, 6, 1))
        self.assertEqual(food.todo.starts_on, dt.date(2026, 5, 28))
        self.assertEqual(
            self.names(food.todo.assignees.all()), {"Bob Example", "Cleo Example"}
        )
        # Basecamp doesn't say who assigned
        self.assertEqual(
            list(food.todo.assignment_set.values_list("assigned_by", flat=True)),
            [None, None],
        )
        self.assertIn("[@Bob](person:", food.todo.notes)
        # Links to recordings keep Basecamp's address, shown through the
        # trampoline to the import (biwak/importer/links.py)
        self.assertIn(
            f"[the announcement]({support.APP}/buckets/{support.PROJECT}/messages/2001)",
            food.todo.notes,
        )
        self.assertIn('href="/basecamp/?to=', render_markdown(food.todo.notes))
        done = self.item("Pick a camp date")
        self.assertEqual(done.todo.completed_at, at("2026-01-08T16:30:00+00:00"))
        self.assertEqual(done.todo.completed_by, self.ada)
        # Archived to-dos come in completed, not archived (specs/archiving.md)
        whale = self.item("Whale watching")
        self.assertEqual(whale.status, Status.ACTIVE)
        self.assertEqual(whale.todo.completed_at, at("2026-01-08T09:00:00+00:00"))
        self.assertEqual(whale.todo.completed_by, self.ada)

        # Messages
        announcement = self.item("We have a camp")
        self.assertEqual(announcement.message.category.name, "Announcement")
        self.assertIn(
            f"[@Cleo](person:{User.objects.get(email='cleo@example.org').pk})",
            announcement.message.content,
        )
        link = re.search(
            r'href="/basecamp/\?to=([^"]+)"',
            render_markdown(announcement.message.content),
        )
        self.client.force_login(self.ada)
        self.assertRedirects(
            self.client.get("/basecamp/", {"to": unquote(link[1])}),
            food.get_absolute_url(),
            fetch_redirect_response=False,
        )
        # Announcement and the email forwards' category
        self.assertEqual(MessageCategory.objects.count(), 2)
        # The board's order from the original times (specs/files.md)
        self.assertEqual(
            announcement.message.last_activity_at,
            max([
                announcement.created_at,
                *announcement.comments.values_list("created_at", flat=True),
            ]),
        )
        latest = announcement.comments.order_by("created_at", "pk").last()
        self.assertEqual(
            announcement.message.last_commenter, latest.author if latest else None
        )

        # Folders, docs, files
        self.assertEqual(
            kinds(Kind.FOLDER),
            {"Public", "Private", "Mixed", "Mixed (internal)", "Deeper"},
        )
        self.assertEqual(self.item("Deeper").parent.title, "Private")
        self.assertEqual(self.item("Public doc").parent.title, "Public")
        self.assertEqual(self.item("Shopping list").parent, None)
        self.assertEqual(
            self.item("Shopping list").doc.content, "# Shopping list\n\nText"
        )
        self.assertEqual(kinds(Kind.FILE), {"plan.png", "map.png", "salaries.png"})
        upload = self.item("map.png").upload
        self.assertEqual(upload.description, "Check this")
        self.assertEqual(upload.versions.get().name, "map.png")

        # Check-ins
        q = Question.objects.get(item__title="What did you cook today?")
        self.assertEqual(
            q.rule,
            "FREQ=WEEKLY;BYDAY=FR,MO,TH,TU,WE".replace(
                "FR,MO,TH,TU,WE", "MO,TU,WE,TH,FR"
            ),
        )
        self.assertEqual(q.starts_on, dt.date(2026, 2, 11))
        self.assertEqual(q.time_of_day, dt.time(9, 0))
        self.assertTrue(q.is_paused)
        self.assertEqual(
            Question.objects.get(item__title="Any worries?").rule,
            "FREQ=MONTHLY;BYMONTHDAY=5",
        )
        self.assertEqual(Occurrence.objects.filter(question=q).count(), 2)
        self.assertEqual(Answer.objects.filter(occurrence__question=q).count(), 3)
        self.assertEqual(self.names(q.people.all()), {"Ada Example", "Bob Example"})

        # Email forwards: internal messages by the forwarder in their own
        # category, the original sender in a line above the mail's lines,
        # the replies as comments
        delivery = self.item("Delivery on Monday")
        bob = User.objects.get(email="bob@example.org")
        self.assertEqual(delivery.kind, Kind.MESSAGE)
        self.assertEqual(delivery.creator, bob)
        self.assertFalse(delivery.visible_to_clients)
        self.assertEqual(
            (delivery.message.category.name, delivery.message.category.emoji),
            ("Email forwards", "\N{INCOMING ENVELOPE}"),
        )
        receipt = Attachment.objects.get(name="receipt.png")
        self.assertEqual(receipt.item, delivery)
        self.assertEqual(
            delivery.message.content,
            "Forwarded from <orders@example.org>, 20 Jan 2026\n\n"
            "Hello Bob\n\nWe deliver on Monday, see\n"
            "https://example.org/delivery\n\n"
            "> Can you deliver soon?\n\n"
            f"![receipt.png](attachment:{receipt.key})",
        )
        self.assertEqual(delivery.created_at, at("2026-01-20T09:00:00+00:00"))
        self.assertEqual(
            list(delivery.comments.values_list("author__email", "content")),
            [("ada@example.org", "Thanks, noted")],
        )
        self.assertEqual(
            self.names(User.objects.filter(subscriptions__item=delivery)),
            {"Bob Example"},
        )

        # Comments, attachments
        self.assertEqual(Comment.objects.count(), 5)
        self.assertEqual(Comment.objects.filter(item=food).count(), 2)
        negotiate = self.item("Negotiate the price")
        attachment = Attachment.objects.get(name="menu.png")
        self.assertEqual(attachment.item, negotiate)
        self.assertIn(f"![menu.png](attachment:{attachment.key})", negotiate.todo.notes)

        # Subscriptions as in Basecamp, bookmarks
        self.assertEqual(
            self.names(User.objects.filter(subscriptions__item=food)),
            {"Ada Example", "Bob Example"},
        )
        self.assertEqual(
            list(Bookmark.objects.values_list("user", "item")),
            [(self.ada.pk, announcement.pk)],
        )

    def test_profile_images_are_imported_unless_generated(self):
        report = self.run_import()
        ada = User.objects.get(pk=self.ada.pk)
        bob = User.objects.get(email="bob@example.org")
        cleo = User.objects.get(email="cleo@example.org")
        # Ada's is Basecamp's own initials: skipped; the others are kept
        self.assertEqual(ada.image, "")
        self.assertTrue(bob.image.endswith(".webp"))
        self.assertTrue(cleo.image.endswith(".webp"))
        self.assertEqual(report.images, ["Bob Example", "Cleo Example"])
        self.assertEqual(report.generated, ["Ada Example"])
        self.assertIn("Profile images imported:", report.as_text())
        self.assertIn("generated by Basecamp", report.as_text())
        avatars = [url for url in self.client_.downloads if "avatar" in url]
        self.assertEqual(len(avatars), 3)
        # The per-person request has the URL, people.json hasn't
        self.assertIn(("/people/2.json", {}), self.client_.requests)

    def test_profile_images_are_fetched_once(self):
        self.run_import()
        downloads = len(self.client_.downloads)
        self.run_import()
        # Only Ada, who has none, is looked at again
        self.assertEqual(len(self.client_.downloads), downloads + 1)

    def test_profile_images_never_overwrite_ones_set_in_biwak(self):
        bob = User.objects.create_user("bob@example.org", full_name="Bob Example")
        bob.image = "people/mine.webp"
        bob.save()
        self.run_import()
        bob.refresh_from_db()
        self.assertEqual(bob.image, "people/mine.webp")
        self.assertNotIn(support.avatar_url(2), self.client_.downloads)
        self.assertNotIn(("/people/2.json", {}), self.client_.requests)

    def test_a_dry_run_fetches_no_profile_images(self):
        self.run_import(dry_run=True)
        self.assertFalse([r for r in self.client_.requests if r[0] == "/people/1.json"])
        self.assertEqual(self.client_.downloads, [])

    def test_a_missing_profile_image_is_a_problem(self):
        del self.client_.files[support.avatar_url(2)]
        report = self.run_import()
        self.assertTrue(any("Bob Example" in p for p in report.problems))
        self.assertEqual(User.objects.get(email="bob@example.org").image, "")

    def test_people(self):
        self.run_import()
        self.assertEqual(User.objects.filter(email="ada@example.org").count(), 1)
        bob = User.objects.get(email="bob@example.org")
        # Own staff active in Basecamp are active (decided 2026-11-22)
        self.assertTrue(bob.is_active)
        self.assertFalse(bob.is_client)
        cleo = User.objects.get(email="cleo@example.org")
        self.assertFalse(cleo.is_active)
        self.assertTrue(cleo.is_client)
        self.assertEqual(cleo.organization.name, "Example Client Ltd")
        self.assertEqual(
            self.names(User.objects.filter(memberships__project=self.project)),
            {"Ada Example", "Bob Example", "Cleo Example"},
        )
        # Eve was only mentioned: no account, no membership
        self.assertFalse(User.objects.filter(email="eve@example.org").exists())

    def test_authors_and_times_are_the_originals(self):
        self.run_import()
        food = self.item("Buy giraffe food")
        self.assertEqual(food.creator, self.ada)
        self.assertEqual(food.created_at, at("2026-01-07T08:00:00+00:00"))
        self.assertEqual(food.updated_at, at("2026-01-09T08:00:00+00:00"))
        created = Event.objects.get(item=food, action="created")
        self.assertEqual(created.created_at, at("2026-01-07T08:00:00+00:00"))
        self.assertEqual(created.actor, self.ada)
        comment = Comment.objects.get(item=food, content="Done by Friday.")
        self.assertEqual(comment.author.email, "bob@example.org")
        self.assertEqual(comment.created_at, at("2026-01-10T08:00:00+00:00"))
        self.assertEqual(
            Event.objects.get(
                item=food, action="commented", actor=comment.author
            ).created_at,
            at("2026-01-10T08:00:00+00:00"),
        )
        completed = Event.objects.get(
            item=self.item("Pick a camp date"), action="completed"
        )
        self.assertEqual(completed.created_at, at("2026-01-08T16:30:00+00:00"))
        # Basecamp doesn't say when people were assigned: at the creation,
        # before the comments (decided 2026-11-22)
        for assigned in Event.objects.filter(item=food, action=Action.ASSIGNED):
            self.assertEqual(assigned.created_at, food.created_at)
            self.assertLess(assigned.created_at, comment.created_at)
        # The project's activity is the latest original time, not now
        self.assertEqual(self.project.last_activity_at.year, 2026)
        self.assertLess(self.project.last_activity_at, at("2026-03-01T00:00:00+00:00"))


# What Basecamp had: the titles of everything clients may see, item by item
VISIBLE = {
    "Kitchen plan",  # a visible list, and its to-dos
    "Buy giraffe food",
    "Pick a camp date",
    "Peel potatoes",
    "We have a camp",  # a visible message
    "Public",  # a visible folder, and what's in it
    "Public doc",
    "Mixed",  # a visible folder, its internal doc is in "Mixed (internal)"
    "map.png",
    "Camp rules",  # a visible doc at the top
    "What did you cook today?",  # a visible check-in with its answers
}
INTERNAL = {
    "Budget",
    "Negotiate the price",
    "Old ideas",
    "Whale watching",
    "Planning board",
    "New menu",
    "Order pots",
    "Kitchen plan (internal)",  # the internal to-do of a visible list
    "Raise the rate for Cleo",
    "Mixed (internal)",  # the internal doc of a visible folder
    "Internal in a public folder",
    "Prices",  # posted by a client, internal in Basecamp
    "Delivery on Monday",  # an email forward: always internal
    "Shopping list",
    "plan.png",
    "Private",
    "Deeper",
    "Deep doc",
    "salaries.png",
    "Any worries?",
}


class VisibilityTest(ImportCase):
    def test_an_email_forward_by_a_client_stays_internal(self):
        forwards = self.client_.data[
            f"/buckets/{support.PROJECT}/inboxes/900/forwards.json"
        ]
        forwards[0]["creator"] = support.CLEO
        self.run_import()
        delivery = self.item("Delivery on Monday")
        self.assertTrue(delivery.creator.is_client)
        self.assertFalse(delivery.visible_to_clients)
        self.assertFalse(delivery.is_client_visible)

    def test_item_by_item_as_in_basecamp(self):
        report = self.run_import()
        for item in Item.objects.exclude(kind=Kind.ANSWER):
            with self.subTest(item.title):
                self.assertEqual(
                    item.is_client_visible,
                    item.title in VISIBLE,
                    f"{item.title}: stored visibility differs from Basecamp's",
                )
        # Every title is accounted for
        titles = self.titles(Item.objects.exclude(kind=Kind.ANSWER))
        self.assertEqual(titles - VISIBLE - INTERNAL, set())
        self.assertEqual(visibility.check(), [])
        text = " ".join(report.internal)
        self.assertIn("to-do 3013 ('Raise the rate for Cleo') into list", text)
        self.assertIn("doc 4301 ('Internal in a public folder') into folder", text)
        # Answers follow their question
        for answer in Item.objects.filter(kind=Kind.ANSWER):
            self.assertEqual(
                answer.is_client_visible, answer.parent.title in VISIBLE, answer
            )

    def test_a_client_sees_exactly_the_visible_items(self):
        self.run_import()
        cleo = User.objects.get(email="cleo@example.org")
        cleo.is_active = True
        cleo.save()
        seen = Item.objects.visible_to(cleo).exclude(kind=Kind.ANSWER)
        self.assertEqual(self.titles(seen), VISIBLE)
        # Through the pages
        self.client.force_login(cleo)
        for item in Item.objects.exclude(kind__in=[Kind.ANSWER, Kind.QUESTION]):
            with self.subTest(item.title):
                status = self.client.get(item.get_absolute_url()).status_code
                self.assertEqual(status, 200 if item.title in VISIBLE else 404)
        # In the feed and the comments: nothing internal in what clients get
        events = Event.objects.visible_to(cleo)
        self.assertTrue(events.exists())
        self.assertEqual(
            {e.item.title for e in events if e.item.kind != Kind.ANSWER} - VISIBLE,
            set(),
        )
        self.assertEqual(
            {c.item.title for c in Comment.objects.filter(item__in=seen)} - VISIBLE,
            set(),
        )

    def test_a_clients_internal_message_stays_internal(self):
        # Messages by clients are visible by definition; the importer
        # sets what Basecamp had
        self.run_import()
        prices = self.item("Prices")
        self.assertEqual(prices.creator.email, "cleo@example.org")
        self.assertFalse(prices.is_client_visible)
        self.assertFalse(prices.visible_to_clients)

    def test_visible_in_basecamp_but_a_container_changed(self):
        # A second run follows Basecamp: the list turned internal
        self.run_import()
        data = self.client_.data
        data["/todosets/300/todolists.json"][1]["visible_to_clients"] = False
        self.run_import()
        food = self.item("Buy giraffe food")
        self.assertFalse(food.is_client_visible)
        self.assertEqual(visibility.check(), [])


class NotifyNobodyTest(ImportCase):
    def setUp(self):
        super().setUp()
        # People with accounts, who would be told about everything
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)

    def test_nobody_is_told(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.run_import()
        self.assertTrue(Event.objects.filter(item__isnull=False).exists())
        self.assertFalse(Subscription.objects.filter(user=self.bob).count() == 0)
        self.assertEqual(Notification.objects.count(), 0)
        # Mails go after the commit: run those callbacks too, or nothing is
        # sent whatever is due (summaries of every imported check-in went
        # out, found 2026-11-22)
        with self.captureOnCommitCallbacks(execute=True):
            call_command("send_mails")
        self.assertEqual(mail.outbox, [])

    def test_a_second_run_tells_nobody_either(self):
        self.run_import()
        self.client_.data["/recordings/3011/comments.json"].append(
            support.recording(
                8003,
                "Comment",
                "Re: x",
                support.ADA,
                "2026-01-12T08:00:00.000Z",
                content=f"<div>Hi {support.mention(support.BOB)}</div>",
                content_attachments=[],
            )
        )
        self.client_.data["/todolists/301/todos.json"][0]["comments_count"] = 3
        with self.captureOnCommitCallbacks(execute=True):
            self.run_import()
        self.assertEqual(Notification.objects.count(), 0)
        self.assertEqual(Comment.objects.count(), 6)

    def test_the_same_event_outside_an_import_does_notify(self):
        # The control: what would have happened without importing()
        from biwak.items import operations as ops

        self.run_import()
        food = self.item("Buy giraffe food")
        with self.captureOnCommitCallbacks(execute=True):
            ops.add_comment(food, author=self.ada, content="Hello")
        self.assertEqual(Notification.objects.filter(user=self.bob).count(), 1)

    def test_existing_people_are_used_not_created(self):
        self.run_import()
        self.assertEqual(
            User.objects.filter(email__iexact="bob@example.org").count(), 1
        )
        self.assertTrue(User.objects.get(email="bob@example.org").is_active)
        self.assertEqual(
            Comment.objects.get(content="Done by Friday.").author, self.bob
        )


class QueriesTest(ImportCase):
    """The import may run against production through a tunnel, where every
    query counts (decided 2026-11-23): mappings and people are looked up
    once, not per object; the projects' activity is recomputed once per
    project, not touched by every event"""

    def test_the_first_run_stays_cheap(self):
        # 1,680 before the caches and recomputing the activity once. At most what it takes now, so lookups
        # per object don't creep back; not assertNumQueries, which every
        # change to the operations would break.
        with CaptureQueriesContext(connection) as queries:
            self.run_import()
        self.assertLessEqual(len(queries.captured_queries), 1421)

    def test_an_interrupted_run_leaves_the_activity_as_far_as_it_got(self):
        def fail(path):
            if path == "/vaults/400/vaults.json":
                raise ConnectionError("down")

        self.client_.on_request = fail
        with self.assertRaises(ConnectionError):
            self.run_import()
        events = Event.objects.filter(project=self.project)
        latest = lambda events: events.aggregate(Max("created_at"))["created_at__max"]  # noqa: E731
        self.assertIsNotNone(self.project.last_activity_at)
        self.assertEqual(self.project.last_activity_at, latest(events))
        self.assertEqual(
            self.project.last_client_activity_at,
            latest(events.filter(item__is_client_visible=True)),
        )
        self.client_.on_request = None
        self.run_import()
        self.assertEqual(self.project.last_activity_at, latest(events))


class SecondRunTest(ImportCase):
    def snapshot(self):
        return {
            model.__name__: model.objects.count()
            for model in (
                Item,
                Group,
                Comment,
                Attachment,
                Subscription,
                Event,
                Membership,
                Answer,
                Occurrence,
                User,
                ImportedObject,
                Bookmark,
            )
        }

    def test_a_second_run_changes_nothing(self):
        self.run_import()
        before = self.snapshot()
        events = set(Event.objects.values_list("pk", flat=True))
        downloads = len(self.client_.downloads)
        report = self.run_import()
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(set(Event.objects.values_list("pk", flat=True)), events)
        # Files aren't downloaded again; profile images only for Ada, whose
        # generated one wasn't kept
        self.assertEqual(len(self.client_.downloads), downloads + 1)
        self.assertEqual(report.counts["to-dos"]["created"], 0)
        self.assertEqual(report.counts["to-dos"]["updated"], 0)
        self.assertEqual(report.counts["to-dos"]["unchanged"], 6)
        self.assertEqual(visibility.check(), [])

    def test_unchanged_recordings_keep_their_times(self):
        """A rerun doesn't write Basecamp's times onto what it skips: an
        item changed in Biwak since keeps its own"""
        self.run_import()
        later = timezone.now()
        Item.objects.update(updated_at=later)
        self.run_import()
        self.assertEqual(
            set(Item.objects.values_list("updated_at", flat=True)), {later}
        )

    def test_people_assigned_since_the_last_run_at_the_last_change(self):
        self.run_import()
        food = self.item("Buy giraffe food")
        todo = self.client_.data["/todolists/301/todos.json"][0]
        todo["assignees"] = [*todo["assignees"], support.ADA]
        todo["updated_at"] = "2026-03-01T08:00:00.000Z"
        self.run_import()
        assigned = Event.objects.filter(item=food, action=Action.ASSIGNED)
        self.assertEqual(
            max((event.created_at, event.data["assignees"]) for event in assigned),
            (at("2026-03-01T08:00:00+00:00"), [self.ada.pk]),
        )
        # The first run's stay at the creation
        self.assertEqual(
            assigned.order_by("created_at").first().created_at, food.created_at
        )

    def test_a_columns_new_color(self):
        self.run_import()
        column = self.client_.data["/card_tables/600.json"]["lists"][1]
        column |= {"color": "aqua", "updated_at": "2026-03-01T08:00:00.000Z"}
        self.run_import()
        self.assertEqual(Group.objects.get(title="Cooking").color, "glacier")

    def test_a_second_run_updates_what_changed(self):
        self.run_import()
        food = self.item("Buy giraffe food")
        data = self.client_.data
        todo = data["/todolists/301/todos.json"][0]
        todo["title"] = todo["content"] = "Buy giraffe and zebra food"
        todo["description"] = "<div>New notes</div>"
        todo["due_on"] = "2026-07-01"
        todo["assignees"] = [support.BOB]
        todo["updated_at"] = "2026-03-01T08:00:00.000Z"
        todo["comments_count"] = 3
        changed = {"updated_at": "2026-03-01T08:00:00.000Z"}
        done = data["/todolists/301/todos.json?completed=true"][0]
        data["/todolists/301/todos.json"].append(done | {"completed": False} | changed)
        data["/todolists/301/todos.json?completed=true"] = []
        data["/recordings/3011/comments.json"].append(
            support.recording(
                8003,
                "Comment",
                "Re: x",
                support.BOB,
                "2026-02-01T08:00:00.000Z",
                content="<div>One more</div>",
                content_attachments=[],
            )
        )
        data["/vaults/400/documents.json"][1] |= {"content": "<div>New rules</div>"}
        data["/message_boards/200/messages.json"][1]["subject"] = "We have a camp!"
        data[f"/projects/{support.PROJECT}.json"]["name"] = "Camp kitchen 2"
        for rec in (
            data["/vaults/400/documents.json"][1],
            data["/message_boards/200/messages.json"][1],
            data[f"/projects/{support.PROJECT}.json"],
        ):
            rec.update(changed)
        self.run_import()
        food.refresh_from_db()
        self.assertEqual(food.title, "Buy giraffe and zebra food")
        self.assertEqual(food.todo.notes, "New notes")
        self.assertEqual(food.todo.due_on, dt.date(2026, 7, 1))
        self.assertEqual(self.names(food.todo.assignees.all()), {"Bob Example"})
        self.assertEqual(Item.objects.filter(kind=Kind.TODO).count(), 8)
        self.assertEqual(Comment.objects.filter(item=food).count(), 3)
        self.assertFalse(self.item("Pick a camp date").todo.is_completed)
        self.assertEqual(
            self.item("Camp rules").doc.content, "# Camp rules\n\nNew rules"
        )
        self.assertEqual(
            self.item("We have a camp!").pk, self.item("We have a camp!").pk
        )
        self.assertEqual(Project.objects.get().name, "Camp kitchen 2")
        self.assertEqual(Project.objects.count(), 1)
        # Completing in Basecamp completes here
        todo["completed"] = True
        todo["completion"] = {
            "created_at": "2026-03-02T08:00:00.000Z",
            "creator": support.BOB,
        }
        todo["updated_at"] = "2026-03-02T08:00:00.000Z"
        self.run_import()
        self.assertTrue(Todo.objects.get(item=food).is_completed)

    def test_changes_from_basecamp_name_nobody(self):
        """Basecamp says when a recording changed, never who changed it: what
        a later run brings over is recorded without a person, at Basecamp's
        time, noted as the import's (decided 2026-11-28: a to-do's creator
        who had left months before "edited" it)"""
        self.run_import()
        data = self.client_.data
        changed = {"updated_at": "2026-03-01T08:00:00.000Z"}
        todo = data["/todolists/301/todos.json"][0]
        todo |= {"title": "Buy zebra food", "content": "Buy zebra food"} | changed
        todo["assignees"] = [support.ADA]
        done = data["/todolists/301/todos.json?completed=true"][0]
        data["/todolists/301/todos.json"].append(done | {"completed": False} | changed)
        data["/todolists/301/todos.json?completed=true"] = []
        data["/message_boards/200/messages.json"][1] |= {"subject": "Camp!"} | changed
        self.run_import()
        events = Event.objects.filter(created_at=at("2026-03-01T08:00:00+00:00"))
        self.assertEqual(
            set(events.values_list("action", flat=True)),
            {Action.EDITED, Action.REOPENED, Action.ASSIGNED, Action.UNASSIGNED},
        )
        for event in events:
            with self.subTest(event.action):
                self.assertIsNone(event.actor)
                self.assertEqual(event.data.get("imported"), "basecamp")

    def test_the_backfill_of_earlier_runs(self):
        """activity 0025: what earlier runs recorded in the creator's name"""
        import importlib

        from django.apps import apps

        self.run_import()
        food = self.item("Buy giraffe food")
        rules = self.item("Camp rules")
        ms = at("2026-03-01T08:00:00.123000+00:00")

        def event(item, action, when, actor=None):
            return Event.objects.create(
                project=item.project,
                item=item,
                action=action,
                actor=actor or item.creator,
                created_at=when,
            )

        edited = event(food, Action.EDITED, ms)
        reopened = event(food, Action.REOPENED, ms)
        assigned_later = event(food, Action.ASSIGNED, ms)
        # Stay: at the creation, in Biwak, by somebody else, a doc
        assigned = event(food, Action.ASSIGNED, food.created_at)
        in_biwak = event(food, Action.EDITED, at("2026-03-01T08:00:00.123456+00:00"))
        somebody = User.objects.exclude(pk=food.creator_id).first()
        other = event(food, Action.EDITED, ms, actor=somebody)
        doc = event(rules, Action.EDITED, ms)
        migration = importlib.import_module(
            "biwak.activity.migrations.0025_imported_changes_without_actor"
        )
        migration.forget_actors(apps, None)
        for e in (edited, reopened, assigned_later):
            e.refresh_from_db()
            self.assertIsNone(e.actor)
            self.assertEqual(e.data["imported"], "basecamp")
        for name, e in {
            "assigned": assigned,
            "in Biwak": in_biwak,
            "other": other,
            "doc": doc,
        }.items():
            actor = e.actor_id
            e.refresh_from_db()
            self.assertEqual(e.actor_id, actor, name)
            self.assertNotIn("imported", e.data)

    def test_documents_get_their_title_as_a_heading_once(self):
        self.run_import()
        rules = self.item("Camp rules")
        self.assertTrue(rules.doc.content.startswith("# Camp rules\n\n"))
        self.run_import()
        rules.doc.refresh_from_db()
        self.assertEqual(rules.doc.content.count("# Camp rules"), 1)
        self.assertEqual(rules.title, "Camp rules")

    def test_the_visibility_switch_follows_basecamp(self):
        self.run_import()
        message = self.client_.data["/message_boards/200/messages.json"][1]
        message["visible_to_clients"] = False
        self.run_import()
        self.assertFalse(self.item("We have a camp").is_client_visible)

    def test_an_interrupted_run_continues(self):
        # The run stops in the middle (the connection fails)
        def fail(path):
            if path == "/vaults/400/vaults.json":
                raise ConnectionError("down")

        self.client_.on_request = fail
        with self.assertRaises(ConnectionError):
            self.run_import()
        partial = Item.objects.count()
        self.assertGreater(partial, 0)
        self.assertFalse(Item.objects.filter(kind=Kind.FOLDER).exists())
        self.client_.on_request = None
        self.run_import()
        # As after one run: what was there isn't there twice
        self.assertGreater(Item.objects.count(), partial)
        self.assertEqual(Project.objects.count(), 1)
        self.assertEqual(Item.objects.filter(kind=Kind.TODO).count(), 8)
        self.assertEqual(Item.objects.filter(kind=Kind.LIST).count(), 5)
        self.assertEqual(Item.objects.filter(kind=Kind.FOLDER).count(), 5)
        self.assertEqual(Membership.objects.count(), 3)
        self.assertEqual(Comment.objects.count(), 5)

    def test_a_deleted_object_is_imported_again(self):
        self.run_import()
        self.item("Peel potatoes").delete()
        self.run_import()
        self.assertEqual(Item.objects.filter(title="Peel potatoes").count(), 1)


class UndoingBiwakTest(ImportCase):
    """A second run sets Basecamp's state over what was changed in Biwak
    meanwhile; when Biwak's change is newer than Basecamp's, that happens
    now, by Biwak, noted as the Basecamp import (decided 2026-11-27)"""

    def run_again(self):
        importer = Importer(self.client_, actor=self.ada, full=True)
        importer.run(support.PROJECT)

    def last_event(self, item):
        return Event.objects.filter(item=item).latest("created_at", "pk")

    def lines(self, item):
        from biwak.activity import timeline

        return [
            str(line.text)
            for line in timeline.entries_for(item, self.ada, [])
            if getattr(line, "is_line", False)
        ]

    def test_completed_in_biwak_is_reopened_now(self):
        self.run_import()
        item = self.item("Raise the rate for Cleo")
        ops.complete(item, actor=self.ada)
        before = timezone.now()
        self.run_again()
        self.assertFalse(item.todo.__class__.objects.get(item=item).is_completed)
        event = self.last_event(item)
        self.assertEqual(event.action, Action.REOPENED)
        self.assertIsNone(event.actor)
        self.assertGreaterEqual(event.created_at, before)
        self.assertEqual(event.data["imported"], "basecamp")
        self.assertEqual(self.lines(item)[-2:], ["completed this", "reopened this"])

    def test_reopened_in_biwak_is_completed_now(self):
        self.run_import()
        item = self.item("Pick a camp date")
        ops.reopen(item, actor=self.ada)
        before = timezone.now()
        self.run_again()
        event = self.last_event(item)
        self.assertEqual(event.action, Action.COMPLETED)
        self.assertIsNone(event.actor)
        self.assertGreaterEqual(event.created_at, before)
        self.assertEqual(event.data["imported"], "basecamp")

    def test_the_page_says_so(self):
        self.run_import()
        item = self.item("Raise the rate for Cleo")
        ops.complete(item, actor=self.ada)
        self.run_again()
        self.client.force_login(self.ada)
        page = " ".join(
            self.client.get(item.get_absolute_url()).content.decode().split()
        )
        self.assertRegex(
            page, r"Biwak</strong> reopened this <span[^>]*>\(Basecamp import\)"
        )
        feed = " ".join(self.client.get("/feed/").content.decode().split())
        self.assertRegex(
            feed, r"reopened .*Raise the rate for Cleo.*\(Basecamp import\)"
        )


class UnchangedTest(ImportCase):
    """A later run skips recordings whose ``updated_at`` and comment count
    are as stored: no update, no requests for comments and subscribers"""

    def run_import(self, **kwargs):
        start = len(self.client_.requests)
        importer = Importer(self.client_, actor=self.ada, **kwargs)
        self.report = importer.run(support.PROJECT)
        return [path for path, _params in self.client_.requests[start:]]

    def following(self, paths):
        """The requests for comments and subscribers"""
        return sorted(
            p
            for p in paths
            if p.endswith(("/comments.json", "/replies.json", "/subscription.json"))
        )

    def test_a_later_run_saves_the_requests(self):
        first = self.run_import()
        self.assertGreater(len(self.following(first)), 20)
        second = self.run_import()
        self.assertEqual(self.following(second), [])
        # Everything else is read as before (containers' children too), but
        # the profile images of Bob and Cleo, which were imported
        self.assertEqual(len(second), len(first) - len(self.following(first)) - 2)
        self.assertEqual(self.report.counts["to-dos"]["unchanged"], 6)
        self.assertEqual(self.report.counts["messages"]["unchanged"], 2)
        self.assertEqual(self.report.counts["comments"], {})
        self.assertIn("to-dos: 0 new, 0 updated, 6 unchanged", self.report.as_text())

    def test_full_reads_everything(self):
        first = self.run_import()
        again = self.run_import(full=True)
        self.assertEqual(self.following(again), self.following(first))
        self.assertEqual(self.report.counts["to-dos"]["updated"], 6)
        self.assertNotIn("unchanged", self.report.as_text())

    def test_a_changed_recording_is_read(self):
        self.run_import()
        data = self.client_.data
        message = data["/message_boards/200/messages.json"][1]
        message["subject"] = "We have a camp!"
        message["updated_at"] = "2026-03-01T08:00:00.000Z"
        # A new comment changes the count, not necessarily ``updated_at``
        data["/todolists/301/todos.json"][0]["comments_count"] = 3
        data["/recordings/3011/comments.json"].append(
            support.recording(
                8003,
                "Comment",
                "Re: x",
                support.BOB,
                "2026-02-01T08:00:00.000Z",
                content="<div>One more</div>",
                content_attachments=[],
            )
        )
        paths = self.run_import()
        self.assertEqual(
            self.following(paths),
            [
                "/recordings/2001/comments.json",
                "/recordings/2001/subscription.json",
                "/recordings/3011/comments.json",
                "/recordings/3011/subscription.json",
            ],
        )
        self.assertTrue(Item.objects.filter(title="We have a camp!").exists())
        self.assertEqual(
            Comment.objects.filter(item__title="Buy giraffe food").count(), 3
        )
        counts = self.report.counts
        self.assertEqual(counts["messages"]["updated"], 1)
        self.assertEqual(counts["messages"]["unchanged"], 1)
        self.assertEqual(counts["comments"]["created"], 1)
        # Those of the message too, which were fetched again
        self.assertEqual(counts["comments"]["unchanged"], 3)
        # And then it's unchanged again
        self.assertEqual(self.following(self.run_import()), [])

    def test_new_children_of_unchanged_containers_are_found(self):
        self.run_import()
        todos = self.client_.data["/todolists/301/todos.json"]
        todos.append(todos[1] | {"id": 3099, "title": "Wash the pots"})
        self.run_import()
        self.assertTrue(Item.objects.filter(title="Wash the pots").exists())
        self.assertEqual(self.report.counts["lists"]["unchanged"], 3)

    def test_what_was_imported_before_is_read_once_completely(self):
        self.run_import()
        # As imported before the state was stored
        ImportedObject.objects.update(
            basecamp_updated_at=None, basecamp_comments_count=None
        )
        self.assertGreater(len(self.following(self.run_import())), 20)
        self.assertEqual(self.following(self.run_import()), [])

    def test_an_interrupted_recording_is_read_again(self):
        def fail(path):
            if path == "/recordings/3011/subscription.json":
                raise ConnectionError("down")

        self.client_.on_request = fail
        with self.assertRaises(ConnectionError):
            self.run_import()
        self.client_.on_request = None
        # Its comments were imported, its subscribers not yet: read again
        paths = self.following(self.run_import())
        self.assertIn("/recordings/3011/subscription.json", paths)
        self.assertEqual(
            Subscription.objects.filter(item__title="Buy giraffe food").count(), 2
        )

    def test_a_dry_run_reports_what_it_would_skip(self):
        self.run_import()
        paths = self.run_import(dry_run=True)
        self.assertEqual(self.following(paths), [])
        self.assertEqual(self.report.counts["to-dos"]["unchanged"], 6)
        self.assertIn("6 unchanged", self.report.as_text())

    def test_since_still_skips_what_is_older(self):
        self.run_import()
        todo = self.client_.data["/todolists/301/todos.json"][0]
        todo["title"] = "Buy zebra food"
        todo["updated_at"] = "2026-03-01T08:00:00.000Z"
        paths = self.run_import(since=at("2026-02-05T00:00:00+00:00"))
        self.assertTrue(Item.objects.filter(title="Buy zebra food").exists())
        self.assertEqual(
            self.following(paths),
            ["/recordings/3011/comments.json", "/recordings/3011/subscription.json"],
        )
        # The others are older: skipped by --since, not even counted
        self.assertEqual(self.report.counts["to-dos"]["updated"], 1)
        self.assertEqual(self.report.counts["to-dos"]["unchanged"], 0)


class ToolsTest(ImportCase):
    """Several tools of a kind are merged and named in the report;
    switched-off ones are skipped, the report says what's in them"""

    @property
    def dock(self):
        return self.client_.data[f"/projects/{support.PROJECT}.json"]["dock"]

    def switch_off(self, *names):
        for tool in self.dock:
            if tool["name"] in names:
                tool["enabled"] = False

    def add_todoset(self, *, enabled=True):
        """A second to-do set with a list and a to-do"""
        data = self.client_.data
        self.dock.append({
            "id": 310,
            "title": "Kitchen to-dos",
            "name": "todoset",
            "enabled": enabled,
        })
        data["/todosets/310.json"] = support.tool(
            "todoset", 310, "Kitchen to-dos", todolists_count=1, completed_ratio="0/1"
        )
        data["/todosets/310/todolists.json"] = [
            support.recording(
                311,
                "Todolist",
                "Dishes",
                support.ADA,
                "2026-01-06T10:00:00.000Z",
                description="",
                description_attachments=[],
            )
        ]
        data["/todosets/310/todolists.json?status=archived"] = []
        data["/todolists/311/todos.json"] = [
            data["/todolists/301/todos.json"][1] | {"id": 3111, "title": "Dry"}
        ]

    def test_several_of_a_kind_are_merged_and_listed(self):
        self.add_todoset()
        report = self.run_import()
        self.assertTrue(Item.objects.filter(title="Dishes").exists())
        self.assertTrue(Item.objects.filter(title="Kitchen plan").exists())
        self.assertEqual(
            report.several, ['Camp kitchen, To-dos: "To-dos", "Kitchen to-dos"']
        )
        self.assertIn(
            'Several tools of a kind, merged:\n  Camp kitchen, To-dos: "To-dos",',
            report.as_text(),
        )

    def test_one_of_each_kind_says_nothing(self):
        report = self.run_import()
        self.assertEqual(report.several, [])
        self.assertNotIn("Several tools", report.as_text())

    def test_switched_off_ones_are_skipped_and_listed(self):
        self.switch_off(
            "todoset",
            "kanban_board",
            "message_board",
            "vault",
            "questionnaire",
            "inbox",
        )
        report = self.run_import()
        self.assertFalse(Item.objects.exists())
        self.assertEqual(
            report.switched_off,
            [
                'Camp kitchen, Message board "Message Board": 2 messages',
                'Camp kitchen, To-dos "To-dos": 2 lists, 5 to-dos',
                'Camp kitchen, Docs & files "Docs & Files": 3 folders, 2 docs, 1 file',
                'Camp kitchen, Card table "Card Table": 2 cards',
                'Camp kitchen, Check-ins "Automatic Check-ins": 2 questions',
                'Camp kitchen, Email forwards "Email Forwards": 1 forward',
            ],
        )
        self.assertIn(
            "Switched off in Basecamp, not imported (--include-disabled imports"
            " them):\n  Camp kitchen, Message board",
            report.as_text(),
        )
        # One request each, for the tool itself, and nothing in them
        paths = [path for path, _params in self.client_.requests]
        for path in (
            "/todosets/300.json",
            "/message_boards/200.json",
            "/vaults/400.json",
            "/card_tables/600.json",
            "/questionnaires/500.json",
            "/inboxes/900.json",
        ):
            self.assertEqual(paths.count(path), 1)
        self.assertFalse(
            any(
                path.startswith((
                    "/todosets/300/",
                    "/message_boards/200/",
                    "/vaults/400/",
                    f"/buckets/{support.PROJECT}/inboxes/",
                ))
                for path in paths
            )
        )

    def test_empty_ones_stay_silent(self):
        self.switch_off("message_board", "kanban_board", "inbox")
        self.client_.data["/message_boards/200.json"]["messages_count"] = 0
        self.client_.data["/inboxes/900.json"]["forwards_count"] = 0
        for column in self.client_.data["/card_tables/600.json"]["lists"]:
            column["cards_count"] = 0
        report = self.run_import()
        self.assertEqual(report.switched_off, [])
        self.assertNotIn("Switched off", report.as_text())
        self.assertFalse(Item.objects.filter(kind=Kind.MESSAGE).exists())

    def test_tools_never_imported_are_ignored(self):
        # The chat and the schedule, switched off or not
        self.switch_off("chat", "schedule")
        report = self.run_import()
        self.assertEqual(report.switched_off, [])
        self.assertFalse([p for p in report.problems if "Switched-off" in p])
        paths = [path for path, _params in self.client_.requests]
        self.assertFalse(any(p.startswith(("/chats", "/schedules")) for p in paths))

    def test_a_dry_run_lists_them_too(self):
        self.switch_off("message_board")
        self.add_todoset()
        report = self.run_import(dry_run=True)
        self.assertEqual(
            report.switched_off,
            ['Camp kitchen, Message board "Message Board": 2 messages'],
        )
        self.assertEqual(len(report.several), 1)
        self.assertEqual(report.counts["messages"], {})

    def test_include_disabled_imports_them(self):
        self.switch_off("message_board")
        self.add_todoset(enabled=False)
        importer = Importer(self.client_, actor=self.ada, include_disabled=True)
        report = importer.run(support.PROJECT)
        self.assertEqual(report.switched_off, [])
        self.assertTrue(Item.objects.filter(title="We have a camp").exists())
        self.assertTrue(Item.objects.filter(title="Dishes").exists())
        self.assertEqual(len(report.several), 1)

    def test_a_tool_which_cant_be_checked_is_a_problem(self):
        self.switch_off("questionnaire")
        del self.client_.data["/questionnaires/500.json"]
        report = self.run_import()
        self.assertIn(
            "Switched-off tool 'Automatic Check-ins' (500) in Camp kitchen not checked",
            report.problems[-1],
        )


class ArchivedTest(ImportCase):
    def test_archived_recordings_are_skipped_and_reported(self):
        report = self.run_import()
        titles = set(Item.objects.values_list("title", flat=True))
        for title in [
            "Old announcement",
            "Old notes",
            "old.png",
        ]:
            self.assertNotIn(title, titles)
        # Basecamp lists no archived questions there (400, checked
        # 2026-11-22): they're neither imported nor reported
        self.assertEqual(len(report.archived), 3)

    def test_archived_to_dos_keep_their_comments_and_complete_once(self):
        self.client_.data["/recordings/3031/comments.json"] = [
            support.recording(
                9100,
                "Comment",
                "Re: Whale watching",
                support.BOB,
                "2026-01-09T09:00:00.000Z",
                parent={"id": 3031, "type": "Todo", "title": "Whale watching"},
                content="Too cold",
                content_attachments=[],
            )
        ]
        for rec in self.client_.data["/todolists/303/todos.json?status=archived"]:
            rec["comments_count"] = 1
        self.run_import()
        self.run_import()
        whale = self.item("Whale watching")
        self.assertTrue(whale.todo.is_completed)
        self.assertEqual(Comment.objects.filter(item=whale).count(), 1)
        self.assertEqual(
            Event.objects.filter(item=whale, action="completed").count(), 1
        )

    def test_archived_lists_stay_archived(self):
        self.run_import()
        self.assertEqual(self.item("Old ideas").status, Status.ARCHIVED)


class FileCountTest(ImportCase):
    def test_the_report_counts_files_downloaded_and_from_the_cache(self):
        """The client's counts; profile images (never cached) aren't files"""
        report = self.run_import()
        files = [url for url in self.client_.downloads if "avatar" not in url]
        self.assertTrue(files)
        self.assertEqual(report.files["downloaded"], len(files))
        self.assertIn(
            f"  Files: {len(files)} downloaded, 0 from the cache", report.as_text()
        )
        self.client_.file_counts.update({"cached": 2, "not redirected": 1})
        self.assertIn(
            " 2 from the cache (1 answered without a redirect, not cached)",
            report.as_text(),
        )

    def test_the_report_counts_answers_from_the_cache(self):
        report = self.run_import()
        self.assertNotIn("Basecamp answers", report.as_text())
        self.client_.answer_counts["cached"] = 7
        self.assertIn("  Basecamp answers: 7 from the cache", report.as_text())

    def test_a_dry_run_counts_no_files(self):
        report = self.run_import(dry_run=True)
        self.assertNotIn("Files:", report.as_text())


class DryRunTest(ImportCase):
    def test_writes_nothing(self):
        report = self.run_import(dry_run=True)
        self.assertTrue(report.dry_run)
        self.assertEqual(Project.objects.count(), 0)
        self.assertEqual(Item.objects.count(), 0)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(ImportedObject.objects.count(), 0)
        self.assertEqual(Attachment.objects.count(), 0)
        self.assertEqual(Event.objects.count(), 0)
        self.assertEqual(self.client_.downloads, [])

    def test_counts_people_and_problems(self):
        report = self.run_import(dry_run=True)
        counts = {label: c["created"] for label, c in report.counts.items()}
        self.assertEqual(counts["projects"], 1)
        self.assertEqual(counts["lists"], 3)
        self.assertEqual(counts["card tables"], 1)
        self.assertEqual(counts["to-dos"], 6)
        self.assertEqual(counts["cards"], 2)
        self.assertEqual(counts["groups"], 1)
        self.assertEqual(counts["columns"], 3)
        self.assertEqual(counts["messages"], 2)
        self.assertEqual(counts["folders"], 4)
        self.assertEqual(counts["docs"], 5)
        self.assertEqual(counts["files"], 3)
        self.assertEqual(counts["check-in questions"], 2)
        self.assertEqual(counts["check-in answers"], 4)
        self.assertEqual(counts["comments"], 4)
        self.assertEqual(
            sorted(report.people),
            [
                "Bob Example <bob@example.org> (staff, active, Example Team)",
                "Cleo Example <cleo@example.org> (client, Example Client Ltd)",
            ],
        )
        self.assertEqual(len(report.internal), 2)
        text = report.as_text()
        self.assertIn("Dry run", text)
        self.assertIn("Raise the rate for Cleo", text)
        self.assertIn("to-dos: 6 new", text)

    def test_lists_archived_recordings_it_skips(self):
        report = self.run_import(dry_run=True)
        self.assertEqual(
            report.archived,
            [
                "message: Old announcement",
                "doc: Old notes",
                "file: old.png",
            ],
        )
        text = report.as_text()
        self.assertIn("Archived in Basecamp, skipped:", text)
        self.assertIn("  doc: Old notes", text)

    def test_after_a_run_it_counts_existing_ones(self):
        self.run_import()
        report = self.run_import(dry_run=True)
        self.assertEqual(report.counts["to-dos"]["unchanged"], 6)
        self.assertEqual(report.counts["to-dos"]["created"], 0)
        self.assertEqual(report.people, [])


class SinceTest(ImportCase):
    def test_only_what_changed_since(self):
        self.run_import(since=at("2026-02-05T00:00:00+00:00"))
        # Containers always, leaves only when changed since
        self.assertTrue(Item.objects.filter(title="Kitchen plan").exists())
        self.assertFalse(Item.objects.filter(title="Buy giraffe food").exists())
        self.assertFalse(Item.objects.filter(title="Camp rules").exists())
        self.assertTrue(Item.objects.filter(kind=Kind.ANSWER).exists())
        self.assertFalse(Comment.objects.exists())


class PeopleTest(ImportCase):
    def test_companies_become_organizations(self):
        """Clients' and collaborators' companies, by name ignoring case and
        spaces; employees in the own organization, if one is
        marked (specs/organizations.md)"""
        own = organization("Example Team", is_own=True)
        existing = organization("Example client LTD")
        people = self.client_.data[f"/projects/{support.PROJECT}/people.json"]
        freelancer = support.person(
            5,
            "Finn Example",
            "finn@example.org",
            company={"id": 11, "name": "Example  Freelance"},
        ) | {"employee": False}
        people.append(freelancer)
        report = self.run_import()
        bob = User.objects.get(email="bob@example.org")
        self.assertEqual(bob.organization, own)
        self.assertFalse(bob.is_external)
        cleo = User.objects.get(email="cleo@example.org")
        self.assertEqual(cleo.organization, existing)
        finn = User.objects.get(email="finn@example.org")
        self.assertEqual(finn.organization.name, "Example Freelance")
        self.assertTrue(finn.is_external)
        self.assertIn(
            "Finn Example <finn@example.org> (external, Example  Freelance)",
            report.people,
        )

    def test_employees_in_the_own_organization_which_always_exists(self):
        self.run_import()
        bob = User.objects.get(email="bob@example.org")
        self.assertTrue(bob.organization.is_own)
        self.assertFalse(bob.is_external)

    def test_the_own_company_is_the_own_organization_whatever_its_name(self):
        # On a real account the own organization was renamed: collaborators
        # of the employees' company got a new organization of its old name
        # on every run (fixed 2026-11-22)
        own = Organization.objects.own()
        own.name = "Our Agency AG"
        own.save()
        people = self.client_.data[f"/projects/{support.PROJECT}/people.json"]
        people.append(
            support.person(
                7, "Hal Example", "hal@example.org", company=support.BOB["company"]
            )
            | {"employee": False}
        )
        self.run_import()
        self.assertEqual(User.objects.get(email="bob@example.org").organization, own)
        hal = User.objects.get(email="hal@example.org")
        self.assertTrue(hal.is_external)
        self.assertIsNone(hal.organization)
        self.assertFalse(Organization.objects.filter(name="Example Team").exists())

    def test_merged_organizations_stay_merged(self):
        from biwak.organizations import operations as org_ops

        self.run_import()
        cleo = User.objects.get(email="cleo@example.org")
        imported = cleo.organization
        clients = Organization.objects.create(name="Clients AG")
        org_ops.merge(imported, clients, actor=self.ada)
        people = self.client_.data[f"/projects/{support.PROJECT}/people.json"]
        people.append(
            support.person(
                8,
                "Ivy Example",
                "ivy@example.org",
                client=True,
                company=support.CLEO["company"],
            )
        )
        self.run_import()
        self.assertEqual(
            User.objects.get(email="ivy@example.org").organization, clients
        )
        self.assertFalse(Organization.objects.filter(name=imported.name).exists())

    def test_collaborators_without_a_company_are_individual_externals(self):
        people = self.client_.data[f"/projects/{support.PROJECT}/people.json"]
        people.append(
            support.person(6, "Gus Example", "gus@example.org") | {"employee": False}
        )
        self.run_import()
        gus = User.objects.get(email="gus@example.org")
        self.assertIsNone(gus.organization)
        self.assertTrue(gus.is_external)

    def test_without_a_company_the_domain_decides(self):
        """As for invitations (decided 2026-11-23): people removed from
        Basecamp have no company; free-mail domains never match, a company
        keeps deciding"""
        own = organization("Example Team", is_own=True, domains=["team.example"])
        client_org = organization("Example Shop", domains=["shop.example"])
        people = self.client_.data[f"/projects/{support.PROJECT}/people.json"]
        people.extend([
            support.person(6, "Gus Example", "gus@team.example") | {"employee": False},
            support.person(7, "Hal Example", "hal@shop.example", client=True),
            support.person(8, "Ivy Example", "ivy@gmail.com", client=True),
            support.person(
                9,
                "Jo Example",
                "jo@shop.example",
                client=True,
                company={"id": 12, "name": "Example Market"},
            ),
        ])
        report = self.run_import(dry_run=True)
        self.assertIn(
            "Gus Example <gus@team.example> (staff, Example Team by the address)",
            report.people,
        )
        self.assertIn(
            "Hal Example <hal@shop.example> (client, Example Shop by the address)",
            report.people,
        )
        self.assertIn("Ivy Example <ivy@gmail.com> (client)", report.people)
        self.assertIn(
            "Jo Example <jo@shop.example> (client, Example Market)", report.people
        )
        self.run_import()
        gus = User.objects.get(email="gus@team.example")
        self.assertEqual(gus.organization, own)
        self.assertFalse(gus.is_external)
        self.assertFalse(gus.is_active)  # Waits to be activated, as before
        self.assertEqual(
            User.objects.get(email="hal@shop.example").organization, client_org
        )
        self.assertIsNone(User.objects.get(email="ivy@gmail.com").organization)
        self.assertEqual(
            User.objects.get(email="jo@shop.example").organization.name,
            "Example Market",
        )

    def test_the_domain_gives_the_own_organization_only_for_admins(self):
        self.ada.is_admin = False
        self.ada.save()
        organization("Example Team", is_own=True, domains=["team.example"])
        people = self.client_.data[f"/projects/{support.PROJECT}/people.json"]
        people.append(
            support.person(6, "Gus Example", "gus@team.example") | {"employee": False}
        )
        report = self.run_import(dry_run=True)
        self.assertIn("Gus Example <gus@team.example> (external)", report.people)
        self.run_import()
        self.assertIsNone(User.objects.get(email="gus@team.example").organization)

    def test_own_staff_gone_from_basecamp_stay_inactive(self):
        tombstone = support.BOB | {"personable_type": "Tombstone"}
        people = self.client_.data[f"/projects/{support.PROJECT}/people.json"]
        people[1] = tombstone
        self.run_import()
        self.assertFalse(User.objects.get(email="bob@example.org").is_active)

    def test_excluded_projects_are_skipped(self):
        with mock.patch.object(importer_module, "EXCLUDED", {support.PROJECT}):
            report = self.run_import()
        self.assertFalse(Project.objects.exists())
        self.assertFalse(User.objects.filter(email="bob@example.org").exists())
        self.assertTrue(any("excluded" in p for p in report.problems))
        # Only the project itself was read
        self.assertEqual(
            [r[0] for r in self.client_.requests], [f"/projects/{support.PROJECT}.json"]
        )

    def test_basecamps_sample_project_is_refused(self):
        # Its people are made up: DummyUser, example.com (checked against a
        # real account 2026-11-22); nothing of it is imported
        people = self.client_.data[f"/projects/{support.PROJECT}/people.json"]
        people[1] = people[1] | {"personable_type": "DummyUser"}
        report = self.run_import()
        self.assertFalse(Project.objects.exists())
        self.assertFalse(User.objects.filter(email="bob@example.org").exists())
        self.assertTrue(any("sample project" in p for p in report.problems))

    def test_a_dummy_person_elsewhere_stops_the_import(self):
        # A creator nobody listed among the project's people
        sample = support.person(99, "Sample Person", "sample@example.com")
        sample["personable_type"] = "DummyUser"
        found = 0
        for value in self.client_.data.values():
            for rec in value if isinstance(value, list) else [value]:
                if isinstance(rec, dict) and rec.get("title") == "Buy giraffe food":
                    rec["creator"] = sample
                    found += 1
        self.assertTrue(found)
        with self.assertRaises(ImportRefused):
            self.run_import()

    def test_redacted_addresses_become_placeholders(self):
        # Only administrators get addresses (sections/people.md)
        people = self.client_.data[f"/projects/{support.PROJECT}/people.json"]
        people[1] = people[1] | {"email_address": "b••••@••••••.org"}
        report = self.run_import()
        bob = User.objects.get(full_name="Bob Example")
        self.assertEqual(bob.email, f"basecamp-{support.BOB['id']}@import.invalid")
        self.assertFalse(bob.is_active)
        self.assertTrue(any("No email address for Bob" in p for p in report.problems))

    def test_a_mention_of_somebody_not_in_the_list_is_found_by_its_global_id(self):
        # Not in the project's people: the signed global ID names Cleo
        importer = Importer(self.client_, actor=self.ada)
        importer.run(support.PROJECT)
        cleo = User.objects.get(email="cleo@example.org")
        importer._people_by_sgid.clear()
        self.assertEqual(importer.user_for_sgid(support.CLEO["attachable_sgid"]), cleo)
        self.assertIsNone(importer.user_for_sgid("nonsense"))

    def test_imported_people_get_marks_like_everybody(self):
        """The one fewest people of the organization have (specs/people.md):
        imported people wait to be activated and count too, so staff
        imported together get different ones"""
        people = self.client_.data[f"/projects/{support.PROJECT}/people.json"]
        people.append(support.person(7, "Finn Example", "finn@example.org"))
        self.run_import()
        staff = User.objects.filter(organization__is_own=True)
        self.assertEqual(staff.count(), 3)
        self.assertEqual(len(set(staff.values_list("mark", flat=True))), 3)
        cleo = User.objects.get(email="cleo@example.org")
        self.assertEqual(cleo.mark, "tent")  # the first of her organization

    def test_staff_and_clients_as_in_basecamp(self):
        self.run_import()
        self.assertEqual(
            dict(User.objects.values_list("email", "is_client")),
            {
                "ada@example.org": False,
                "bob@example.org": False,
                "cleo@example.org": True,
            },
        )
        # Nobody becomes an administrator
        self.assertEqual(User.objects.filter(is_admin=True).count(), 1)


LEFT_ON = dt.date(2025, 3, 3)


class PeopleWhoLeftTest(ImportCase):
    """Who turns up in a project but isn't among the account's people
    anymore has left Basecamp (specs/activation.md, "People who left")"""

    def leave(self, *people):
        ids = {p["id"] for p in people}
        self.client_.data["/people.json"] = [
            p for p in self.client_.data["/people.json"] if p["id"] not in ids
        ]

    def left_at(self, email):
        return User.objects.get(email=email).left_at

    def account_reads(self):
        return [r for r in self.client_.requests if r[0] == "/people.json"]

    def test_people_still_in_the_account_wait_to_be_activated(self):
        report = self.run_import()
        self.assertEqual(report.left, [])
        self.assertIsNone(self.left_at("bob@example.org"))
        self.assertNotIn("People who left", report.as_text())

    def test_people_gone_from_the_account_have_left(self):
        self.leave(support.BOB)
        report = self.run_import()
        bob = User.objects.get(email="bob@example.org")
        self.assertFalse(bob.is_active)
        self.assertEqual(bob.left_at, timezone.localdate())
        self.assertIsNone(self.left_at("cleo@example.org"))
        self.assertEqual(report.left, ["Bob Example <bob@example.org>"])
        self.assertIn(
            "People who left Basecamp:\n  Bob Example <bob@example.org>",
            report.as_text(),
        )
        # Read once per run, for several projects too
        self.assertEqual(len(self.account_reads()), 1)

    def test_a_tombstone_in_the_account_has_left(self):
        # /people.json lists removed people too, as tombstones (checked
        # against a real account 2026-11-22)
        self.client_.data["/people.json"] = [
            p | {"personable_type": "Tombstone"} if p["id"] == support.CLEO["id"] else p
            for p in self.client_.data["/people.json"]
        ]
        report = self.run_import()
        self.assertEqual(self.left_at("cleo@example.org"), timezone.localdate())
        self.assertEqual(report.left, ["Cleo Example <cleo@example.org>"])

    def test_read_once_for_several_projects(self):
        self.leave(support.BOB)
        importer = Importer(self.client_, actor=self.ada)
        importer.run(support.PROJECT)
        importer.run(support.PROJECT)
        self.assertEqual(len(self.account_reads()), 1)
        self.assertEqual(importer.report.left, ["Bob Example <bob@example.org>"])

    def test_active_people_are_not_touched(self):
        bob = person("Bob")
        bob.email = "bob@example.org"
        bob.save()
        self.leave(support.BOB)
        report = self.run_import()
        bob.refresh_from_db()
        self.assertTrue(bob.is_active)
        self.assertIsNone(bob.left_at)
        self.assertEqual(report.left, [])

    def test_the_day_they_left_stays(self):
        self.leave(support.BOB)
        self.run_import()
        User.objects.filter(email="bob@example.org").update(left_at=dt.date(2025, 3, 3))
        report = self.run_import()
        self.assertEqual(self.left_at("bob@example.org"), dt.date(2025, 3, 3))
        self.assertEqual(report.left, [])

    def test_people_back_in_the_account_are_cleared(self):
        """Decided 2026-11-22: a date the import set (gone from Basecamp) is
        cleared when they are back; they wait to be activated again"""
        account = list(self.client_.data["/people.json"])
        self.leave(support.BOB)
        self.run_import()
        bob = User.objects.get(email="bob@example.org")
        self.assertTrue(bob.left_in_basecamp)
        self.client_.data["/people.json"] = account
        report = self.run_import(dry_run=True)
        self.assertEqual(report.back, ["Bob Example <bob@example.org>"])
        self.assertIn("Back in Basecamp:\n  Bob Example", report.as_text())
        self.assertEqual(self.left_at("bob@example.org"), timezone.localdate())
        report = self.run_import()
        self.assertEqual(report.back, ["Bob Example <bob@example.org>"])
        self.assertEqual(report.left, [])
        bob.refresh_from_db()
        self.assertIsNone(bob.left_at)
        self.assertFalse(bob.left_in_basecamp)
        self.assertEqual(self.run_import().back, [])

    def test_deactivated_in_biwak_stays_whatever_basecamp_lists(self):
        from biwak.organizations import activation

        self.run_import()
        bob = User.objects.get(email="bob@example.org")
        User.objects.filter(pk=bob.pk).update(is_active=True)
        activation.deactivate([bob], actor=self.ada)
        for dry_run in [True, False]:
            with self.subTest(dry_run=dry_run):
                report = self.run_import(dry_run=dry_run)
                self.assertEqual(report.back, [])
                self.assertEqual(self.left_at("bob@example.org"), timezone.localdate())

    def test_a_dry_run_reports_and_writes_nothing(self):
        self.leave(support.BOB)
        report = self.run_import(dry_run=True)
        self.assertEqual(report.left, ["Bob Example <bob@example.org>"])
        self.assertIn("People who left Basecamp:", report.as_text())
        self.assertFalse(User.objects.filter(email="bob@example.org").exists())
        # People who exist, inactive, are reported and not changed
        self.run_import()
        User.objects.filter(email="bob@example.org").update(left_at=None)
        report = self.run_import(dry_run=True)
        self.assertEqual(report.left, ["Bob Example <bob@example.org>"])
        self.assertIsNone(self.left_at("bob@example.org"))

    def test_people_met_only_in_comments_of_skipped_recordings(self):
        """Somebody met only as the author of a comment on a recording that
        later runs skip (unchanged, its comments aren't read again) is
        checked too: every person imported from the account, not only
        those met in this run (fixed 2026-11-28: a run stopped halfway left
        one behind, its restart skipped the message she had commented on)"""
        # A client: imported inactive, waiting to be activated
        gil = support.person(8, "Gil Example", "gil@example.org", client=True)
        self.client_.data["/people.json"].append(gil)
        self.client_.data["/recordings/3011/comments.json"][0]["creator"] = gil
        self.run_import()
        self.assertIsNone(self.left_at("gil@example.org"))
        self.client_.data["/people.json"] = [
            p | {"personable_type": "Tombstone"} if p["id"] == gil["id"] else p
            for p in self.client_.data["/people.json"]
        ]
        report = self.run_import()
        self.assertEqual(report.counts["comments"]["created"], 0)
        self.assertEqual(report.left, ["Gil Example <gil@example.org>"])
        self.assertEqual(self.left_at("gil@example.org"), timezone.localdate())

    def test_later_runs_read_the_account_every_time(self):
        """Skipping unchanged recordings or reading everything with
        ``--full``: the account's people are read either way"""
        self.run_import()
        self.leave(support.CLEO)
        report = Importer(self.client_, actor=self.ada).run(support.PROJECT)
        self.assertEqual(report.counts["to-dos"]["created"], 0)
        self.assertEqual(report.left, ["Cleo Example <cleo@example.org>"])
        self.assertEqual(self.left_at("cleo@example.org"), timezone.localdate())
        # Bob is own staff, imported active: active people aren't touched
        self.leave(support.BOB)
        report = Importer(self.client_, actor=self.ada, full=True).run(support.PROJECT)
        self.assertEqual(report.left, [])
        self.assertEqual(len(self.account_reads()), 3)


class ScheduleTest(ImportCase):
    def schedule(self, **kwargs):
        from biwak.importer.importer import schedule_of

        base = {
            "frequency": "every_day",
            "days": [],
            "hour": 17,
            "minute": 30,
            "week_instance": None,
            "week_interval": None,
            "month_interval": None,
            "start_date": "2026-02-11",  # a Wednesday
        }
        return schedule_of(base | kwargs)

    def test_rules_are_stored_in_canonical_form(self):
        rule, starts_on, time_of_day = self.schedule(
            frequency="on_certain_days", days=["5", "1"]
        )
        self.assertEqual(rule, "FREQ=WEEKLY;BYDAY=MO,FR")
        self.assertEqual(starts_on, dt.date(2026, 2, 11))
        self.assertEqual(time_of_day, dt.time(17, 30))

    def test_the_frequencies(self):
        self.assertEqual(self.schedule()[0], "FREQ=DAILY")
        self.assertEqual(
            self.schedule(days=[1, 2, 3, 4, 5])[0], "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"
        )
        self.assertEqual(
            self.schedule(frequency="every_week", days=[0])[0], "FREQ=WEEKLY;BYDAY=SU"
        )
        # Without days: the first date's weekday
        self.assertEqual(
            self.schedule(frequency="every_week")[0], "FREQ=WEEKLY;BYDAY=WE"
        )
        self.assertEqual(
            self.schedule(frequency="every_other_week", days=[2])[0],
            "FREQ=WEEKLY;INTERVAL=2;BYDAY=TU",
        )
        self.assertEqual(
            self.schedule(frequency="every_month")[0], "FREQ=MONTHLY;BYMONTHDAY=11"
        )
        self.assertEqual(
            self.schedule(frequency="every_month", month_interval=3)[0],
            "FREQ=MONTHLY;INTERVAL=3;BYMONTHDAY=11",
        )
        self.assertEqual(
            self.schedule(frequency="every_month", start_date="2026-01-31")[0],
            "FREQ=MONTHLY;BYMONTHDAY=28,29,30,31;BYSETPOS=-1",
        )
        self.assertEqual(
            self.schedule(frequency="every_month", week_instance=2, days=[1])[0],
            "FREQ=MONTHLY;BYDAY=MO;BYSETPOS=2",
        )
        # "The last Monday": whether Basecamp says -1 or 5, it's the last
        # one, also in months with only four Mondays
        for last in (-1, 5):
            with self.subTest(week_instance=last):
                self.assertEqual(
                    self.schedule(
                        frequency="every_month", week_instance=last, days=[1]
                    )[0],
                    "FREQ=MONTHLY;BYDAY=MO;BYSETPOS=-1",
                )

    def test_unknown_frequencies_are_a_problem_not_a_crash(self):
        self.client_.data["/questionnaires/500/questions.json"][0]["schedule"][
            "frequency"
        ] = "every_decade"
        report = self.run_import()
        self.assertTrue(any("unknown frequency" in p for p in report.problems))
        self.assertFalse(
            Question.objects.filter(item__title="What did you cook today?").exists()
        )
        self.assertTrue(Question.objects.filter(item__title="Any worries?").exists())

    def test_imported_questions_are_paused_and_never_asked(self):
        self.run_import()
        occurrences = Occurrence.objects.count()
        self.assertEqual(Question.objects.filter(paused_at__isnull=True).count(), 0)
        self.assertEqual(Question.objects.exclude(next_at=None).count(), 0)
        with self.captureOnCommitCallbacks(execute=True):
            call_command("send_mails")
        self.assertEqual(Occurrence.objects.count(), occurrences)
        self.assertEqual(mail.outbox, [])


class CommandTest(ImportCase):
    def setUp(self):
        super().setUp()
        self.err = io.StringIO()  # the progress lines

    def call(self, *args, token="secret", **kwargs):
        out = io.StringIO()
        with (
            mock.patch.dict(
                "os.environ", {"BASECAMP_TOKEN": token} if token else {}, clear=False
            ),
            mock.patch(
                "biwak.importer.management.commands.import_basecamp.make_client",
                return_value=self.client_,
            ) as make,
        ):
            call_command(
                "import_basecamp", *args, stdout=out, stderr=self.err, **kwargs
            )
        return out.getvalue(), make

    def test_progress_while_it_runs(self):
        """On stderr by default: the project, its people, each tool, a line
        every 25 items and a summary; -v 0 prints none"""
        self.call("--account", "1000", "--project", str(support.PROJECT))
        progress = self.err.getvalue()
        self.assertIn(f"[1/1] Basecamp project {support.PROJECT}", progress)
        self.assertIn("people", progress)
        self.assertIn("  To-dos", progress)
        self.assertIn("  Message board", progress)
        self.assertIn("  done: ", progress)
        self.assertIn(" requests, ", progress)
        self.err = io.StringIO()
        self.call("--account", "1000", "--project", str(support.PROJECT), verbosity=0)
        self.assertEqual(self.err.getvalue(), "")

    def test_runs_as_the_person_of_the_token(self):
        # The profile says Ada
        text, make = self.call("--account", "1000", "--project", str(support.PROJECT))
        make.assert_called_once_with(
            "1000",
            "secret",
            cache_dir=client_api.default_cache_dir(),
            answers_max_age=3600,
            renew_token=None,
        )
        self.assertIn("Imported.", text)
        self.assertIn("to-dos: 6 new", text)
        self.assertEqual(Project.objects.count(), 1)
        self.assertEqual(
            Project.objects.get().memberships.filter(user=self.ada).count(), 1
        )

    def test_dry_run(self):
        text, _make = self.call(
            "--account", "1000", "--project", str(support.PROJECT), "--dry-run"
        )
        self.assertIn("Dry run", text)
        self.assertIn("People to create:", text)
        self.assertEqual(Project.objects.count(), 0)

    def test_since_and_user(self):
        self.call(
            "--account",
            "1000",
            "--project",
            str(support.PROJECT),
            "--since",
            "2026-02-05",
            "--user",
            "ada@example.org",
        )
        self.assertFalse(Item.objects.filter(title="Camp rules").exists())

    def test_full(self):
        args = ("--account", "1000", "--project", str(support.PROJECT))
        self.call(*args)
        text, _make = self.call(*args)
        self.assertIn("to-dos: 0 new, 0 updated, 6 unchanged", text)
        text, _make = self.call(*args, "--full")
        self.assertIn("to-dos: 0 new, 6 updated", text)
        self.assertNotIn("unchanged", text)

    def test_include_disabled(self):
        dock = self.client_.data[f"/projects/{support.PROJECT}.json"]["dock"]
        dock[0]["enabled"] = False  # the message board
        args = ("--account", "1000", "--project", str(support.PROJECT))
        text, _make = self.call(*args, "--dry-run")
        self.assertIn('Message board "Message Board": 2 messages', text)
        text, _make = self.call(*args, "--include-disabled")
        self.assertNotIn("Switched off", text)
        self.assertIn("messages: 2 new", text)

    def test_archive(self):
        args = ("--account", "1000", "--project", str(support.PROJECT), "--archive")
        text, _make = self.call(*args, "--dry-run")
        self.assertIn("Projects to archive in Basecamp:\n  Camp kitchen", text)
        self.assertEqual(self.client_.archived_projects, [])

        text, _make = self.call(*args)
        self.assertIn("Projects archived in Basecamp:\n  Camp kitchen", text)
        self.assertEqual(self.client_.archived_projects, [support.PROJECT])

    def test_no_archiving_without_the_option(self):
        self.call("--account", "1000", "--project", str(support.PROJECT))
        self.assertEqual(self.client_.archived_projects, [])

    def test_archived_projects_are_not_archived_again(self):
        self.client_.data[f"/projects/{support.PROJECT}.json"]["status"] = "archived"
        text, _make = self.call(
            "--account", "1000", "--project", str(support.PROJECT), "--archive"
        )
        self.assertNotIn("archived in Basecamp:", text)
        self.assertEqual(self.client_.archived_projects, [])

    def test_a_failed_import_archives_nothing(self):
        def fail(path):
            if path.startswith("/todolists/"):
                raise RuntimeError("Connection lost")

        self.client_.on_request = fail
        with self.assertRaises(RuntimeError):
            self.call(
                "--account", "1000", "--project", str(support.PROJECT), "--archive"
            )
        self.assertEqual(self.client_.archived_projects, [])

    def test_cache_options(self):
        """On by default; --cache-dir elsewhere, --no-cache off (the client
        is a fake: nothing touches a real cache)"""
        args = ["--account", "1000", "--project", str(support.PROJECT)]
        _text, make = self.call(*args, "--cache-dir", "/srv/somewhere")
        make.assert_called_once_with(
            "1000",
            "secret",
            cache_dir="/srv/somewhere",
            answers_max_age=3600,
            renew_token=None,
        )
        _text, make = self.call(*args, "--no-cache")
        make.assert_called_once_with(
            "1000", "secret", cache_dir=None, answers_max_age=3600, renew_token=None
        )
        _text, make = self.call(*args, "--answers-max-age", "0.5")
        self.assertEqual(make.call_args.kwargs["answers_max_age"], 1800)
        with self.assertRaisesMessage(CommandError, "not both"):
            self.call(*args, "--no-cache", "--cache-dir", "/srv/somewhere")

    def test_make_client(self):
        import tempfile

        from biwak.importer.management.commands.import_basecamp import make_client

        with tempfile.TemporaryDirectory() as directory:
            client = make_client("1000", "secret", cache_dir=directory)
            self.assertEqual(str(client.cache.directory), directory)
        self.assertIsNone(make_client("1000", "secret").cache)

    def test_needs_a_token(self):
        with (
            mock.patch.dict("os.environ", {}, clear=False),
            self.assertRaisesMessage(CommandError, "BASECAMP_TOKEN"),
        ):
            import os

            os.environ.pop("BASECAMP_TOKEN", None)
            call_command("import_basecamp", "--account", "1", "--project", "2")

    def test_a_token_command(self):
        """For the token, and again when Basecamp refuses it: run without
        BASECAMP_TOKEN, which the Basecamp CLI would echo"""
        command = "sh -c 'echo ${BASECAMP_TOKEN:-fresh}'"
        _text, make = self.call(
            "--account",
            "1000",
            "--project",
            str(support.PROJECT),
            "--token-command",
            command,
            token=None,
        )
        self.assertEqual(make.call_args.args, ("1000", "fresh"))
        renew = make.call_args.kwargs["renew_token"]
        with mock.patch.dict("os.environ", {"BASECAMP_TOKEN": "stale"}):
            self.assertEqual(renew(), "fresh")
        with self.assertRaisesMessage(CommandError, "--token-command"):
            self.call(
                "--account",
                "1000",
                "--project",
                "1",
                "--token-command",
                "false",
                token=None,
            )

    def test_a_refused_token_stops_the_run(self):
        """What was imported stays; the message says how to go on"""

        def refuse(path):
            if path == "/vaults/400/vaults.json":
                raise client_api.Unauthorized(path)

        self.client_.on_request = refuse
        args = ("--account", "1000", "--project", str(support.PROJECT))
        with self.assertRaisesMessage(CommandError, "--token-command"):
            self.call(*args)
        self.assertEqual(Project.objects.count(), 1)
        with self.assertRaisesMessage(CommandError, "also the one 'echo x' gave"):
            self.call(*args, "--token-command", "echo x")

    def test_needs_a_staff_member_to_run_as(self):
        with self.assertRaisesMessage(CommandError, "No active staff member"):
            self.call(
                "--account",
                "1000",
                "--project",
                str(support.PROJECT),
                "--user",
                "nobody@example.org",
            )
        person("Cleo", client=True)
        with self.assertRaisesMessage(CommandError, "No active staff member"):
            self.call(
                "--account",
                "1000",
                "--project",
                str(support.PROJECT),
                "--user",
                "cleo@example.org",
            )


class SearchTest(ImportCase):
    def found(self, word):
        response = self.client.get("/search/", {"q": word})
        self.assertEqual(response.status_code, 200)
        return {result["item"].title for result in response.context["results"]}

    def test_clients_find_nothing_internal(self):
        self.run_import()
        cleo = User.objects.get(email="cleo@example.org")
        cleo.is_active = True
        cleo.save()
        self.client.force_login(cleo)
        # Internal titles and texts (an answer, a doc, a message)
        for word in [
            "Negotiate",
            "Shopping",
            "salaries",
            "stove",
            "worries",
            "Deep",
            "Raise",
            "Internal in",
            "internal",
        ]:
            with self.subTest(word):
                self.assertEqual(self.found(word), set())
        # What is visible is found, and staff find everything
        self.assertEqual(self.found("giraffe"), {"Buy giraffe food"})
        self.client.force_login(self.ada)
        self.assertEqual(self.found("Negotiate"), {"Negotiate the price"})
        self.assertEqual(self.found("stove"), {"Any worries?"})


class InternalInsideVisibleTest(ImportCase):
    """What was internal inside a container visible to clients goes into an
    internal container of its own (decided 2026-11-21)"""

    def test_a_todo_goes_into_an_internal_list(self):
        self.run_import()
        plan = self.item("Kitchen plan")
        internal = self.item("Kitchen plan (internal)")
        self.assertEqual(internal.kind, Kind.LIST)
        self.assertFalse(internal.is_client_visible)
        self.assertFalse(internal.visible_to_clients)
        todo = self.item("Raise the rate for Cleo")
        self.assertEqual(todo.parent, internal)
        self.assertFalse(todo.is_client_visible)
        self.assertEqual(plan.children.filter(title=todo.title).count(), 0)

    def test_a_doc_goes_into_a_top_level_internal_folder(self):
        self.run_import()
        internal = self.item("Mixed (internal)")
        self.assertEqual(internal.kind, Kind.FOLDER)
        self.assertIsNone(internal.parent)
        self.assertFalse(internal.is_client_visible)
        doc = self.item("Internal in a public folder")
        self.assertEqual(doc.parent, internal)
        self.assertFalse(doc.is_client_visible)

    def test_a_second_run_reuses_them(self):
        self.run_import()
        before = Item.objects.count()
        self.run_import()
        self.assertEqual(Item.objects.count(), before)
        self.assertEqual(
            ImportedObject.objects.filter(
                basecamp_type__in=["Vault::Internal", "Todolist::Internal"]
            ).count(),
            2,
        )
        self.assertEqual(Item.objects.filter(title="Mixed (internal)").count(), 1)

    def test_the_dry_run_lists_them(self):
        report = self.run_import(dry_run=True)
        self.assertEqual(Item.objects.count(), 0)
        self.assertEqual(report.counts["internal folders"]["created"], 1)
        self.assertEqual(report.counts["internal lists"]["created"], 1)
        self.assertEqual(len(report.internal), 2)
        self.assertIn('into folder "Mixed (internal)"', report.as_text())

    def test_clients_see_none_of_it_staff_find_it(self):
        self.run_import()
        cleo = User.objects.get(email="cleo@example.org")
        cleo.is_active = True
        cleo.save()
        titles = [
            "Kitchen plan (internal)",
            "Raise the rate for Cleo",
            "Mixed (internal)",
            "Internal in a public folder",
        ]
        self.client.force_login(cleo)
        for title in titles:
            item = self.item(title)
            self.assertEqual(self.client.get(item.get_absolute_url()).status_code, 404)
            self.assertNotIn(item, Item.objects.visible_to(cleo))
        for word in ["Raise", "Internal in"]:
            response = self.client.get("/search/", {"q": word})
            self.assertEqual(response.context["results"], [])
        self.client.force_login(self.ada)
        for title in titles:
            item = self.item(title)
            self.assertEqual(self.client.get(item.get_absolute_url()).status_code, 200)
        response = self.client.get("/search/", {"q": "Raise"})
        self.assertEqual(
            {r["item"].title for r in response.context["results"]},
            {"Raise the rate for Cleo"},
        )

    def test_a_todo_in_a_group_keeps_its_group(self):
        data = self.client_.data
        grouped = data["/todolists/3014/todos.json"]
        pots = dict(
            grouped[0], id=3016, title="Wash the pots", visible_to_clients=False
        )
        grouped.append(pots)
        self.run_import()
        internal = self.item("Kitchen plan (internal)")
        pots = self.item("Wash the pots")
        self.assertEqual(pots.parent, internal)
        self.assertEqual(pots.todo.group.title, "Week 1")
        self.assertEqual(pots.todo.group.todolist, internal.todolist)
        self.assertEqual(self.item("Peel potatoes").todo.group.title, "Week 1")
        self.assertEqual(internal.todolist.groups.count(), 1)


class StartDatesTest(ImportCase):
    """Basecamp's ``starts_on`` (specs/start-dates.md)"""

    def food(self):
        return self.client_.data["/todolists/301/todos.json"][0]

    def test_a_second_run_changes_it(self):
        self.run_import()
        self.food().update(
            starts_on="2026-06-20",
            due_on="2026-07-01",
            updated_at="2026-03-01T08:00:00.000Z",
        )
        self.run_import()
        todo = self.item("Buy giraffe food").todo
        self.assertEqual(
            (todo.starts_on, todo.due_on), (dt.date(2026, 6, 20), dt.date(2026, 7, 1))
        )

    def test_without_a_due_date_or_after_it_none(self):
        for due_on in [None, "2026-05-01"]:
            with self.subTest(due_on=due_on):
                Item.objects.all().delete()
                ImportedObject.objects.all().delete()
                self.food()["due_on"] = due_on
                self.run_import()
                todo = self.item("Buy giraffe food").todo
                self.assertIsNone(todo.starts_on)


class TooLargeTest(ImportCase):
    """Files over the upload limit aren't imported but listed, with where
    they would have gone and their link in Basecamp, so they can be put
    elsewhere (decided 2026-11-22); the run goes on"""

    def setUp(self):
        super().setUp()
        patcher = mock.patch("biwak.files.models.MAX_SIZE", 10)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch("biwak.files.attachments.MAX_SIZE", 10)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_files_too_large_are_listed_not_imported(self):
        report = self.run_import()
        self.assertFalse(Item.objects.filter(kind=Kind.FILE).exists())
        self.assertFalse(Attachment.objects.exists())
        text = report.as_text()
        self.assertIn("Too large to import (at most 0 MB), put them elsewhere:", text)
        # Where it would have gone and where it is in Basecamp
        self.assertIn("plan.png", text)
        self.assertIn(f"/buckets/{support.PROJECT}/uploads/4003", text)
        # The rest is imported
        self.assertTrue(Item.objects.filter(kind=Kind.TODO).exists())

    def test_a_dry_run_lists_them_too(self):
        report = self.run_import(dry_run=True)
        self.assertIn("plan.png", report.as_text())


class GroupColorTest(TestCase):
    def test_basecamps_colors_in_the_palette(self):
        """specs/import-basecamp.md, decided 2026-11-23 by the user"""
        for basecamp, color in [
            ("red", "ember"),
            ("yellow", "moss"),
            ("aqua", "glacier"),
            ("brown", "bark"),
            ("white", ""),
            (None, ""),
            ("chartreuse", ""),
        ]:
            with self.subTest(basecamp=basecamp):
                self.assertEqual(importer_module.group_color(basecamp), color)
        self.assertEqual(
            sorted(importer_module.BASECAMP_COLORS),
            sorted([
                "red",
                "orange",
                "yellow",
                "green",
                "blue",
                "aqua",
                "purple",
                "gray",
                "pink",
                "brown",
            ]),
        )


def repetition(frequency, days, **extra):
    """A to-do's ``repetition_schedule`` as the API gives it"""
    return {
        "days": days,
        "duration": None,
        "end_date": None,
        "frequency": frequency,
        "hour": 0,
        "minute": 0,
        "month_interval": None,
        "start_date": "2026-12-17",
        "week_instance": None,
        "week_interval": None,
    } | extra


class RepeatTest(ImportCase):
    """Repeating to-dos (specs/import-basecamp.md): the newest to-do of a
    series has Basecamp's schedule, which becomes its rule"""

    def test_the_shapes(self):
        for schedule, rule in [
            (repetition("every_week", [1]), "FREQ=WEEKLY;BYDAY=MO"),
            (repetition("every_day_of_month", [17]), "FREQ=MONTHLY;BYMONTHDAY=17"),
            (
                repetition("every_month", [1], week_instance=1),
                "FREQ=MONTHLY;BYDAY=MO;BYSETPOS=1",
            ),
            (
                repetition("custom_month", [10], month_interval=3),
                "FREQ=MONTHLY;INTERVAL=3;BYMONTHDAY=10",
            ),
            (
                repetition("every_day_of_month", [31]),
                "FREQ=MONTHLY;BYMONTHDAY=28,29,30,31;BYSETPOS=-1",
            ),
        ]:
            with self.subTest(schedule["frequency"]):
                self.assertEqual(importer_module.recurrence_of(schedule), (rule, None))
        self.assertEqual(
            importer_module.recurrence_of(
                repetition("every_week", [1], end_date="2027-06-30")
            ),
            ("FREQ=WEEKLY;BYDAY=MO", dt.date(2027, 6, 30)),
        )

    def todos(self, *, completed=False):
        key = "/todolists/301/todos.json" + ("?completed=true" if completed else "")
        return self.client_.data[key]

    def test_an_open_one_repeats(self):
        self.todos()[0]["repetition_schedule"] = repetition(
            "custom_month", [1], month_interval=3, end_date="2027-12-31"
        )
        self.run_import()
        food = Todo.objects.get(item__title="Buy giraffe food")
        self.assertEqual(food.recurrence, "FREQ=MONTHLY;INTERVAL=3;BYMONTHDAY=1")
        self.assertEqual(food.recurrence_ends_on, dt.date(2027, 12, 31))
        self.assertFalse(Todo.objects.filter(previous=food.item).exists())

    def test_a_done_one_neither_repeats_nor_makes_a_next_one(self):
        # Basecamp moves the schedule on; if a done one had it all the same,
        # completing it while importing would make a next one
        self.todos(completed=True)[0]["repetition_schedule"] = repetition(
            "every_week", [1]
        )
        self.run_import()
        done = Todo.objects.get(item__title="Pick a camp date")
        self.assertTrue(done.is_completed)
        self.assertEqual(done.recurrence, "")
        self.assertFalse(Todo.objects.filter(previous=done.item).exists())

    def test_an_unknown_schedule_is_a_problem(self):
        self.todos()[0]["repetition_schedule"] = repetition("every_full_moon", [1])
        report = self.run_import(dry_run=True)
        self.assertIn(
            "To-do 'Buy giraffe food' (3011) in Camp kitchen doesn't repeat: its"
            " schedule isn't known (unknown frequency 'every_full_moon')",
            report.problems,
        )
        self.run_import()
        self.assertEqual(
            Todo.objects.get(item__title="Buy giraffe food").recurrence, ""
        )

    def test_a_later_run_takes_the_change(self):
        food = self.todos()[0]
        food["repetition_schedule"] = repetition("every_week", [1])
        self.run_import()
        food["repetition_schedule"] = None
        food["updated_at"] = "2026-02-01T08:00:00.000Z"
        self.run_import()
        self.assertEqual(
            Todo.objects.get(item__title="Buy giraffe food").recurrence, ""
        )


class FillScheduleTest(ImportCase):
    """To-dos imported before schedules were, unchanged since: a later run
    adds the schedule the listing gives, where Biwak never had a rule"""

    todos = RepeatTest.todos

    def setUp(self):
        super().setUp()
        self.run_import()
        # Unchanged in Basecamp (the same updated_at), now with a schedule
        self.todos()[0]["repetition_schedule"] = repetition("every_week", [1])

    @property
    def food(self):
        return Todo.objects.get(item__title="Buy giraffe food")

    def test_added_and_listed(self):
        report = self.run_import(dry_run=True)
        line = "Camp kitchen: 'Buy giraffe food' (3011), every Monday"
        self.assertEqual(report.schedules, [line])
        self.assertIn(
            f"Schedules to add to to-dos imported before:\n  {line}", report.as_text()
        )
        self.assertEqual(self.food.recurrence, "")
        report = self.run_import()
        self.assertEqual(report.counts["to-dos"]["unchanged"], 6)
        self.assertEqual(report.schedules, [line])
        self.assertEqual(self.food.recurrence, "FREQ=WEEKLY;BYDAY=MO")
        # Once there, nothing more to add
        self.assertEqual(self.run_import().schedules, [])

    def test_a_rule_removed_in_biwak_stays_removed(self):
        item = self.food.item
        ops.update_todo(item, actor=self.ada, recurrence="FREQ=DAILY")
        ops.update_todo(item, actor=self.ada, recurrence="")
        report = self.run_import()
        self.assertEqual(report.schedules, [])
        self.assertEqual(self.food.recurrence, "")

    def test_a_rule_set_in_biwak_stays(self):
        ops.update_todo(self.food.item, actor=self.ada, recurrence="FREQ=DAILY")
        self.assertEqual(self.run_import().schedules, [])
        self.assertEqual(self.food.recurrence, "FREQ=DAILY")

    def test_not_for_one_completed_in_biwak(self):
        ops.complete(self.food.item, actor=self.ada)
        self.assertEqual(self.run_import().schedules, [])
        self.assertEqual(self.food.recurrence, "")
