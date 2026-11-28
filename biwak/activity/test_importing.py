import datetime as dt

from django.test import TestCase

from biwak.activity.models import Action, Event, Notification
from biwak.activity.operations import importing, subscribe
from biwak.items import operations as ops
from biwak.test_utils import person, project


class ImportingTest(TestCase):
    """``importing()``: events tell nobody and carry the time given"""

    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.project = project(members=[self.ada, self.bob])
        self.list = ops.create_list(
            project=self.project, title="Plan", creator=self.ada
        )
        subscribe(self.bob, self.list)

    def comment(self):
        with self.captureOnCommitCallbacks(execute=True):
            ops.create_todo(todolist=self.list, title="Cook", creator=self.ada)

    def test_events_notify(self):
        self.comment()
        self.assertEqual(Notification.objects.filter(user=self.bob).count(), 1)

    def test_nobody_is_told_inside(self):
        with importing():
            self.comment()
        self.assertEqual(Notification.objects.count(), 0)
        self.assertTrue(Event.objects.filter(action=Action.CREATED).exists())

    def test_the_time_is_the_one_given(self):
        then = dt.datetime(2020, 3, 4, 5, 6, tzinfo=dt.UTC)
        with importing(at=then):
            ops.create_todo(todolist=self.list, title="Cook", creator=self.ada)
        event = Event.objects.filter(item__title="Cook").get()
        self.assertEqual(event.created_at, then)
        self.project.refresh_from_db()
        # The list was made now: the old event doesn't make the project older
        self.assertGreater(self.project.last_activity_at, then)

    def test_afterwards_everything_is_as_before(self):
        with importing(at=dt.datetime(2020, 1, 1, tzinfo=dt.UTC)):
            pass
        self.comment()
        self.assertEqual(Notification.objects.count(), 1)
        self.assertGreater(Event.objects.latest("created_at").created_at.year, 2020)

    def test_an_edit_dated_in_the_past_leaves_later_edits_alone(self):
        """Edits merge into the same person's edit of the 10 minutes
        before, never into a later one (found 2026-11-28, verification
        round 2: an import's edit at Basecamp's time took the person's
        edit of today back with it)"""
        todo = ops.create_todo(todolist=self.list, title="Tent", creator=self.ada)
        ops.update_todo(todo, actor=self.ada, title="Order the tent")
        edit = Event.objects.get(item=todo, action=Action.EDITED)
        when = edit.created_at
        with importing(at=when - dt.timedelta(days=200)):
            ops.update_todo(todo, actor=self.ada, notes="From long ago")
        edit.refresh_from_db()
        self.assertEqual(edit.created_at, when)
        self.assertEqual(
            Event.objects.filter(item=todo, action=Action.EDITED).count(), 2
        )
