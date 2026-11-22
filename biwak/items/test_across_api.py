"""Copying lists and moving to another project through the API
(specs/lists-across-projects.md)"""

import datetime as dt

from django.test import TestCase

from biwak.accounts.models import APIToken
from biwak.items import operations as ops
from biwak.items.models import Item, Kind
from biwak.items.test_across_views import Fixture
from biwak.projects.models import Membership


class APITest(Fixture, TestCase):
    def api(self, user):
        _token, secret = APIToken.create_for(user=user, title="T", access="write")
        return {"authorization": f"Bearer {secret}"}

    def copy(self, user, item=None, **data):
        return self.client.post(
            f"/api/v1/lists/{(item or self.list).pk}/copy/",
            {"project_id": self.website.pk} | data,
            content_type="application/json",
            headers=self.api(user),
        )

    def move(self, user, item=None, **data):
        return self.client.post(
            f"/api/v1/items/{(item or self.list).pk}/move/",
            {"project_id": self.website.pk} | data,
            content_type="application/json",
            headers=self.api(user),
        )

    def test_copy(self):
        response = self.copy(self.ada, dates="shift", days=2)
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()
        self.assertEqual(data["title"], "Launch")
        self.assertEqual(data["project_id"], self.website.pk)
        self.assertFalse(data["visible_to_clients"])
        todo = Item.objects.get(parent=data["id"])
        self.assertEqual(todo.todo.due_on, dt.date(2026, 12, 3))
        self.assertEqual(list(todo.todo.assignees.all()), [self.ada])
        response = self.copy(
            self.ada,
            project_id=self.pitch.pk,
            dates="remove",
            visible_to_clients=True,
            title="Next launch",
        )
        data = response.json()
        self.assertEqual(data["title"], "Next launch")
        self.assertTrue(data["visible_to_clients"])
        self.assertIsNone(Item.objects.get(parent=data["id"]).todo.due_on)
        self.assertEqual(self.copy(self.ada, dates="shift").status_code, 400)

    def test_copy_refused(self):
        self.assertEqual(self.copy(self.cleo).status_code, 403)
        self.assertEqual(
            self.copy(self.ada, project_id=self.secret.pk).status_code, 404
        )
        internal = ops.create_list(project=self.pitch, title="Plans", creator=self.ada)
        self.assertEqual(self.copy(self.cleo, internal).status_code, 404)
        self.assertEqual(self.copy(self.ada, self.tent).status_code, 404)
        self.website.archived_at = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
        self.website.save()
        self.assertEqual(self.copy(self.ada).status_code, 400)

    def test_move_asks_for_confirm(self):
        response = self.move(self.ada)
        self.assertEqual(response.status_code, 400)
        detail = response.json()["detail"]
        self.assertIn("Cleo Example won't see it in Website", detail)
        self.assertIn("visible to 1 client", detail)
        self.assertIn("confirm", detail)
        self.list.refresh_from_db()
        self.assertEqual(self.list.project, self.pitch)
        response = self.move(self.ada, confirm=True)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["project_id"], self.website.pk)
        self.assertEqual(response.json()["parent_id"], None)

    def test_move_kinds(self):
        message = ops.create_message(project=self.pitch, title="Hi", creator=self.ada)
        folder = ops.create_folder(project=self.pitch, title="Maps", creator=self.ada)
        doc = ops.create_doc(
            project=self.pitch, title="Plan", creator=self.ada, parent=folder
        )
        self.assertEqual(self.move(self.ada, message, confirm=True).status_code, 200)
        # In a folder: with its folder only
        self.assertEqual(self.move(self.ada, doc).status_code, 400)
        response = self.move(self.ada, folder, confirm=True)
        self.assertEqual(response.status_code, 200)
        doc.refresh_from_db()
        self.assertEqual(doc.project, self.website)
        # To-dos stay in their project; a parent in another project isn't a place
        self.assertEqual(self.move(self.ada, self.tent).status_code, 400)
        self.assertEqual(
            self.move(
                self.ada, message, project_id=self.pitch.pk, parent_id=folder.pk
            ).status_code,
            400,
        )

    def test_move_refused(self):
        self.assertEqual(
            self.move(self.ada, project_id=self.secret.pk).status_code, 404
        )
        # Clients: only what they created, where they create such things
        self.assertEqual(self.move(self.cleo, confirm=True).status_code, 403)
        message = ops.create_message(
            project=self.pitch, title="Hi", creator=self.cleo, visible=True
        )
        # Cleo isn't in Website
        self.assertEqual(self.move(self.cleo, message).status_code, 404)
        Membership.objects.create(project=self.website, user=self.cleo)
        own = ops.create_list(
            project=self.pitch, title="Wishes", creator=self.cleo, visible=True
        )
        self.assertEqual(self.move(self.cleo, own, confirm=True).status_code, 403)
        self.assertEqual(self.move(self.cleo, message, confirm=True).status_code, 200)
        self.website.archived_at = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
        self.website.save()
        self.assertEqual(self.move(self.ada, confirm=True).status_code, 400)
        self.list.refresh_from_db()
        self.assertEqual(self.list.project, self.pitch)
        self.assertEqual(self.list.kind, Kind.LIST)
