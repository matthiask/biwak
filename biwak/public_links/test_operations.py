"""Public links (specs/public-links.md): the operations; the fixture of the
other tests"""

import datetime as dt

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from biwak.activity.models import Action, Event, Notification
from biwak.activity.notify import notify
from biwak.items import operations as ops
from biwak.projects import operations as project_ops
from biwak.public_links import operations as link_ops
from biwak.public_links.models import PublicLink
from biwak.test_utils import (
    person,
    project,
)


class Fixture:
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")  # Staff, subscribed to everything below
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.bob, self.cleo])
        self.todolist = ops.create_list(
            project=self.project, title="Internal", creator=self.ada
        )
        self.todo = ops.create_todo(
            todolist=self.todolist,
            title="Pitch the tent",
            creator=self.ada,
            notes="- [ ] pegs\n- [x] poles",
        )
        self.client.force_login(self.ada)

    def share(self, item=None, days=7, actor=None):
        return link_ops.create_public_link(
            item or self.todo, days=days, actor=actor or self.ada
        )


class OperationsTest(Fixture, TestCase):
    def test_create_replace_and_stop(self):
        link = self.share(days=3)
        self.assertEqual(len(link.token), 43)
        self.assertAlmostEqual(
            link.expires_at,
            timezone.now() + dt.timedelta(days=3),
            delta=dt.timedelta(seconds=10),
        )
        new = self.share(days=30)
        self.assertNotEqual(new.token, link.token)
        self.assertEqual(PublicLink.objects.get().token, new.token)
        link_ops.stop_public_link(self.todo, actor=self.ada)
        self.assertFalse(PublicLink.objects.exists())
        # Stopping again changes nothing
        self.assertIsNone(link_ops.stop_public_link(self.todo, actor=self.ada))
        self.assertEqual(
            list(
                Event.objects
                .filter(item=self.todo)
                .order_by("pk")
                .values_list("action", flat=True)[1:]
            ),
            [Action.SHARED_PUBLICLY, Action.SHARED_PUBLICLY, Action.STOPPED_SHARING],
        )
        event = (
            Event.objects.filter(action=Action.SHARED_PUBLICLY).order_by("pk").last()
        )
        self.assertEqual(event.data["days"], 30)

    def test_only_the_days_offered(self):
        for days in (0, 2, 31, 365):
            with self.subTest(days=days), self.assertRaises(ValueError):
                self.share(days=days)
        for days in (1, 3, 7, 30):
            self.share(days=days)

    def test_not_containers_and_not_by_clients(self):
        from django.core.exceptions import PermissionDenied

        with self.assertRaises(PermissionDenied):
            self.share(self.todolist)
        folder = ops.create_folder(project=self.project, title="F", creator=self.ada)
        with self.assertRaises(PermissionDenied):
            self.share(folder)
        with self.assertRaises(PermissionDenied):
            self.share(actor=self.cleo)

    def test_the_events_notify_nobody(self):
        ops.assign(self.todo, [self.bob], actor=self.ada)
        Notification.objects.all().delete()
        self.share()
        link_ops.stop_public_link(self.todo, actor=self.ada)
        for event in Event.objects.filter(
            action__in=[Action.SHARED_PUBLICLY, Action.STOPPED_SHARING]
        ):
            self.assertEqual(notify(event.pk), [])
        self.assertFalse(Notification.objects.exists())

    def test_trashing_ends_it_for_good(self):
        link = self.share()
        ops.trash(self.todo, actor=self.ada)
        self.assertFalse(PublicLink.objects.exists())
        ops.restore(self.todo, actor=self.ada)
        self.assertFalse(PublicLink.objects.exists())
        self.assertEqual(self.client.get(f"/p/{link.token}/").status_code, 404)

    def test_trashing_the_container(self):
        self.share()
        ops.trash(self.todolist, actor=self.ada)
        self.assertFalse(PublicLink.objects.exists())
        ops.restore(self.todolist, actor=self.ada)
        self.assertFalse(PublicLink.objects.exists())

    def test_archiving_the_project(self):
        other = project("Other", members=[self.ada])
        message = ops.create_message(project=other, title="M", creator=self.ada)
        self.share()
        kept = self.share(message)
        project_ops.archive_project(self.project, actor=self.ada)
        self.assertEqual(list(PublicLink.objects.all()), [kept])
        project_ops.unarchive_project(self.project, actor=self.ada)
        self.assertEqual(list(PublicLink.objects.all()), [kept])

    def test_fairy_tasks_delete_expired_links(self):
        link = self.share(days=1)
        message = ops.create_message(project=self.project, title="M", creator=self.ada)
        live = self.share(message)
        PublicLink.objects.filter(pk=link.pk).update(
            expires_at=timezone.now() - dt.timedelta(minutes=1)
        )
        call_command("fairy_tasks")
        self.assertEqual(list(PublicLink.objects.all()), [live])
