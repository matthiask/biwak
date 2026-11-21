"""Archiving (specs/archiving.md): lists only, from the menus, left out of
the places listed, notifying nobody"""

from django.test import TestCase

from biwak.activity.models import Action, Event
from biwak.items import operations as ops
from biwak.items.models import Item, Status
from biwak.test_utils import person, project


class ArchivingTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.cleo])
        self.list = ops.create_list(
            project=self.project, title="Launch", creator=self.ada, visible=True
        )
        self.own = ops.create_list(
            project=self.project, title="Wishes", creator=self.cleo, visible=True
        )

    def test_only_lists_are_archived(self):
        todo = ops.create_todo(todolist=self.list, title="Tent", creator=self.ada)
        message = ops.create_message(
            project=self.project, title="Hello", creator=self.ada
        )
        doc = ops.create_doc(project=self.project, title="Plan", creator=self.ada)
        folder = ops.create_folder(project=self.project, title="Maps", creator=self.ada)
        for item in [todo, message, doc, folder]:
            with self.subTest(kind=item.kind):
                with self.assertRaises(ValueError):
                    ops.archive(item, actor=self.ada)
                item.refresh_from_db()
                self.assertEqual(item.status, Status.ACTIVE)

    def test_events(self):
        ops.archive(self.list, actor=self.ada)
        ops.unarchive(self.list, actor=self.ada)
        self.assertEqual(
            set(Event.objects.filter(item=self.list).values_list("action", flat=True)),
            {Action.CREATED, Action.ARCHIVED, Action.UNARCHIVED},
        )

    def test_the_menus(self):
        self.client.force_login(self.ada)
        archive = f"/lists/{self.list.pk}/archive/"
        for url in [self.list.get_absolute_url(), self.project.get_absolute_url()]:
            with self.subTest(url=url):
                self.assertContains(self.client.get(url), f'action="{archive}"')
                self.assertContains(self.client.get(url), ">Archive</button>")
        response = self.client.get(self.project.get_absolute_url())
        self.assertContains(
            response, f'name="next" value="{self.project.get_absolute_url()}"'
        )
        self.assertRedirects(
            self.client.post(archive, {"next": self.project.get_absolute_url()}),
            self.project.get_absolute_url(),
        )
        for url in [self.list.get_absolute_url(), self.project.get_absolute_url()]:
            self.assertContains(self.client.get(url), ">Unarchive</button>")
        # Only local addresses
        response = self.client.post(
            archive, {"unarchive": "1", "next": "https://x.example/"}
        )
        self.assertRedirects(
            response, self.list.get_absolute_url(), fetch_redirect_response=False
        )

    def test_clients_archive_what_they_created(self):
        self.client.force_login(self.cleo)
        page = self.client.get(self.project.get_absolute_url())
        self.assertContains(page, f'action="/lists/{self.own.pk}/archive/"')
        self.assertNotContains(page, f'action="/lists/{self.list.pk}/archive/"')
        self.assertEqual(
            self.client.post(f"/lists/{self.list.pk}/archive/").status_code, 403
        )
        self.client.post(f"/lists/{self.own.pk}/archive/")
        self.own.refresh_from_db()
        self.assertEqual(self.own.status, Status.ARCHIVED)

    def test_other_kinds_have_no_archive_url(self):
        message = ops.create_message(
            project=self.project, title="Hello", creator=self.ada
        )
        self.client.force_login(self.ada)
        self.assertEqual(
            self.client.post(f"/lists/{message.pk}/archive/").status_code, 404
        )
        self.assertNotContains(self.client.get(message.get_absolute_url()), "/archive/")

    def test_no_next_to_do_in_an_archived_list(self):
        todo = ops.create_todo(
            todolist=self.list,
            title="Water",
            creator=self.ada,
            due_on="2027-03-01",
            recurrence="FREQ=WEEKLY;BYDAY=MO",
        )
        ops.archive(self.list, actor=self.ada)
        ops.complete(todo, actor=self.ada)
        self.assertEqual(Item.objects.filter(parent=self.list).count(), 1)
        # Brought back, it recurs again
        ops.unarchive(self.list, actor=self.ada)
        ops.reopen(todo, actor=self.ada)
        ops.complete(todo, actor=self.ada)
        self.assertEqual(Item.objects.filter(parent=self.list).count(), 2)
