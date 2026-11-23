"""Group colors (specs/core.md, "Group colors", decided 2026-11-23)"""

from django.test import TestCase

from biwak.accounts.models import APIToken
from biwak.activity.models import Event
from biwak.items import operations as ops
from biwak.items.models import Group
from biwak.test_utils import MODAL, assert_modal, person, project


class Base(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.cleo])
        self.shared = ops.create_list(
            project=self.project, title="Shared", creator=self.ada, visible=True
        )
        self.group = ops.create_group(todolist=self.shared.todolist, title="Later")


class OperationsTest(Base):
    def test_none_unless_chosen(self):
        self.assertEqual(self.group.color, "")
        group = ops.create_group(
            todolist=self.shared.todolist, title="Soon", color="lake"
        )
        self.assertEqual(Group.objects.get(pk=group.pk).color, "lake")

    def test_only_the_palette(self):
        for color in ["amber", "red"]:
            with self.subTest(color=color):
                with self.assertRaises(ValueError):
                    ops.create_group(
                        todolist=self.shared.todolist, title="X", color=color
                    )
                with self.assertRaises(ValueError):
                    ops.update_group(self.group, color=color)
        self.group.refresh_from_db()
        self.assertEqual(self.group.color, "")

    def test_a_color_is_no_event(self):
        before = Event.objects.count()
        ops.update_group(self.group, color="ember")
        ops.update_group(self.group, title="Soon", color="")
        self.assertEqual(Event.objects.count(), before)
        self.group.refresh_from_db()
        self.assertEqual((self.group.title, self.group.color), ("Soon", ""))

    def test_copying_a_list_keeps_the_colors(self):
        ops.update_group(self.group, color="moss")
        ops.create_group(todolist=self.shared.todolist, title="Plain")
        copy = ops.copy_list(
            self.shared, project=self.project, title="Shared", actor=self.ada
        )
        self.assertEqual(
            list(copy.todolist.groups.values_list("title", "color")),
            [("Later", "moss"), ("Plain", "")],
        )


class PagesTest(Base):
    def test_the_list_and_the_board_show_it(self):
        ops.update_group(self.group, color="glacier")
        for viewer in [self.ada, self.cleo]:
            self.client.force_login(viewer)
            for view in ["list", "board"]:
                with self.subTest(viewer=viewer, view=view):
                    response = self.client.get(
                        f"{self.shared.get_absolute_url()}?view={view}"
                    )
                    self.assertContains(response, 'data-group-color="glacier"')
                    self.assertContains(response, "Later")

    def test_the_modals_set_it(self):
        self.client.force_login(self.ada)
        url = f"/groups/{self.group.pk}/edit/"
        response = self.client.get(url, headers=MODAL)
        assert_modal(self, response, title="Edit the group")
        self.assertContains(response, 'value="lake"')
        self.assertNotRegex(
            response.content.decode(), r'value="lake"\s+id="[^"]*"\s+checked'
        )
        self.client.post(url, {"title": "Later", "color": "lake"})
        self.group.refresh_from_db()
        self.assertEqual(self.group.color, "lake")
        self.assertRegex(
            self.client.get(url).content.decode(),
            r'value="lake"\s+id="[^"]*"\s+checked',
        )
        response = self.client.post(url, {"title": "Later", "color": "amber"})
        self.assertContains(response, "Select a valid choice.")
        self.client.post(
            f"/lists/{self.shared.pk}/groups/", {"title": "Soon", "color": "berry"}
        )
        self.assertEqual(self.shared.todolist.groups.get(title="Soon").color, "berry")

    def test_the_menu_moves_without_dragging(self):
        second = ops.create_group(todolist=self.shared.todolist, title="Someday")
        self.client.force_login(self.ada)
        response = self.client.get(self.shared.get_absolute_url())
        self.assertContains(response, "Move down", count=1)
        self.assertContains(response, "Move up", count=1)
        self.assertNotContains(response, "bi-arrow-up")
        self.client.post(f"/groups/{second.pk}/move/", {"index": 0})
        self.assertEqual(
            list(self.shared.todolist.groups.values_list("title", flat=True)),
            ["Someday", "Later"],
        )

    def test_clients_color_groups_of_their_own_lists_only(self):
        own = ops.create_list(
            project=self.project, title="Ours", creator=self.cleo, visible=True
        )
        group = ops.create_group(todolist=own.todolist, title="Now")
        self.client.force_login(self.cleo)
        self.client.post(f"/groups/{group.pk}/edit/", {"title": "Now", "color": "lake"})
        group.refresh_from_db()
        self.assertEqual(group.color, "lake")
        response = self.client.post(
            f"/groups/{self.group.pk}/edit/", {"title": "Later", "color": "lake"}
        )
        self.assertEqual(response.status_code, 403)
        self.group.refresh_from_db()
        self.assertEqual(self.group.color, "")


class APITest(Base):
    def api(self, user, method, path, data=None):
        _token, secret = APIToken.create_for(user=user, title="T", access="write")
        return getattr(self.client, method)(
            f"/api/v1/{path}",
            data,
            content_type="application/json",
            headers={"authorization": f"Bearer {secret}"},
        )

    def test_create_update_and_read(self):
        response = self.api(
            self.ada,
            "post",
            f"lists/{self.shared.pk}/groups/",
            {"title": "Soon", "color": "lake"},
        )
        self.assertEqual(response.status_code, 201)
        created = response.json()
        self.assertEqual((created["color"], created["color_name"]), ("lake", "Lake"))
        response = self.api(
            self.ada, "patch", f"groups/{created['id']}/", {"color": ""}
        )
        self.assertEqual(
            (response.json()["color"], response.json()["color_name"]), ("", "")
        )
        response = self.api(
            self.ada, "patch", f"groups/{created['id']}/", {"title": "Next"}
        )
        self.assertEqual(response.json()["title"], "Next")
        for color in ["amber", None]:
            with self.subTest(color=color):
                response = self.api(
                    self.ada, "patch", f"groups/{self.group.pk}/", {"color": color}
                )
                self.assertIn(response.status_code, {400, 422})
        ops.update_group(self.group, color="bark")
        # Clients see it, on the list and on the to-do
        todo = ops.create_todo(
            todolist=self.shared, title="Visible", creator=self.ada, group=self.group
        )
        groups = self.api(self.cleo, "get", f"lists/{self.shared.pk}/").json()["groups"]
        self.assertEqual(groups[0]["color"], "bark")
        self.assertEqual(groups[0]["color_name"], "Bark")
        group = self.api(self.cleo, "get", f"todos/{todo.pk}/").json()["group"]
        self.assertEqual(group["color"], "bark")

    def test_clients_only_in_their_lists(self):
        response = self.api(
            self.cleo, "patch", f"groups/{self.group.pk}/", {"color": "lake"}
        )
        self.assertEqual(response.status_code, 403)
        own = ops.create_list(
            project=self.project, title="Ours", creator=self.cleo, visible=True
        )
        response = self.api(
            self.cleo,
            "post",
            f"lists/{own.pk}/groups/",
            {"title": "Now", "color": "forest"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["color"], "forest")
