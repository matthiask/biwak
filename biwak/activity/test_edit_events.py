import datetime as dt

from django.test import TestCase
from django.urls import reverse

from biwak.activity import feed
from biwak.activity.mails import describe
from biwak.activity.models import Action, Event, Notification
from biwak.items import operations as ops
from biwak.test_utils import person, project


class EditEventsTest(TestCase):
    """Edits say what changed, unassigning is an event (specs/timeline.md)"""

    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.project = project(members=[self.ada, self.bob])
        self.list = ops.create_list(
            project=self.project, title="Plans", creator=self.ada, visible=True
        )
        self.todo = ops.create_todo(
            todolist=self.list, title="Order the tent", creator=self.ada
        )
        Event.objects.all().delete()

    def edited(self):
        return Event.objects.get(action=Action.EDITED)

    def test_edit_records_fields_title_and_due_date(self):
        ops.update_todo(
            self.todo,
            actor=self.ada,
            title="Order two tents",
            due_on=dt.date(2026, 12, 1),
            notes="Blue",
        )
        data = self.edited().data
        self.assertEqual(data["fields"], ["title", "notes", "due_on"])
        self.assertEqual(data["title"], "Order two tents")
        self.assertEqual(data["due_on"], "2026-12-01")

    def test_clearing_the_due_date(self):
        ops.update_todo(self.todo, actor=self.ada, due_on=dt.date(2026, 12, 1))
        ops.update_todo(self.todo, actor=self.ada, due_on=None)
        data = self.edited().data
        self.assertEqual(data["fields"], ["due_on"])
        self.assertIsNone(data["due_on"])

    def test_recurrence_fields_are_one(self):
        ops.update_todo(
            self.todo,
            actor=self.ada,
            recurrence="RRULE:FREQ=WEEKLY",
            recurrence_ends_on=None,
            recurrence_count=None,
        )
        self.assertEqual(self.edited().data["fields"], ["recurrence"])

    def test_merged_edits_list_everything(self):
        ops.update_todo(self.todo, actor=self.ada, notes="Blue")
        ops.update_todo(self.todo, actor=self.ada, due_on=dt.date(2026, 12, 1))
        ops.update_todo(self.todo, actor=self.ada, notes="Green")
        data = self.edited().data
        self.assertEqual(data["fields"], ["notes", "due_on"])
        self.assertEqual(data["due_on"], "2026-12-01")

    def test_unassigning_records_an_event_and_tells_nobody(self):
        ops.assign(self.todo, [self.bob], actor=self.ada)
        Event.objects.all().delete()
        Notification.objects.all().delete()
        ops.unassign(self.todo, [self.bob], actor=self.ada)
        (event,) = Event.objects.all()
        self.assertEqual(event.action, Action.UNASSIGNED)
        self.assertEqual(event.data["assignees"], [self.bob.pk])
        self.assertFalse(Notification.objects.exists())
        self.assertFalse(self.todo.todo.assignees.exists())

    def test_unassigning_nobody_assigned_records_nothing(self):
        ops.unassign(self.todo, [self.bob], actor=self.ada)
        self.assertFalse(Event.objects.exists())

    def test_the_form_unassigns_too(self):
        ops.assign(self.todo, [self.bob], actor=self.ada)
        Event.objects.all().delete()
        ops.update_todo(self.todo, actor=self.ada, assignees=[])
        self.assertEqual(
            list(Event.objects.values_list("action", flat=True)), [Action.UNASSIGNED]
        )

    def test_the_feed_says_who_was_removed(self):
        ops.assign(self.todo, [self.bob], actor=self.ada)
        Event.objects.all().delete()
        ops.unassign(self.todo, [self.bob], actor=self.ada)
        self.client.force_login(self.ada)
        response = self.client.get(reverse("feed"))
        text = " ".join(response.content.decode().split())
        self.assertIn("removed", text)
        self.assertIn("Bob", text)
        self.assertIn("from", text)
        # The filter offers it
        self.assertContains(response, 'value="unassigned"')

    def test_the_mail_line_and_the_api(self):
        ops.assign(self.todo, [self.bob], actor=self.ada)
        Event.objects.all().delete()
        ops.unassign(self.todo, [self.bob], actor=self.ada)
        event = Event.objects.get()
        self.assertEqual(describe(event, self.ada), "Ada Example removed Bob Example.")
        self.assertEqual(describe(event, self.bob), "Ada Example removed you.")
        self.assertEqual(feed.feed_events(self.ada).get().pk, event.pk)


class ItemEditEventsTest(TestCase):
    """Edits of messages, docs and files say what changed, moves between
    folders where from and to (specs/timeline.md)"""

    def setUp(self):
        self.ada = person("Ada")
        self.project = project(members=[self.ada])

    def data(self, action=Action.EDITED):
        return Event.objects.get(action=action).data

    def test_messages(self):
        from biwak.files.operations import update_message

        item = ops.create_message(
            project=self.project, title="News", content="Hello", creator=self.ada
        )
        update_message(item, actor=self.ada, title="Big news", content="Hi")
        self.assertEqual(self.data()["fields"], ["title", "content"])

    def test_docs(self):
        from biwak.files.operations import save_version, update_doc

        item = ops.create_doc(
            project=self.project, title="Brief", content="Tent", creator=self.ada
        )
        update_doc(item, actor=self.ada, content="# Brief\n\nTents")
        self.assertEqual(self.data()["fields"], ["content"])
        Event.objects.filter(action=Action.EDITED).delete()
        update_doc(item, actor=self.ada, content="# Plan\n\nTents")
        self.assertEqual(self.data()["fields"], ["title", "content"])
        Event.objects.filter(action=Action.EDITED).delete()
        # "Save as a version" changes nothing
        save_version(item, actor=self.ada)
        self.assertEqual(self.data()["fields"], [])

    def test_files(self):
        from django.core.files.base import ContentFile

        from biwak.files.operations import replace_upload, update_upload

        item = ops.create_upload(
            project=self.project,
            file=ContentFile(b"x", name="plan.txt"),
            creator=self.ada,
        )
        replace_upload(item, ContentFile(b"y", name="plan.txt"), actor=self.ada)
        update_upload(item, actor=self.ada, description="The plan")
        self.assertEqual(self.data()["fields"], ["file", "description"])

    def test_moves_between_folders(self):
        folder = ops.create_folder(
            project=self.project, title="Minutes", creator=self.ada
        )
        item = ops.create_doc(project=self.project, title="Brief", creator=self.ada)
        ops.move_item(item, parent=folder, actor=self.ada)
        data = self.data(Action.MOVED)
        self.assertEqual((data["folder_id"], data["folder_was"]), (folder.pk, None))
        Event.objects.filter(action=Action.MOVED).delete()
        ops.move_item(item, parent=None, actor=self.ada)
        data = self.data(Action.MOVED)
        self.assertEqual((data["folder_id"], data["folder_was"]), (None, folder.pk))
