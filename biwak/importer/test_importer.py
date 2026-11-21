"""The Basecamp importer against recorded shapes with made-up data
(specs/import-basecamp.md)"""

import datetime as dt
import io
from unittest import mock

from django.core import mail
from django.core.management import CommandError, call_command
from django.test import TestCase

from biwak.accounts.models import User
from biwak.activity.models import Event, Notification, Subscription
from biwak.bookmarks.models import Bookmark
from biwak.checkins.models import Answer, Occurrence, Question
from biwak.files.models import Attachment
from biwak.importer import support
from biwak.importer.importer import Importer
from biwak.importer.models import ImportedObject
from biwak.items import visibility
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
from biwak.projects.models import Membership, Project
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
                    "todolist__item__title", "title"
                )
            ),
            [
                ("Kitchen plan", "Week 1"),
                ("Planning board", "Triage"),
                ("Planning board", "Cooking"),
                ("Planning board", "Done"),
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
        self.assertEqual(
            self.names(food.todo.assignees.all()), {"Bob Example", "Cleo Example"}
        )
        self.assertIn("[@Bob Example](person:", food.todo.notes)
        self.assertIn("[the announcement](/messages/", food.todo.notes)
        done = self.item("Pick a camp date")
        self.assertEqual(done.todo.completed_at, at("2026-01-08T16:30:00+00:00"))
        self.assertEqual(done.todo.completed_by, self.ada)
        self.assertEqual(self.item("Whale watching").status, Status.ARCHIVED)

        # Messages
        announcement = self.item("We have a camp")
        self.assertEqual(announcement.message.category.name, "Announcement")
        self.assertIn(
            f"[@Cleo Example](person:{User.objects.get(email='cleo@example.org').pk})",
            announcement.message.content,
        )
        self.assertIn(f"](/todos/{food.pk}/)", announcement.message.content)
        self.assertEqual(MessageCategory.objects.count(), 1)

        # Folders, docs, files
        self.assertEqual(
            kinds(Kind.FOLDER),
            {"Public", "Private", "Mixed", "Mixed (internal)", "Deeper"},
        )
        self.assertEqual(self.item("Deeper").parent.title, "Private")
        self.assertEqual(self.item("Public doc").parent.title, "Public")
        self.assertEqual(self.item("Shopping list").parent, None)
        self.assertEqual(self.item("Shopping list").doc.content, "Text")
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
        self.assertEqual(self.names(q.people.all()), {"Ada Example"} | set())

        # Comments, attachments
        self.assertEqual(Comment.objects.count(), 4)
        self.assertEqual(Comment.objects.filter(item=food).count(), 2)
        negotiate = self.item("Negotiate the price")
        attachment = Attachment.objects.get()
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

    def test_profile_images_are_not_imported(self):
        """Basecamp's generated initials images can't be told apart from
        uploaded ones by their URL (specs/people.md, decided 2026-11-21):
        none are imported, our own mark is better"""
        self.run_import()
        self.assertEqual(User.objects.exclude(image="").count(), 0)
        self.assertFalse([url for url in self.client_.downloads if "avatar" in url])

    def test_people(self):
        self.run_import()
        self.assertEqual(User.objects.filter(email="ada@example.org").count(), 1)
        bob = User.objects.get(email="bob@example.org")
        self.assertFalse(bob.is_active)
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
    "Shopping list",
    "plan.png",
    "Private",
    "Deeper",
    "Deep doc",
    "salaries.png",
    "Any worries?",
}


class VisibilityTest(ImportCase):
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
        with self.captureOnCommitCallbacks(execute=True):
            self.run_import()
        self.assertEqual(Notification.objects.count(), 0)
        self.assertEqual(Comment.objects.count(), 5)

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
        # Files aren't downloaded again
        self.assertEqual(len(self.client_.downloads), downloads)
        self.assertEqual(report.counts["to-dos"]["created"], 0)
        self.assertEqual(report.counts["to-dos"]["updated"], 6)
        self.assertEqual(visibility.check(), [])

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
        done = data["/todolists/301/todos.json?completed=true"][0]
        data["/todolists/301/todos.json"].append(done | {"completed": False})
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
        data["/vaults/400/documents.json"][1]["content"] = "<div>New rules</div>"
        data["/message_boards/200/messages.json"][1]["subject"] = "We have a camp!"
        data[f"/projects/{support.PROJECT}.json"]["name"] = "Camp kitchen 2"
        self.run_import()
        food.refresh_from_db()
        self.assertEqual(food.title, "Buy giraffe and zebra food")
        self.assertEqual(food.todo.notes, "New notes")
        self.assertEqual(food.todo.due_on, dt.date(2026, 7, 1))
        self.assertEqual(self.names(food.todo.assignees.all()), {"Bob Example"})
        self.assertEqual(Item.objects.filter(kind=Kind.TODO).count(), 8)
        self.assertEqual(Comment.objects.filter(item=food).count(), 3)
        self.assertFalse(self.item("Pick a camp date").todo.is_completed)
        self.assertEqual(self.item("Camp rules").doc.content, "New rules")
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
        self.run_import()
        self.assertTrue(Todo.objects.get(item=food).is_completed)

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
        self.assertEqual(Comment.objects.count(), 4)

    def test_a_deleted_object_is_imported_again(self):
        self.run_import()
        self.item("Peel potatoes").delete()
        self.run_import()
        self.assertEqual(Item.objects.filter(title="Peel potatoes").count(), 1)


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
                "Bob Example <bob@example.org> (staff, Example Team)",
                "Cleo Example <cleo@example.org> (client, Example Client Ltd)",
            ],
        )
        self.assertEqual(len(report.internal), 2)
        text = report.as_text()
        self.assertIn("Dry run", text)
        self.assertIn("Raise the rate for Cleo", text)
        self.assertIn("to-dos: 6 new", text)

    def test_after_a_run_it_counts_existing_ones(self):
        self.run_import()
        report = self.run_import(dry_run=True)
        self.assertEqual(report.counts["to-dos"]["updated"], 6)
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
        self.assertFalse(bob.is_partner)
        cleo = User.objects.get(email="cleo@example.org")
        self.assertEqual(cleo.organization, existing)
        finn = User.objects.get(email="finn@example.org")
        self.assertEqual(finn.organization.name, "Example Freelance")
        self.assertTrue(finn.is_partner)
        self.assertIn(
            "Finn Example <finn@example.org> (partner, Example  Freelance)",
            report.people,
        )

    def test_employees_in_the_own_organization_which_always_exists(self):
        self.run_import()
        bob = User.objects.get(email="bob@example.org")
        self.assertTrue(bob.organization.is_own)
        self.assertFalse(bob.is_partner)

    def test_collaborators_without_a_company_are_individual_partners(self):
        people = self.client_.data[f"/projects/{support.PROJECT}/people.json"]
        people.append(
            support.person(6, "Gus Example", "gus@example.org") | {"employee": False}
        )
        self.run_import()
        gus = User.objects.get(email="gus@example.org")
        self.assertIsNone(gus.organization)
        self.assertTrue(gus.is_partner)

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
        call_command("send_mails")
        self.assertEqual(Occurrence.objects.count(), occurrences)
        self.assertEqual(mail.outbox, [])


class CommandTest(ImportCase):
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
            call_command("import_basecamp", *args, stdout=out, **kwargs)
        return out.getvalue(), make

    def test_runs_as_the_person_of_the_token(self):
        # The profile says Ada
        text, make = self.call("--account", "1000", "--project", str(support.PROJECT))
        make.assert_called_once_with("1000", "secret")
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

    def test_needs_a_token(self):
        with (
            mock.patch.dict("os.environ", {}, clear=False),
            self.assertRaisesMessage(CommandError, "BASECAMP_TOKEN"),
        ):
            import os

            os.environ.pop("BASECAMP_TOKEN", None)
            call_command("import_basecamp", "--account", "1", "--project", "2")

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
