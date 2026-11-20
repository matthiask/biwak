import datetime as dt

from django.test import TestCase
from django.utils import timezone

from biwak.accounts.models import NotificationLevel
from biwak.activity import mentions
from biwak.activity.models import Action, Event, LevelOverride, Notification
from biwak.activity.notify import effective_level, notify, notify_people
from biwak.activity.operations import record, subscribe, unsubscribe
from biwak.items import operations as ops
from biwak.projects import operations as project_ops
from biwak.test_utils import person, project


class NotifyTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.bob, self.cleo])
        self.internal = ops.create_list(
            project=self.project, title="Internal", creator=self.ada
        )
        self.shared = ops.create_list(
            project=self.project, title="Shared", creator=self.ada, visible=True
        )
        self.todo = ops.create_todo(
            todolist=self.shared, title="Visible", creator=self.ada
        )
        self.secret = ops.create_todo(
            todolist=self.internal, title="Secret", creator=self.ada
        )

    def told(self, run):
        """Runs ``run`` and the notifications after the commit; who was told"""
        before = set(Notification.objects.values_list("pk", flat=True))
        with self.captureOnCommitCallbacks(execute=True):
            run()
        return {
            n.user
            for n in Notification.objects.exclude(pk__in=before).select_related("user")
        }

    def test_comment(self):
        subscribe(self.bob, self.todo)
        subscribe(self.cleo, self.todo)
        told = self.told(
            lambda: ops.add_comment(self.todo, author=self.ada, content="Hi")
        )
        self.assertEqual(told, {self.bob, self.cleo})
        # Never the actor
        told = self.told(
            lambda: ops.add_comment(self.todo, author=self.bob, content="Hi")
        )
        self.assertEqual(told, {self.ada, self.cleo})

    def test_client_not_told_about_internal_items(self):
        subscribe(self.cleo, self.secret)  # e.g. before it was hidden
        subscribe(self.bob, self.secret)
        told = self.told(
            lambda: ops.add_comment(self.secret, author=self.ada, content="Hi")
        )
        self.assertEqual(told, {self.bob})

    def test_lost_access(self):
        """Visibility is checked when notifying, not when subscribing"""
        subscribe(self.cleo, self.todo)
        subscribe(self.bob, self.todo)
        ops.set_visibility(self.shared, visible=False, actor=self.ada)
        told = self.told(
            lambda: ops.add_comment(self.todo, author=self.ada, content="Hi")
        )
        self.assertEqual(told, {self.bob})
        limited = project("Salaries", members=[self.ada, self.bob], all_access=False)
        salaries = ops.create_list(project=limited, title="2027", creator=self.ada)
        subscribe(self.bob, salaries)
        project_ops.remove_member(limited, self.bob, actor=self.ada)
        subscribe(self.bob, salaries)  # even if the subscription stayed
        self.assertEqual(
            self.told(lambda: ops.update_list(salaries, actor=self.ada, title="X")),
            set(),
        )

    def test_inactive_not_told(self):
        subscribe(self.bob, self.todo)
        self.bob.is_active = False
        self.bob.save()
        self.assertEqual(
            self.told(lambda: ops.add_comment(self.todo, author=self.ada, content="x")),
            set(),
        )

    def test_created_tells_container_subscribers(self):
        subscribe(self.bob, self.shared)
        told = self.told(
            lambda: ops.create_todo(todolist=self.shared, title="New", creator=self.ada)
        )
        self.assertEqual(told, {self.bob})

    def test_assigned_and_completed(self):
        told = self.told(lambda: ops.assign(self.todo, [self.bob], actor=self.ada))
        self.assertEqual(told, {self.bob})
        told = self.told(lambda: ops.complete(self.todo, actor=self.bob))
        self.assertEqual(told, {self.ada})
        told = self.told(lambda: ops.reopen(self.todo, actor=self.ada))
        self.assertEqual(told, {self.bob})

    def test_other_events(self):
        subscribe(self.bob, self.shared)
        subscribe(self.bob, self.todo)
        for action in [
            lambda: ops.move_todo(self.todo, todolist=self.internal, actor=self.ada),
            lambda: ops.move_todo(self.todo, todolist=self.shared, actor=self.ada),
            lambda: ops.set_visibility(self.shared, visible=False, actor=self.ada),
            lambda: ops.archive(self.shared, actor=self.ada),
            lambda: ops.unarchive(self.shared, actor=self.ada),
        ]:
            with self.subTest(action=action):
                self.assertTrue(self.told(action))
        # Trashed: nobody can see it any more, nobody is told
        self.assertEqual(self.told(lambda: ops.trash(self.todo, actor=self.ada)), set())
        self.assertEqual(
            self.told(lambda: ops.restore(self.todo, actor=self.ada)), {self.bob}
        )

    def test_project_events_notify_nobody(self):
        dan = person("Dan")
        self.assertEqual(
            self.told(
                lambda: project_ops.add_member(self.project, dan, actor=self.ada)
            ),
            set(),
        )
        event = record(actor=self.ada, action=Action.JOINED, project=self.project)
        self.assertEqual(notify(event.pk), [])

    def test_levels(self):
        subscribe(self.bob, self.todo)
        comment = lambda: ops.add_comment(self.todo, author=self.ada, content="x")  # noqa: E731
        self.bob.notification_level = NotificationLevel.NOTHING
        self.bob.save()
        self.assertEqual(self.told(comment), set())
        # Not even a mention gets through "nothing"
        mention = lambda: ops.add_comment(  # noqa: E731
            self.todo, author=self.ada, content=mentions.syntax(self.bob)
        )
        self.assertEqual(self.told(mention), set())

        self.bob.notification_level = NotificationLevel.CONCERNS_ME
        self.bob.save()
        self.assertEqual(self.told(comment), set())
        self.assertEqual(self.told(mention), {self.bob})
        # Comments on what they commented on
        ops.add_comment(self.todo, author=self.bob, content="me too")
        self.assertEqual(self.told(comment), {self.bob})
        # Their to-dos completed by someone else
        mine = ops.create_todo(todolist=self.shared, title="Mine", creator=self.bob)
        other = ops.create_todo(todolist=self.shared, title="Other", creator=self.ada)
        subscribe(self.bob, other)
        self.assertEqual(
            self.told(lambda: ops.complete(mine, actor=self.ada)), {self.bob}
        )
        self.assertEqual(self.told(lambda: ops.complete(other, actor=self.ada)), set())
        # Being assigned
        self.assertEqual(
            self.told(lambda: ops.assign(other, [self.bob], actor=self.ada)),
            {self.bob},
        )
        # Edits don't concern them
        self.assertEqual(
            self.told(lambda: ops.update_todo(other, actor=self.ada, title="New")),
            set(),
        )

    def test_overrides(self):
        subscribe(self.bob, self.todo)
        comment = lambda: ops.add_comment(self.todo, author=self.ada, content="x")  # noqa: E731
        LevelOverride.objects.create(
            user=self.bob, project=self.project, level=NotificationLevel.NOTHING
        )
        self.assertEqual(effective_level(self.bob, self.todo), "nothing")
        self.assertEqual(self.told(comment), set())
        # The container's override wins over the project's, the item's over
        # the container's
        LevelOverride.objects.create(
            user=self.bob, item=self.shared, level=NotificationLevel.EVERYTHING
        )
        self.assertEqual(self.told(comment), {self.bob})
        LevelOverride.objects.create(
            user=self.bob, item=self.todo, level=NotificationLevel.CONCERNS_ME
        )
        self.assertEqual(effective_level(self.bob, self.todo), "concerns_me")
        self.assertEqual(effective_level(self.bob, self.shared), "everything")
        self.assertEqual(self.told(comment), set())

    def test_edits_merge(self):
        subscribe(self.bob, self.todo)
        told = self.told(
            lambda: ops.update_todo(self.todo, actor=self.ada, title="One")
        )
        self.assertEqual(told, {self.bob})
        first = Notification.objects.get()
        self.told(lambda: ops.update_todo(self.todo, actor=self.ada, title="Two"))
        event = Event.objects.get(action=Action.EDITED)
        self.assertEqual(event.data["title"], "Two")
        # Still one, unsent notification, moved forward
        notification = Notification.objects.get()
        self.assertGreater(notification.created_at, first.created_at)
        # Sent: the session goes on without telling Bob again
        Notification.objects.update(sent_at=timezone.now())
        self.told(lambda: ops.update_todo(self.todo, actor=self.ada, title="Three"))
        self.assertEqual(Notification.objects.count(), 1)
        # Unless he's mentioned now
        self.told(
            lambda: ops.update_todo(
                self.todo, actor=self.ada, notes=mentions.syntax(self.bob)
            )
        )
        self.assertEqual(Notification.objects.filter(user=self.bob).count(), 2)
        self.assertEqual(Event.objects.filter(action=Action.EDITED).count(), 1)
        # After 10 minutes, or by someone else, a new event
        Event.objects.filter(action=Action.EDITED).update(
            created_at=timezone.now() - dt.timedelta(minutes=11)
        )
        ops.update_todo(self.todo, actor=self.ada, title="Four")
        ops.update_todo(self.todo, actor=self.bob, title="Five")
        self.assertEqual(Event.objects.filter(action=Action.EDITED).count(), 3)

    def test_notify_people(self):
        message = ops.create_message(
            project=self.project, title="News", creator=self.ada
        )
        self.assertEqual(notify_people(message, whom="nobody", actor=self.ada), [])
        # Cleo can't see the internal message
        self.assertEqual(
            notify_people(message, whom="everybody", actor=self.ada), [self.bob]
        )
        unsubscribe(self.bob, message)
        self.assertEqual(
            notify_people(message, whom=[self.bob, self.cleo], actor=self.ada),
            [self.bob],
        )
