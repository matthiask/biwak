"""Forwarded mails through the API (specs/forwarding.md)"""

import json

from django.conf import settings
from django.test import override_settings

from biwak.files.models import Attachment
from biwak.forwarding.models import ForwardedMail
from biwak.forwarding.test_operations import FilingTestCase
from biwak.items import operations as ops
from biwak.items.models import Item
from biwak.test_utils import project


class ForwardedAPITest(FilingTestCase):
    def post(self, forwarded, **data):
        return self.client.post(
            f"/api/v1/forwarded/{forwarded.pk}/file/",
            json.dumps(data),
            content_type="application/json",
        )

    def test_list_own_only(self):
        forwarded = self.forwarded()
        self.forwarded(user=self.bea)
        self.client.force_login(self.ada)
        [data] = self.client.get("/api/v1/forwarded/").json()
        self.assertEqual(data["id"], forwarded.pk)
        self.assertEqual(data["subject"], "Revised quote for the landing page")
        self.assertEqual(
            data["sender"], {"name": "Dora Example", "email": "dora@example.com"}
        )
        self.assertEqual(data["sent_on"], "2026-11-20")
        self.assertEqual(data["cc"], "Finn Example <finn@example.com>")
        image = forwarded.files.get(name="image001.png")
        self.assertIn(f"(forwarded:{image.key})", data["text"])
        self.assertIn(
            f'src="{settings.BASE_URL}{image.get_absolute_url()}"', data["text_html"]
        )
        self.assertEqual(
            [f["name"] for f in data["files"]], ["image001.png", "Quote 2026-117.pdf"]
        )

    def test_clients_get_403(self):
        self.client.force_login(self.cleo)
        self.assertEqual(self.client.get("/api/v1/forwarded/").status_code, 403)

    @override_settings(REPLY_DOMAIN="")
    def test_404_while_off(self):
        self.client.force_login(self.ada)
        self.assertEqual(self.client.get("/api/v1/forwarded/").status_code, 404)

    def test_file_as_message(self):
        forwarded = self.forwarded()
        self.client.force_login(self.ada)
        response = self.post(forwarded, kind="message", project_id=self.project.pk)
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()
        self.assertEqual(data["kind"], "message")
        self.assertEqual(data["title"], "Revised quote for the landing page")
        self.assertFalse(data["visible_to_clients"])
        item = Item.objects.get(pk=data["id"])
        self.assertEqual(Attachment.objects.filter(item=item).count(), 2)
        self.assertFalse(ForwardedMail.objects.exists())

    def test_file_as_todo(self):
        group = ops.create_group(todolist=self.internal.todolist, title="Bugs")
        forwarded = self.forwarded("gmail_en.eml")
        self.client.force_login(self.ada)
        response = self.post(
            forwarded,
            kind="todo",
            list_id=self.internal.pk,
            group_id=group.pk,
            title="Look at the export",
        )
        self.assertEqual(response.status_code, 201, response.content)
        todo = Item.objects.get(pk=response.json()["id"])
        self.assertEqual(todo.title, "Look at the export")
        self.assertEqual(todo.todo.group, group)
        self.assertIn("up 12%", todo.todo.notes)

    def test_file_as_todo_into_a_list_clients_see(self):
        forwarded = self.forwarded("gmail_en.eml")
        self.client.force_login(self.ada)
        response = self.post(forwarded, kind="todo", list_id=self.shared.pk)
        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(response.json()["visible_to_clients"])
        # The client reads it, with its notes and attachments
        self.client.force_login(self.cleo)
        data = self.client.get(f"/api/v1/todos/{response.json()['id']}/").json()
        self.assertIn("up 12%", data["notes"])
        self.assertIn("analytics-2026-11.csv", data["notes_html"])

    def test_refused(self):
        forwarded = self.forwarded("gmail_en.eml")
        limited = project("Payroll", members=[self.bea], all_access=False)
        other = ops.create_list(project=limited, title="Salaries", creator=self.bea)
        self.client.force_login(self.ada)
        for data, status in [
            ({"kind": "message"}, 400),
            ({"kind": "message", "project_id": limited.pk}, 404),
            (
                {"kind": "message", "project_id": self.project.pk, "category_id": 999},
                400,
            ),
            ({"kind": "todo"}, 400),
            ({"kind": "todo", "list_id": other.pk}, 404),
            ({"kind": "todo", "list_id": self.internal.pk, "group_id": 999}, 400),
            ({"kind": "doc", "project_id": self.project.pk}, 422),
        ]:
            with self.subTest(data):
                self.assertEqual(self.post(forwarded, **data).status_code, status)
        self.assertTrue(ForwardedMail.objects.exists())
        self.assertFalse(Item.objects.filter(kind__in=["message", "todo"]).exists())

    def test_somebody_elses_is_404(self):
        forwarded = self.forwarded()
        self.client.force_login(self.bea)
        response = self.post(forwarded, kind="message", project_id=self.project.pk)
        self.assertEqual(response.status_code, 404)
        url = f"/api/v1/forwarded/{forwarded.pk}/"
        self.assertEqual(self.client.delete(url).status_code, 404)
        self.assertTrue(ForwardedMail.objects.exists())

    def test_delete(self):
        forwarded = self.forwarded()
        self.client.force_login(self.ada)
        url = f"/api/v1/forwarded/{forwarded.pk}/"
        self.assertEqual(self.client.delete(url).status_code, 204)
        self.assertFalse(ForwardedMail.objects.exists())
        self.assertEqual(self.client.delete(url).status_code, 404)
