"""Archiving (specs/archiving.md): lists only, from the menus, left out of
the places listed, notifying nobody"""

import datetime as dt
import importlib
from contextlib import contextmanager

from django.apps import apps
from django.test import TestCase
from django.urls import reverse

from biwak.accounts.models import APIToken
from biwak.activity.models import Action, Event
from biwak.items import operations as ops
from biwak.items.models import Item, Status, Todo
from biwak.palette.test_actions import palette_data
from biwak.projects import operations as project_ops
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
        """On the list's page; not on the project page's rows (decided
        2026-11-21: the list itself is the place)"""
        self.client.force_login(self.ada)
        archive = f"/lists/{self.list.pk}/archive/"
        self.assertContains(
            self.client.get(self.list.get_absolute_url()), f'action="{archive}"'
        )
        self.assertContains(
            self.client.get(self.list.get_absolute_url()), ">Archive</button>"
        )
        self.assertNotContains(
            self.client.get(self.project.get_absolute_url()), f'action="{archive}"'
        )
        self.assertRedirects(
            self.client.post(archive, {"next": self.project.get_absolute_url()}),
            self.project.get_absolute_url(),
        )
        self.assertContains(
            self.client.get(self.list.get_absolute_url()), ">Unarchive</button>"
        )
        # Only local addresses
        response = self.client.post(
            archive, {"unarchive": "1", "next": "https://x.example/"}
        )
        self.assertRedirects(
            response, self.list.get_absolute_url(), fetch_redirect_response=False
        )

    def test_clients_archive_what_they_created(self):
        self.client.force_login(self.cleo)
        self.assertContains(
            self.client.get(self.own.get_absolute_url()),
            f'action="/lists/{self.own.pk}/archive/"',
        )
        self.assertNotContains(
            self.client.get(self.list.get_absolute_url()),
            f'action="/lists/{self.list.pk}/archive/"',
        )
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

    def test_api(self):
        _token, secret = APIToken.create_for(user=self.cleo, title="T", access="write")
        headers = {"authorization": f"Bearer {secret}"}

        def call(method, path, data=None):
            return getattr(self.client, method)(
                f"/api/v1/{path}",
                data,
                content_type="application/json",
                headers=headers,
            )

        # A client archives only what they created
        self.assertEqual(
            call("patch", f"lists/{self.list.pk}/", {"archived": True}).status_code, 403
        )
        response = call("patch", f"lists/{self.own.pk}/", {"archived": True})
        self.assertEqual(response.json()["status"], "archived")
        url = f"projects/{self.project.pk}/lists/"
        self.assertEqual([i["title"] for i in call("get", url).json()], ["Launch"])
        archived = call("get", url + "?archived=true").json()
        self.assertEqual([i["title"] for i in archived], ["Wishes"])
        call("patch", f"lists/{self.own.pk}/", {"archived": False})
        self.assertEqual(Item.objects.get(pk=self.own.pk).status, Status.ACTIVE)

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


class MigrationTest(TestCase):
    """0011: the function on the real tables"""

    def test_archived_to_dos_are_completed_and_other_items_active(self):
        ada = person("Ada")
        camp = project(members=[ada])
        todolist = ops.create_list(project=camp, title="Old", creator=ada)
        archived_list = ops.create_list(project=camp, title="Done", creator=ada)
        todo = ops.create_todo(todolist=todolist, title="Tent", creator=ada)
        done = ops.create_todo(todolist=todolist, title="Pegs", creator=ada)
        ops.complete(done, actor=ada)
        trashed = ops.create_todo(todolist=todolist, title="Rope", creator=ada)
        message = ops.create_message(project=camp, title="Hello", creator=ada)
        ops.archive(archived_list, actor=ada)
        # What the old code allowed
        when = dt.datetime(2026, 5, 1, tzinfo=dt.UTC)
        Item.objects.filter(pk__in=[todo.pk, done.pk, message.pk]).update(
            status=Status.ARCHIVED, updated_at=when
        )
        Item.objects.filter(pk=trashed.pk).update(
            status=Status.TRASHED, archived_when_trashed=True
        )
        completed_at = Todo.objects.get(item=done).completed_at

        migration = importlib.import_module(
            "biwak.items.migrations.0011_archived_lists_only"
        )
        migration.convert(apps, None)

        statuses = {i.title: i.status for i in Item.objects.filter(project=camp)}
        self.assertEqual(statuses["Tent"], Status.ACTIVE)
        self.assertEqual(statuses["Hello"], Status.ACTIVE)
        self.assertEqual(statuses["Rope"], Status.TRASHED)
        self.assertEqual(statuses["Done"], Status.ARCHIVED)
        todo.todo.refresh_from_db()
        self.assertEqual(todo.todo.completed_at, when)
        done.todo.refresh_from_db()
        self.assertEqual(done.todo.completed_at, completed_at)
        trashed.todo.refresh_from_db()
        self.assertIsNotNone(trashed.todo.completed_at)
        self.assertFalse(Item.objects.get(pk=trashed.pk).archived_when_trashed)


class ClosedListsTest(TestCase):
    """Archived lists and lists in archived projects take no new or moved
    to-dos, at every entry point (decided 2026-11-28); reordering what's
    there stays"""

    MESSAGE = "No to-dos can be added to this list."

    def setUp(self):
        self.ada = person("Ada")
        self.project = project(members=[self.ada])
        self.list = ops.create_list(
            project=self.project, title="Launch", creator=self.ada
        )
        self.other = ops.create_list(
            project=self.project, title="Later", creator=self.ada
        )
        self.tent = ops.create_todo(todolist=self.list, title="Tent", creator=self.ada)
        self.stove = ops.create_todo(
            todolist=self.list, title="Stove", creator=self.ada
        )
        self.map = ops.create_todo(todolist=self.other, title="Map", creator=self.ada)
        self.client.force_login(self.ada)

    def archived_list(self):
        ops.archive(self.list, actor=self.ada)

    def archived_project(self):
        project_ops.archive_project(self.project, actor=self.ada)

    @contextmanager
    def closed(self, what):
        """The list archived, or its project, brought back afterwards"""
        if what == "list":
            self.archived_list()
        else:
            self.archived_project()
        self.list.refresh_from_db()
        try:
            yield
        finally:
            if what == "list":
                ops.unarchive(self.list, actor=self.ada)
            else:
                project_ops.unarchive_project(self.project, actor=self.ada)
            self.list.refresh_from_db()

    def test_operations(self):
        for what in ("list", "project"):
            with self.subTest(closed=what), self.closed(what):
                with self.assertRaisesMessage(ValueError, self.MESSAGE):
                    ops.create_todo(todolist=self.list, title="Rope", creator=self.ada)
                with self.assertRaisesMessage(ValueError, self.MESSAGE):
                    ops.move_todo(self.map, todolist=self.list, actor=self.ada)
                # Reordering stays
                ops.move_todo(self.stove, todolist=self.list, index=0, actor=self.ada)
                self.assertEqual(
                    list(ops.open_todos(self.list).values_list("title", flat=True)),
                    ["Stove", "Tent"],
                )
                ops.move_todo(self.stove, todolist=self.list, actor=self.ada)

    def test_the_inline_form(self):
        url = self.list.get_absolute_url()
        self.assertContains(self.client.get(url), "wb-add-todo-form")
        actions = {a["label"] for a in palette_data(self.client.get(url))["actions"]}
        self.assertIn("New to-do", actions)
        for what in ("list", "project"):
            with self.subTest(closed=what), self.closed(what):
                response = self.client.get(url)
                self.assertNotContains(response, "wb-add-todo-form")
                actions = {a["label"] for a in palette_data(response)["actions"]}
                self.assertNotIn("New to-do", actions)
                response = self.client.post(
                    url, {"title": "Rope"}, headers={"X-Biwak-Fragment": "1"}
                )
                self.assertContains(response, self.MESSAGE, status_code=422)
                self.assertFalse(Item.objects.filter(title="Rope").exists())

    def test_dragging(self):
        for what in ("list", "project"):
            with self.subTest(closed=what), self.closed(what):
                response = self.client.post(
                    f"/todos/{self.map.pk}/move/",
                    {"list": self.list.pk, "index": "0", "quiet": "1"},
                )
                self.assertEqual(response.status_code, 400)
                response = self.client.post(
                    f"/lists/{self.list.pk}/todos/move/",
                    {"todos": [self.map.pk], "index": "0"},
                )
                self.assertEqual(response.status_code, 400)
                self.map.refresh_from_db()
                self.assertEqual(self.map.parent_id, self.other.pk)

    def test_moving_without_dragging(self):
        """ "Move to…" doesn't offer archived lists; in an archived project
        it says why"""
        url = f"/todos/{self.map.pk}/move-to/"
        data = {"target": str(self.list.pk), "index": "end"}
        with self.closed("list"):
            self.assertNotContains(self.client.get(url), f'value="{self.list.pk}"')
            response = self.client.post(url, data)
            self.assertContains(response, "Select a valid choice.")
        with self.closed("project"):
            self.assertContains(self.client.post(url, data), self.MESSAGE)
        self.map.refresh_from_db()
        self.assertEqual(self.map.parent_id, self.other.pk)

    def test_moving_several(self):
        """The selection's "Move…" into another list of an archived project,
        by a client (staff choose among active projects only)"""
        cleo = person("Cleo", client=True)
        project_ops.add_member(self.project, cleo, actor=self.ada)
        here = ops.create_list(
            project=self.project, title="Here", creator=self.ada, visible=True
        )
        there = ops.create_list(
            project=self.project, title="There", creator=self.ada, visible=True
        )
        rope = ops.create_todo(todolist=here, title="Rope", creator=self.ada)
        self.archived_project()
        self.client.force_login(cleo)
        response = self.client.post(
            f"{reverse('todos_move_selected')}?items={rope.pk}",
            {"target": str(there.pk), "index": "end"},
        )
        self.assertContains(response, self.MESSAGE)
        rope.refresh_from_db()
        self.assertEqual(rope.parent_id, here.pk)

    def test_api(self):
        def call(path, data):
            return self.client.post(
                f"/api/v1/{path}", data, content_type="application/json"
            )

        for what in ("list", "project"):
            with self.subTest(closed=what), self.closed(what):
                for path, data in [
                    (f"lists/{self.list.pk}/todos/", {"title": "Rope"}),
                    (f"todos/{self.map.pk}/move/", {"list_id": self.list.pk}),
                    (f"lists/{self.list.pk}/todos/move/", {"todo_ids": [self.map.pk]}),
                    ("todos/move/", {"ids": [self.map.pk], "list_id": self.list.pk}),
                ]:
                    with self.subTest(path=path):
                        response = call(path, data)
                        self.assertContains(response, self.MESSAGE, status_code=400)
                self.map.refresh_from_db()
                self.assertEqual(self.map.parent_id, self.other.pk)

    def test_no_next_to_do_in_an_archived_project(self):
        todo = ops.create_todo(
            todolist=self.list,
            title="Water",
            creator=self.ada,
            due_on="2027-03-01",
            recurrence="FREQ=WEEKLY;BYDAY=MO",
        )
        self.archived_project()
        ops.complete(todo, actor=self.ada)
        self.assertFalse(
            Item.objects
            .filter(parent=self.list, title="Water")
            .exclude(pk=todo.pk)
            .exists()
        )
