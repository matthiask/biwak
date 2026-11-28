"""Groups keeping their untouched to-dos for a year (specs/stale-todos.md,
"Backlog groups"): 90 or 365 days, staff only"""

from django.test import TestCase

from biwak.accounts.models import APIToken
from biwak.items import operations as ops
from biwak.items.models import Group, Kind
from biwak.projects import operations as project_ops
from biwak.test_utils import person, project


class BacklogGroupsTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.cleo])
        self.list = ops.create_list(
            project=self.project, title="Board", creator=self.ada, visible=True
        )
        self.group = ops.create_group(todolist=self.list.todolist, title="Backlog")
        # A list Cleo created, so she may change its groups
        self.own = ops.create_list(
            project=self.project, title="Mine", creator=self.cleo, visible=True
        )
        self.own_group = ops.create_group(todolist=self.own.todolist, title="Ideas")

    def test_operations(self):
        self.assertEqual(self.group.stale_after, 90)
        ops.update_group(self.group, stale_after=365)
        self.group.refresh_from_db()
        self.assertEqual(self.group.stale_after, 365)
        with self.assertRaises(ValueError):
            ops.update_group(self.group, stale_after=30)
        with self.assertRaises(ValueError):
            ops.create_group(todolist=self.list.todolist, title="X", stale_after=0)

    def test_copies_keep_it(self):
        """Copying a list and a project from a template keep it (decided
        2026-11-28)"""
        ops.update_group(self.group, stale_after=365)
        copy = ops.copy_list(
            self.list, project=self.project, title="Board", actor=self.ada
        )
        self.assertEqual(copy.todolist.groups.get().stale_after, 365)
        template = project_ops.create_template(name="Boards", actor=self.ada)
        board = ops.create_list(project=template, title="Board", creator=self.ada)
        ops.create_group(todolist=board.todolist, title="Later", stale_after=365)
        website = project_ops.create_from_template(
            template, actor=self.ada, name="Website"
        )
        copied = website.items.get(kind=Kind.LIST)
        self.assertEqual(copied.todolist.groups.get().stale_after, 365)

    def test_form_as_staff(self):
        self.client.force_login(self.ada)
        url = f"/groups/{self.group.pk}/edit/"
        response = self.client.get(url)
        self.assertContains(response, "Keep untouched to-dos for a year")
        self.client.post(url, {"title": "Backlog", "keep_for_a_year": "on"})
        self.group.refresh_from_db()
        self.assertEqual(self.group.stale_after, 365)
        response = self.client.get(url)
        self.assertContains(response, 'id="id_keep_for_a_year" checked')
        self.client.post(url, {"title": "Backlog"})
        self.group.refresh_from_db()
        self.assertEqual(self.group.stale_after, 90)
        self.client.post(
            f"/lists/{self.list.pk}/groups/",
            {"title": "Later", "keep_for_a_year": "on"},
        )
        self.assertEqual(Group.objects.get(title="Later").stale_after, 365)

    def test_form_as_client(self):
        """Clients never see the checkbox; saving keeps what staff chose"""
        ops.update_group(self.own_group, stale_after=365)
        self.client.force_login(self.cleo)
        url = f"/groups/{self.own_group.pk}/edit/"
        response = self.client.get(url)
        self.assertNotContains(response, "Keep untouched to-dos for a year")
        self.client.post(url, {"title": "Ideas", "keep_for_a_year": ""})
        self.own_group.refresh_from_db()
        self.assertEqual(self.own_group.stale_after, 365)

    def call(self, user, method, path, data):
        _token, secret = APIToken.create_for(user=user, title="T", access="write")
        return getattr(self.client, method)(
            f"/api/v1/{path}",
            data,
            content_type="application/json",
            headers={"authorization": f"Bearer {secret}"},
        )

    def test_api(self):
        path = f"groups/{self.group.pk}/"
        response = self.call(self.ada, "patch", path, {"stale_after": 365})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["stale_after"], 365)
        response = self.call(self.ada, "patch", path, {"stale_after": 100})
        self.assertEqual(response.status_code, 400)
        response = self.call(
            self.ada,
            "post",
            f"lists/{self.list.pk}/groups/",
            {"title": "Later", "stale_after": 365},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["stale_after"], 365)
        # Clients change their own lists' groups, not this
        path = f"groups/{self.own_group.pk}/"
        response = self.call(self.cleo, "patch", path, {"stale_after": 365})
        self.assertEqual(response.status_code, 403)
        response = self.call(self.cleo, "patch", path, {"title": "Notes"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["stale_after"], 90)
