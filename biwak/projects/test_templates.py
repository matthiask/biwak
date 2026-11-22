"""Templates (specs/templates.md): the operations, who sees them and what
leaves them out"""

import datetime as dt

from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.test import TestCase

from biwak.activity import feed, notify
from biwak.activity.models import Action, Event, Mention, Notification, Subscription
from biwak.checkins import operations as checkin_ops
from biwak.checkins.support import MONDAY_9
from biwak.files import attachments, operations as file_ops
from biwak.files.models import Attachment
from biwak.items import due, operations as ops
from biwak.items.models import Item, Kind, MessageCategory, Status
from biwak.palette import queries as palette
from biwak.projects import operations as project_ops
from biwak.projects.models import Membership, Project
from biwak.projects.overview import overview
from biwak.public_links import operations as public_link_ops
from biwak.search import queries as search
from biwak.test_utils import external, person, project


class Fixture:
    """A template "Web project" with a list (a group, open and completed
    to-dos), a welcome message visible to clients, a pinned message and
    folders with a doc and a file"""

    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.pia = external("Pia")
        self.template = project_ops.create_template(
            name="Web project", description="For websites", actor=self.ada
        )
        self.list = ops.create_list(
            project=self.template,
            title="Onboarding",
            creator=self.ada,
            description="The first weeks",
            visible=True,
        )
        self.later = ops.create_group(todolist=self.list.todolist, title="Later")
        self.kickoff = ops.create_todo(
            todolist=self.list,
            title="Kick-off",
            creator=self.ada,
            notes="- [ ] agenda\n- [ ] room",
            due_on=dt.date(2026, 12, 1),
            assignees=[self.bob],
        )
        ops.create_todo(
            todolist=self.list, title="Review", creator=self.ada, group=self.later
        )
        done = ops.create_todo(todolist=self.list, title="Done", creator=self.ada)
        ops.complete(done, actor=self.ada)
        ops.add_comment(self.kickoff, author=self.bob, content="Which room?")
        self.category = MessageCategory.objects.create(name="Welcome", emoji="👋")
        self.welcome = ops.create_message(
            project=self.template,
            title="Welcome",
            creator=self.ada,
            content="Hello!",
            visible=True,
            category=self.category,
        )
        self.questions = ops.create_message(
            project=self.template, title="Questions for you", creator=self.ada
        )
        file_ops.pin_message(self.questions, actor=self.ada)
        self.design = ops.create_folder(
            project=self.template, title="Design", creator=self.ada, color="blue"
        )
        self.drafts = ops.create_folder(
            project=self.template,
            title="Drafts",
            creator=self.ada,
            parent=self.design,
        )
        self.brief = ops.create_doc(
            project=self.template,
            title="Project brief",
            creator=self.ada,
            parent=self.drafts,
            content="Goals",
        )
        self.logo = ops.create_upload(
            project=self.template,
            file=ContentFile(b"logo", name="logo.svg"),
            creator=self.ada,
            parent=self.design,
        )


class TemplateTest(Fixture, TestCase):
    def test_created(self):
        self.assertTrue(self.template.is_template)
        self.assertTrue(self.template.is_all_access)
        self.assertFalse(self.template.memberships.exists())
        with self.assertRaises(PermissionError):
            project_ops.create_template(name="X", actor=self.pia)
        with self.assertRaises(PermissionError):
            project_ops.create_template(name="X", actor=self.cleo)

    def test_who_sees_it(self):
        """Own staff without being members; clients and externals never,
        even as members"""
        Membership.objects.create(project=self.template, user=self.cleo)
        Membership.objects.create(project=self.template, user=self.pia)
        self.assertTrue(self.template.is_accessible_to(self.bob))
        self.assertFalse(self.template.is_accessible_to(self.cleo))
        self.assertFalse(self.template.is_accessible_to(self.pia))
        self.assertFalse(Item.objects.visible_to(self.cleo).exists())
        self.assertFalse(Item.objects.visible_to(self.pia).exists())

    def test_no_members(self):
        with self.assertRaises(ValueError):
            project_ops.add_member(self.template, self.bob, actor=self.ada)

    def test_no_public_links(self):
        """Nothing in a template is shared publicly (decided 2026-11-22)"""
        self.assertFalse(self.kickoff.is_shareable)
        self.assertFalse(public_link_ops.can_share(self.ada, self.welcome))
        with self.assertRaises(PermissionDenied):
            public_link_ops.create_public_link(self.welcome, days=7, actor=self.ada)

    def test_stays_all_access(self):
        with self.assertRaises(ValueError):
            project_ops.update_project(
                self.template, is_all_access=False, actor=self.ada
            )

    def test_left_out(self):
        """Out of the lists across projects, like archived projects"""
        self.assertNotIn(self.template, Project.objects.active())
        self.assertNotIn(self.template, overview(self.ada))
        self.assertFalse(feed.feed_events(self.ada).exists())
        self.assertTrue(feed.feed_events(self.ada, project=self.template).exists())
        self.assertFalse(due.todos(self.bob, assignee="me").exists())
        # Search never finds templates, not even searching in one
        # (decided 2026-11-22)
        self.assertFalse(search.search(self.ada, "Kick-off").exists())
        self.assertFalse(
            search.search(self.ada, "Kick-off", project=self.template).exists()
        )
        # Nor does the palette, neither the template nor what's in it
        # (decided 2026-11-22: they're used from the templates page and
        # "New project/list from a template")
        self.assertEqual(palette.jumps(self.ada, "Web project"), [])
        self.assertEqual(palette.jumps(self.ada, "Kick-off"), [])

    def test_tells_nobody(self):
        """Nothing inside a template tells anybody: assigning, commenting,
        mentioning, posting"""
        self.assertFalse(Notification.objects.exists())
        ops.create_message(
            project=self.template,
            title="Hi",
            creator=self.ada,
            content=f"[@Bob](person:{self.bob.pk}) look",
            also=[self.bob],
        )
        ops.add_comment(
            self.kickoff, author=self.ada, content=f"[@Bob](person:{self.bob.pk}) here"
        )
        for event in Event.objects.all():
            self.assertEqual(notify.notify(event.pk), [])
        self.assertFalse(Notification.objects.exists())
        self.assertFalse(Mention.objects.exists())

    def test_move_refused(self):
        other = project("Website", members=[self.ada])
        with self.assertRaises(ValueError):
            ops.move_to_project(self.welcome, project=other, actor=self.ada)
        message = ops.create_message(project=other, title="Hi", creator=self.ada)
        with self.assertRaises(ValueError):
            ops.move_to_project(message, project=self.template, actor=self.ada)


class FromTemplateTest(Fixture, TestCase):
    def create(self, **kwargs):
        kwargs.setdefault("name", "Website")
        return project_ops.create_from_template(self.template, actor=self.ada, **kwargs)

    def test_everything_copied(self):
        website = self.create(description="A new site")
        self.assertFalse(website.is_template)
        self.assertEqual(website.description, "A new site")
        items = Item.objects.filter(project=website)
        [todolist] = items.filter(kind=Kind.LIST)
        self.assertEqual(todolist.title, "Onboarding")
        self.assertEqual(todolist.todolist.description, "The first weeks")
        self.assertEqual([g.title for g in todolist.todolist.groups.all()], ["Later"])
        todos = list(ops.open_todos(todolist))
        self.assertEqual([t.title for t in todos], ["Kick-off", "Review"])
        self.assertEqual(todos[0].todo.notes, "- [ ] agenda\n- [ ] room")
        self.assertEqual(todos[0].todo.due_on, dt.date(2026, 12, 1))
        self.assertFalse(items.filter(title="Done").exists())
        welcome = items.get(kind=Kind.MESSAGE, title="Welcome")
        self.assertEqual(welcome.message.content, "Hello!")
        self.assertEqual(welcome.message.category, self.category)
        self.assertIsNone(welcome.message.pinned_at)
        questions = items.get(kind=Kind.MESSAGE, title="Questions for you")
        self.assertIsNotNone(questions.message.pinned_at)
        design = items.get(kind=Kind.FOLDER, title="Design")
        self.assertEqual(design.folder.color, "blue")
        drafts = items.get(kind=Kind.FOLDER, parent=design)
        brief = items.get(kind=Kind.DOC, parent=drafts)
        self.assertEqual(brief.title, "Project brief")
        self.assertIn("Goals", brief.doc.content)
        self.assertEqual(brief.doc.versions.count(), 1)
        logo = items.get(kind=Kind.FILE, parent=design)
        version = logo.upload.versions.get()
        self.assertNotEqual(
            version.file.name, self.logo.upload.versions.get().file.name
        )
        with version.file.open("rb") as file:
            self.assertEqual(file.read(), b"logo")
        # Comments aren't
        self.assertFalse(todos[0].comments.exists())

    def test_client_visibility_copied(self):
        website = self.create()
        items = Item.objects.filter(project=website)
        self.assertTrue(items.get(kind=Kind.LIST).is_client_visible)
        self.assertTrue(items.get(title="Kick-off").is_client_visible)
        self.assertTrue(items.get(title="Welcome").is_client_visible)
        self.assertFalse(items.get(title="Questions for you").is_client_visible)
        self.assertFalse(items.get(kind=Kind.FOLDER, title="Design").is_client_visible)

    def test_assignees(self):
        """Kept: added as members when they wouldn't see the new project,
        as "Copy…" does (decided 2026-11-22)"""
        website = self.create(is_all_access=True)
        kickoff = Item.objects.get(project=website, title="Kick-off")
        self.assertEqual(list(kickoff.todo.assignees.all()), [self.bob])
        self.assertTrue(
            Subscription.objects.filter(user=self.bob, item=kickoff).exists()
        )
        self.assertFalse(website.memberships.filter(user=self.bob).exists())
        shop = self.create(name="Shop", is_all_access=False)
        kickoff = Item.objects.get(project=shop, title="Kick-off")
        self.assertEqual(list(kickoff.todo.assignees.all()), [self.bob])
        self.assertTrue(shop.memberships.filter(user=self.bob).exists())
        self.assertTrue(
            Event.objects.filter(
                project=shop, action=Action.ADDED, data__user=self.bob.pk
            ).exists()
        )
        with_bob = self.create(name="Bob's", is_all_access=False, members=[self.bob])
        kickoff = Item.objects.get(project=with_bob, title="Kick-off")
        self.assertEqual(list(kickoff.todo.assignees.all()), [self.bob])

    def test_one_event_nobody_told(self):
        website = self.create(members=[self.bob])
        [event] = Event.objects.filter(project=website).exclude(action=Action.ADDED)
        self.assertEqual(event.action, Action.CREATED)
        self.assertIsNone(event.item)
        self.assertEqual(event.data["template_id"], self.template.pk)
        self.assertEqual(event.data["template"], "Web project")
        self.assertFalse(Notification.objects.exists())

    def test_creator_subscribed(self):
        website = self.create()
        subscribed = set(
            Subscription.objects.filter(
                user=self.ada, item__project=website
            ).values_list("item__kind", flat=True)
        )
        self.assertEqual(subscribed, {Kind.LIST, Kind.MESSAGE, Kind.DOC, Kind.FILE})

    def test_left_out(self):
        """Archived lists, trashed items and drafts"""
        archived = ops.create_list(project=self.template, title="Old", creator=self.ada)
        ops.archive(archived, actor=self.ada)
        trashed = ops.create_message(
            project=self.template, title="Gone", creator=self.ada
        )
        ops.trash(trashed, actor=self.ada)
        ops.create_draft(project=self.template, creator=self.ada)
        website = self.create()
        titles = set(
            Item.objects.filter(project=website, parent=None).values_list(
                "title", flat=True
            )
        )
        self.assertEqual(
            titles,
            {"Onboarding", "Welcome", "Questions for you", "Design"},
        )
        self.assertFalse(
            Item.objects.filter(project=website, status=Status.TRASHED).exists()
        )

    def test_attachments_copied(self):
        attachment = attachments.upload(
            project=self.template,
            file=ContentFile(b"plan", name="plan.txt"),
            uploaded_by=self.ada,
        )
        message = ops.create_message(
            project=self.template,
            title="Plan",
            creator=self.ada,
            content=f"See [plan.txt](attachment:{attachment.key})",
        )
        website = self.create()
        copy = Item.objects.get(project=website, title="Plan")
        new = Attachment.objects.get(item=copy)
        self.assertNotEqual(new.key, attachment.key)
        self.assertIn(new.key, copy.message.content)
        self.assertEqual(Attachment.objects.get(item=message).key, attachment.key)

    def test_template_unchanged_later(self):
        website = self.create()
        ops.create_list(project=self.template, title="New", creator=self.ada)
        self.assertFalse(Item.objects.filter(project=website, title="New").exists())

    def test_only_templates(self):
        website = self.create()
        with self.assertRaises(ValueError):
            project_ops.create_from_template(website, actor=self.ada, name="Again")

    def test_own_staff_only(self):
        with self.assertRaises(PermissionError):
            project_ops.create_from_template(
                self.template, actor=self.pia, name="Theirs"
            )

    def test_feed_names_the_template(self):
        website = self.create(members=[self.pia])
        events = list(Event.objects.filter(project=website, action=Action.CREATED))
        feed.add_projects(events, self.ada)
        self.assertEqual(events[0].template_name, "Web project")
        feed.add_projects(events, self.pia)
        self.assertEqual(events[0].template_name, "")


class QuestionsFromTemplateTest(Fixture, TestCase):
    """Check-in questions are copied with their schedules and the people
    asked (decided 2026-11-22)"""

    def setUp(self):
        super().setUp()
        self.weekly = checkin_ops.create_question(
            project=self.template,
            title="What are you working on?",
            creator=self.ada,
            people=[self.bob],
            **MONDAY_9,
        )

    def create(self, **kwargs):
        kwargs.setdefault("name", "Website")
        return project_ops.create_from_template(self.template, actor=self.ada, **kwargs)

    def test_copied(self):
        shop = self.create(is_all_access=False)
        copy = Item.objects.get(project=shop, kind=Kind.QUESTION)
        self.assertEqual(copy.title, "What are you working on?")
        question = copy.question
        self.assertEqual(question.rule, MONDAY_9["rule"])
        self.assertEqual(question.starts_on, MONDAY_9["starts_on"])
        self.assertEqual(question.time_of_day, MONDAY_9["time_of_day"])
        self.assertIsNotNone(question.next_at)
        self.assertTrue(question.is_askable)
        # Bob, asked, wouldn't see the limited project: added as member
        self.assertEqual(list(question.people.all()), [self.bob])
        self.assertTrue(shop.memberships.filter(user=self.bob).exists())
        subscribed = set(
            Subscription.objects.filter(item=copy).values_list("user", flat=True)
        )
        self.assertEqual(subscribed, {self.ada.pk, self.bob.pk})
        # Silently: the project's one event, besides adding Bob
        self.assertFalse(Event.objects.filter(item=copy).exists())
        # The template's own question stays, still not asked
        self.assertFalse(self.weekly.question.is_askable)

    def test_paused_and_trashed(self):
        checkin_ops.pause(self.weekly, actor=self.ada)
        gone = checkin_ops.create_question(
            project=self.template, title="Gone?", creator=self.ada, **MONDAY_9
        )
        ops.trash(gone, actor=self.ada)
        website = self.create()
        question = Item.objects.get(project=website, kind=Kind.QUESTION).question
        self.assertTrue(question.is_paused)
        self.assertIsNone(question.next_at)


class ListFromTemplateTest(Fixture, TestCase):
    def test_copy_into_a_project(self):
        """The copy of lists-across-projects.md, the other way round"""
        website = project("Website", members=[self.ada])
        copy = ops.copy_list(
            self.list,
            project=website,
            title="Onboarding Dan",
            actor=self.ada,
            dates=ops.Dates.REMOVE,
        )
        self.assertEqual(copy.title, "Onboarding Dan")
        self.assertEqual(
            [t.title for t in ops.open_todos(copy)], ["Kick-off", "Review"]
        )
        self.assertIsNone(ops.open_todos(copy).first().todo.due_on)
        # Told like any copy
        self.assertTrue(Event.objects.filter(item=copy, action=Action.CREATED).exists())


class CopyIntoTemplateTest(Fixture, TestCase):
    def test_nobody_added(self):
        """A running list copied into a template: its client assignees are
        left out, nobody becomes a member"""
        website = project("Website", members=[self.ada, self.cleo])
        launch = ops.create_list(
            project=website, title="Launch", creator=self.ada, visible=True
        )
        ops.create_todo(
            todolist=launch, title="Tent", creator=self.ada, assignees=[self.cleo]
        )
        added, dropped = ops.copy_people(launch, self.template, visible=True)
        self.assertEqual(list(added), [])
        self.assertEqual(list(dropped), [self.cleo])
        copy = ops.copy_list(
            launch, project=self.template, title="Launch", actor=self.ada
        )
        self.assertFalse(self.template.memberships.exists())
        self.assertFalse(ops.open_todos(copy).get().todo.assignees.exists())
