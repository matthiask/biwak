"""Editing, archiving, the trash and moving without dragging"""

import datetime as dt
import io
import threading

import time_machine
from django.core.management import call_command
from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from biwak.accounts.models import APIToken
from biwak.audit.models import LoggedAction
from biwak.items import operations as ops
from biwak.items.models import Item, Status
from biwak.projects.models import Project
from biwak.test_utils import person, project


class ManageTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.cleo])
        self.internal = ops.create_list(
            project=self.project, title="Internal", creator=self.ada
        )
        self.shared = ops.create_list(
            project=self.project, title="Shared", creator=self.ada, visible=True
        )
        self.group = ops.create_group(todolist=self.shared.todolist, title="Later")
        self.todo = ops.create_todo(
            todolist=self.shared, title="Visible", creator=self.ada
        )
        self.secret = ops.create_todo(
            todolist=self.internal, title="Secret", creator=self.ada
        )

    def test_project_edit_and_archive(self):
        self.client.force_login(self.ada)
        url = f"/projects/{self.project.pk}/"
        response = self.client.post(
            url + "edit/", {"name": "Renamed", "description": "", "is_all_access": ""}
        )
        self.assertRedirects(response, url)
        self.project.refresh_from_db()
        self.assertEqual(self.project.name, "Renamed")
        self.assertFalse(self.project.is_all_access)
        self.client.post(url + "archive/")
        self.assertNotContains(self.client.get("/"), "Renamed")
        self.assertContains(self.client.get("/?archived=1"), "Renamed")
        self.assertContains(self.client.get(url), "Archived on")
        self.client.post(url + "archive/", {"unarchive": "1"})
        self.assertContains(self.client.get("/"), "Renamed")
        # Clients don't
        self.client.force_login(self.cleo)
        self.assertEqual(self.client.get(url + "edit/").status_code, 403)
        self.assertEqual(self.client.post(url + "archive/").status_code, 403)

    def test_list_edit_and_archive(self):
        self.client.force_login(self.ada)
        url = f"/lists/{self.shared.pk}/"
        self.client.post(
            url + "edit/", {"title": "Renamed", "description": "*Hi*", "view": "board"}
        )
        self.shared.refresh_from_db()
        self.assertEqual(self.shared.title, "Renamed")
        self.assertEqual(self.shared.todolist.view, "board")
        self.client.post(url + "archive/")
        response = self.client.get(self.project.get_absolute_url())
        self.assertContains(response, "Archived lists")
        self.assertContains(self.client.get(url), "This list is archived")
        # Clients only change what they created
        self.client.force_login(self.cleo)
        self.assertEqual(self.client.get(url + "edit/").status_code, 403)
        own = ops.create_list(
            project=self.project, title="Wishes", creator=self.cleo, visible=True
        )
        self.assertEqual(self.client.get(f"/lists/{own.pk}/edit/").status_code, 200)

    def test_archiving_twice(self):
        """A double submit archived an archived list: a 500"""
        self.client.force_login(self.ada)
        url = f"/lists/{self.shared.pk}/archive/"
        for data in [{}, {}, {"unarchive": "1"}, {"unarchive": "1"}]:
            self.assertEqual(self.client.post(url, data).status_code, 302, data)
        self.shared.refresh_from_db()
        self.assertEqual(self.shared.status, Status.ACTIVE)

    def test_bad_numbers_are_400(self):
        """int() and pk="x" in moves were 500s"""
        self.client.force_login(self.ada)
        for url, data in [
            (f"/groups/{self.group.pk}/move/", {"index": "x"}),
            (f"/todos/{self.todo.pk}/move/", {"list": "x"}),
            (f"/todos/{self.todo.pk}/move/", {"index": "x"}),
            (f"/todos/{self.todo.pk}/move/", {"group": "x"}),
            (f"/todos/{self.todo.pk}/move/", {"target": "x"}),
            (f"/todos/{self.todo.pk}/move/", {"target": f"{self.shared.pk}:x"}),
            (
                f"/lists/{self.shared.pk}/todos/move/",
                {"todos": [self.todo.pk], "index": "x"},
            ),
            (
                f"/lists/{self.shared.pk}/todos/move/",
                {"todos": [self.todo.pk], "group": "x"},
            ),
        ]:
            with self.subTest(url=url, data=data):
                self.assertEqual(self.client.post(url, data).status_code, 400)

    def test_negative_index_and_the_same_todo_twice(self):
        """The API took index -1 as one from the end; [a, a] left a gap"""
        b = ops.create_todo(todolist=self.shared, title="B", creator=self.ada)
        ops.create_todo(todolist=self.shared, title="C", creator=self.ada)
        _token, secret = APIToken.create_for(user=self.ada, title="T", access="write")
        h = {"authorization": f"Bearer {secret}"}

        def titles():
            return list(
                Item.objects
                .filter(parent=self.shared, todo__group=None)
                .order_by("position")
                .values_list("title", "position")
            )

        response = self.client.post(
            f"/api/v1/todos/{b.pk}/move/",
            {"index": -1},
            content_type="application/json",
            headers=h,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(titles(), [("B", 1), ("Visible", 2), ("C", 3)])
        response = self.client.post(
            f"/api/v1/lists/{self.shared.pk}/todos/move/",
            {"todo_ids": [b.pk, b.pk], "index": 1},
            content_type="application/json",
            headers=h,
        )
        self.assertEqual(response.status_code, 400)
        self.client.force_login(self.ada)
        response = self.client.post(
            f"/lists/{self.shared.pk}/todos/move/", {"todos": [b.pk, b.pk]}
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(titles(), [("B", 1), ("Visible", 2), ("C", 3)])
        with self.assertRaises(ValueError):
            ops.move_todos([b, b], todolist=self.shared, actor=self.ada)

    def test_groups(self):
        second = ops.create_group(todolist=self.shared.todolist, title="Someday")
        self.client.force_login(self.ada)
        self.client.post(f"/groups/{second.pk}/move/", {"index": 0})
        self.assertEqual(
            list(self.shared.todolist.groups.values_list("title", flat=True)),
            ["Someday", "Later"],
        )
        self.client.post(f"/groups/{second.pk}/rename/", {"title": "Maybe"})
        second.refresh_from_db()
        self.assertEqual(second.title, "Maybe")

    def test_clients_dont_change_groups_of_lists_staff_created(self):
        """Clients change only what they created (``can_change()``), the
        groups of a list like the list"""
        second = ops.create_group(todolist=self.shared.todolist, title="Someday")
        self.client.force_login(self.cleo)
        for url, data in [
            (f"/groups/{second.pk}/rename/", {"title": "x"}),
            (f"/groups/{second.pk}/move/", {"index": 0}),
            (f"/groups/{second.pk}/delete/", {}),
            (f"/lists/{self.shared.pk}/groups/", {"title": "New"}),
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url, data).status_code, 403)
        self.assertEqual(
            list(self.shared.todolist.groups.values_list("title", flat=True)),
            ["Later", "Someday"],
        )
        response = self.client.get(self.shared.get_absolute_url())
        self.assertNotContains(response, f"/groups/{second.pk}/")
        self.assertNotContains(response, f"/lists/{self.shared.pk}/groups/")

        _token, secret = APIToken.create_for(user=self.cleo, title="T", access="write")
        headers = {"authorization": f"Bearer {secret}"}
        for method, path, data in [
            ("patch", f"groups/{second.pk}/", {"title": "x", "index": 0}),
            ("delete", f"groups/{second.pk}/", None),
            ("post", f"lists/{self.shared.pk}/groups/", {"title": "New"}),
        ]:
            with self.subTest(method=method, path=path):
                response = getattr(self.client, method)(
                    f"/api/v1/{path}",
                    data,
                    content_type="application/json",
                    headers=headers,
                )
                self.assertEqual(response.status_code, 403)
        self.assertEqual(
            list(self.shared.todolist.groups.values_list("title", flat=True)),
            ["Later", "Someday"],
        )

    def test_clients_change_groups_of_their_lists(self):
        own = ops.create_list(
            project=self.project, title="Ours", creator=self.cleo, visible=True
        )
        group = ops.create_group(todolist=own.todolist, title="Now")
        self.client.force_login(self.cleo)
        self.client.post(f"/groups/{group.pk}/rename/", {"title": "Soon"})
        group.refresh_from_db()
        self.assertEqual(group.title, "Soon")

    def test_move_without_dragging(self):
        self.client.force_login(self.ada)
        other = ops.create_todo(todolist=self.shared, title="Other", creator=self.ada)
        url = f"/todos/{other.pk}/"
        self.assertContains(
            self.client.get(url), f'value="{self.shared.pk}:{self.group.pk}"'
        )
        self.client.post(
            url + "move/", {"target": f"{self.shared.pk}:{self.group.pk}", "index": ""}
        )
        other.refresh_from_db()
        self.assertEqual(other.todo.group, self.group)
        self.client.post(url + "move/", {"target": str(self.shared.pk), "index": "0"})
        self.assertEqual(
            list(
                Item.objects
                .filter(parent=self.shared, todo__group=None)
                .order_by("position")
                .values_list("title", flat=True)
            ),
            ["Other", "Visible"],
        )
        # Into the internal list: hidden from clients now
        self.client.post(url + "move/", {"target": str(self.internal.pk)})
        other.refresh_from_db()
        self.assertFalse(other.is_client_visible)
        # Clients don't get internal lists as targets
        self.client.force_login(self.cleo)
        response = self.client.get(f"/todos/{self.todo.pk}/")
        self.assertNotContains(response, f'value="{self.internal.pk}"')

    def test_move_to_another_project_is_refused(self):
        self.client.force_login(self.ada)
        there = ops.create_list(
            project=project("Other", members=[self.ada]),
            title="There",
            creator=self.ada,
        )
        response = self.client.post(f"/todos/{self.todo.pk}/move/", {"list": there.pk})
        self.assertEqual(response.status_code, 400)
        _token, secret = APIToken.create_for(user=self.ada, title="T", access="write")
        response = self.client.post(
            f"/api/v1/todos/{self.todo.pk}/move/",
            {"list_id": there.pk},
            content_type="application/json",
            headers={"authorization": f"Bearer {secret}"},
        )
        self.assertEqual(response.status_code, 400)
        # Several at once: the same 400 (was 404), 404 for to-dos nobody
        # may know about
        response = self.client.post(
            f"/api/v1/lists/{there.pk}/todos/move/",
            {"todo_ids": [self.todo.pk]},
            content_type="application/json",
            headers={"authorization": f"Bearer {secret}"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(), {"detail": "To-dos can't move to another project."}
        )
        response = self.client.post(
            f"/lists/{there.pk}/todos/move/", {"todos": [self.todo.pk]}
        )
        self.assertEqual(response.status_code, 400)
        response = self.client.post(
            f"/api/v1/lists/{there.pk}/todos/move/",
            {"todo_ids": [999999999]},
            content_type="application/json",
            headers={"authorization": f"Bearer {secret}"},
        )
        self.assertEqual(response.status_code, 404)
        self.todo.refresh_from_db()
        self.assertEqual(self.todo.parent, self.shared)

    def test_move_several(self):
        a, b, c = (
            ops.create_todo(todolist=self.shared, title=t, creator=self.ada)
            for t in "ABC"
        )
        self.client.force_login(self.ada)
        later = ops.create_todo(
            todolist=self.shared, title="L", creator=self.ada, group=self.group
        )
        # C and A (in this order) into the group, after L
        response = self.client.post(
            f"/lists/{self.shared.pk}/todos/move/",
            {"todos": [c.pk, a.pk], "group": self.group.pk, "index": 1},
        )
        self.assertEqual(response.status_code, 204)

        def titles(group):
            return list(
                Item.objects
                .filter(parent=self.shared, todo__group=group)
                .order_by("position")
                .values_list("title", flat=True)
            )

        self.assertEqual(titles(self.group), ["L", "C", "A"])
        self.assertEqual(titles(None), ["Visible", "B"])
        # Back to the top of the ungrouped ones, from two groups at once
        self.client.post(
            f"/lists/{self.shared.pk}/todos/move/",
            {"todos": [later.pk, b.pk], "group": "", "index": 0},
        )
        self.assertEqual(titles(None), ["L", "B", "Visible"])
        self.assertEqual(titles(self.group), ["C", "A"])
        # Into another list (visibility follows), through the API
        _token, secret = APIToken.create_for(user=self.ada, title="T", access="write")
        response = self.client.post(
            f"/api/v1/lists/{self.internal.pk}/todos/move/",
            {"todo_ids": [a.pk, c.pk]},
            content_type="application/json",
            headers={"authorization": f"Bearer {secret}"},
        )
        self.assertEqual([t["title"] for t in response.json()], ["A", "C"])
        self.assertEqual({t["visible_to_clients"] for t in response.json()}, {False})
        self.assertEqual(titles(self.group), [])
        # Clients can't move what they don't see
        self.client.force_login(self.cleo)
        response = self.client.post(
            f"/lists/{self.shared.pk}/todos/move/", {"todos": [self.secret.pk]}
        )
        self.assertEqual(response.status_code, 404)

    def test_board_hides_empty_ungrouped_column(self):
        self.client.force_login(self.ada)
        url = f"/lists/{self.shared.pk}/?view=board"
        self.assertNotContains(
            self.client.get(url), '<section class="wb-group" hidden>'
        )
        ops.move_todo(self.todo, todolist=self.shared, group=self.group, actor=self.ada)
        self.assertContains(self.client.get(url), '<section class="wb-group" hidden>')

    def test_trash_and_restore(self):
        self.client.force_login(self.ada)
        self.client.post(f"/items/{self.todo.pk}/trash/")
        self.client.post(f"/items/{self.shared.pk}/trash/")
        trash = self.client.get(f"/projects/{self.project.pk}/trash/")
        self.assertContains(trash, "Shared")
        # Trashed before its list: it waits for the list
        self.assertContains(trash, "Visible")
        response = self.client.post(f"/items/{self.todo.pk}/restore/")
        self.assertRedirects(response, f"/projects/{self.project.pk}/trash/")
        self.client.post(f"/items/{self.shared.pk}/restore/")
        self.client.post(f"/items/{self.todo.pk}/restore/")
        self.todo.refresh_from_db()
        self.assertEqual(self.todo.status, Status.ACTIVE)

        # Clients: no trash page, only their own things
        self.client.force_login(self.cleo)
        trash_url = f"/projects/{self.project.pk}/trash/"
        self.assertEqual(self.client.get(trash_url).status_code, 403)
        self.assertEqual(
            self.client.post(f"/items/{self.todo.pk}/trash/").status_code, 403
        )
        own = ops.create_todo(todolist=self.shared, title="Mine", creator=self.cleo)
        self.client.post(f"/items/{own.pk}/trash/")
        own.refresh_from_db()
        self.assertEqual(own.status, Status.TRASHED)

    def test_an_archived_list_comes_back_archived(self):
        """Restoring made an archived list active: the archive was lost"""
        ops.archive(self.shared, actor=self.ada)
        ops.trash(self.shared, actor=self.ada)
        ops.restore(Item.objects.get(pk=self.shared.pk), actor=self.ada)
        self.shared.refresh_from_db()
        self.assertEqual(self.shared.status, Status.ARCHIVED)
        # Its to-dos are back too
        self.todo.refresh_from_db()
        self.assertEqual(self.todo.status, Status.ACTIVE)
        # Active ones stay active
        ops.trash(self.internal, actor=self.ada)
        ops.restore(Item.objects.get(pk=self.internal.pk), actor=self.ada)
        self.internal.refresh_from_db()
        self.assertEqual(self.internal.status, Status.ACTIVE)

    def test_purge_and_fairy_tasks(self):
        ops.trash(self.secret, actor=self.ada)
        ops.trash(self.internal, actor=self.ada)
        call_command("fairy_tasks", stdout=io.StringIO())
        self.assertTrue(Item.objects.filter(pk=self.internal.pk).exists())
        with time_machine.travel(timezone.now() + dt.timedelta(days=31)):
            call_command("fairy_tasks", stdout=io.StringIO())
        self.assertFalse(
            Item.objects.filter(pk__in=[self.internal.pk, self.secret.pk]).exists()
        )
        self.assertTrue(Item.objects.filter(pk=self.shared.pk).exists())

    def test_list_order(self):
        self.client.force_login(self.ada)
        url = f"/projects/{self.project.pk}/lists/order/"
        ids = [self.shared.pk, self.internal.pk]
        self.assertEqual(self.client.post(url, {"lists": ids[:1]}).status_code, 400)
        self.assertEqual(self.client.post(url, {"lists": ids}).status_code, 204)
        self.assertEqual(
            list(
                Item.objects
                .filter(project=self.project, parent=None)
                .order_by("position")
                .values_list("title", flat=True)
            ),
            ["Shared", "Internal"],
        )
        self.client.force_login(self.cleo)
        self.assertEqual(self.client.post(url, {"lists": ids}).status_code, 403)

    def test_api(self):
        _token, secret = APIToken.create_for(user=self.ada, title="T", access="write")
        h = {"authorization": f"Bearer {secret}"}

        def send(method, path, data=None):
            return getattr(self.client, method)(
                f"/api/v1/{path}", data, content_type="application/json", headers=h
            )

        data = send("patch", f"projects/{self.project.pk}/", {"archived": True}).json()
        self.assertIsNotNone(data["archived_at"])
        send(
            "patch", f"projects/{self.project.pk}/", {"archived": False, "name": "New"}
        )
        self.assertEqual(Project.objects.get().name, "New")
        data = send(
            "patch", f"lists/{self.shared.pk}/", {"title": "L", "archived": True}
        ).json()
        self.assertEqual((data["title"], data["status"]), ("L", "archived"))
        send("patch", f"lists/{self.shared.pk}/", {"archived": False})
        data = send("patch", f"groups/{self.group.pk}/", {"title": "Soon"}).json()
        self.assertEqual(data["title"], "Soon")
        self.assertEqual(send("delete", f"groups/{self.group.pk}/").status_code, 204)
        response = send(
            "put",
            f"projects/{self.project.pk}/lists/order/",
            {"list_ids": [self.shared.pk, self.internal.pk]},
        )
        self.assertEqual(
            [x["id"] for x in response.json()], [self.shared.pk, self.internal.pk]
        )
        self.assertEqual(
            send("delete", f"items/{self.shared.pk}/").json()["status"], "trashed"
        )
        trash = self.client.get(f"/api/v1/projects/{self.project.pk}/trash/", headers=h)
        self.assertEqual([x["id"] for x in trash.json()], [self.shared.pk])
        self.assertEqual(
            send("post", f"items/{self.shared.pk}/restore/").json()["status"], "active"
        )

    def test_audit_log(self):
        LoggedAction.objects.all().delete()
        self.client.force_login(self.ada)
        self.client.post(
            f"/lists/{self.shared.pk}/edit/",
            {"title": "Audited", "description": "", "view": "list"},
        )
        action = LoggedAction.objects.filter(table_name="items_item", action="U").last()
        self.assertEqual(action.changed_fields["title"], "Audited")
        self.assertEqual(action.user_id, self.ada.pk)


class ConcurrentMovesTest(TransactionTestCase):
    """Two moves into the same list at once: the list's row lock keeps the
    positions distinct (specs/core.md)"""

    def test_concurrent_moves(self):
        ada = person("Ada")
        p = project(members=[ada])
        source = ops.create_list(project=p, title="Source", creator=ada)
        target = ops.create_list(project=p, title="Target", creator=ada)
        todos = [
            ops.create_todo(todolist=source, title=f"T{n}", creator=ada)
            for n in range(6)
        ]
        errors = []
        barrier = threading.Barrier(len(todos))

        def move(todo):
            try:
                barrier.wait()
                ops.move_todo(
                    Item.objects.get(pk=todo.pk), todolist=target, index=0, actor=ada
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                close_old_connections()
                connection.close()

        threads = [threading.Thread(target=move, args=[todo]) for todo in todos]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        positions = list(
            Item.objects.filter(parent=target).values_list("position", flat=True)
        )
        self.assertEqual(len(positions), 6)
        self.assertEqual(len(set(positions)), 6)
