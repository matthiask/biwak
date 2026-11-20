import datetime as dt
import json
import tempfile
import urllib.parse
from pathlib import Path
from unittest.mock import patch

import biwak_cli
from click.testing import CliRunner
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase

from biwak.accounts.models import APIToken
from biwak.activity.models import LevelOverride
from biwak.files.models import Attachment
from biwak.items import operations as ops
from biwak.items.models import Comment, Item
from biwak.test_utils import person, project


class Response:
    """The parts of a requests response the CLI uses"""

    def __init__(self, response):
        self.status_code = response.status_code
        self.ok = response.status_code < 400
        self.headers = response.headers
        self.text = response.content.decode()
        self._response = response

    def json(self):
        return self._response.json()


class CLITest(TestCase):
    """The real CLI against the API, requests through the test client"""

    def setUp(self):
        self.api_client = Client()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        for patcher in [
            patch.object(biwak_cli.core.requests, "request", self.request),
            patch.object(biwak_cli.core, "CONFIG", Path(directory.name) / "b.toml"),
            patch.object(biwak_cli.commands.console, "_width", 200),
        ]:
            patcher.start()
            self.addCleanup(patcher.stop)
        biwak_cli.core._check_version.cache_clear()
        self.ada = person("Ada")
        self.project = project(members=[self.ada])
        self.list = ops.create_list(
            project=self.project, title="Launch", creator=self.ada, visible=True
        )

    def request(
        self, method, url, *, headers, timeout, params=None, json=None, files=None
    ):
        path = urllib.parse.urlsplit(url).path
        if method == "GET":
            response = self.api_client.get(path, params, headers=headers)
        elif files:
            response = self.api_client.post(
                path,
                {
                    field: SimpleUploadedFile(name, file.read())
                    for field, (name, file) in files.items()
                },
                headers=headers,
            )
        else:
            response = getattr(self.api_client, method.lower())(
                path, json, content_type="application/json", headers=headers
            )
        return Response(response)

    def biwak(self, *args, access="write", input=None):
        _token, token = APIToken.create_for(user=self.ada, title="T", access=access)
        biwak_cli.core.write_config({"url": "http://testserver", "token": token})
        with patch.object(biwak_cli.commands.console, "_color_system", None):
            result = CliRunner().invoke(
                biwak_cli.cli, [str(a) for a in args], input=input
            )
        if result.exception and not isinstance(result.exception, SystemExit):
            raise result.exception
        return result

    def test_workflow(self):
        self.assertIn("Ada Example", self.biwak("me").output)
        self.assertIn("Website", self.biwak("projects").output)
        output = self.biwak("lists", self.project.pk).output
        self.assertIn("Launch", output)
        self.assertIn("[clients]", output)

        result = self.biwak(
            "todo",
            "add",
            self.list.pk,
            "Order the tent",
            "--due",
            "2026-12-01",
            "--assign",
            self.ada.pk,
            "--json",
        )
        data = json.loads(result.stdout)
        self.assertEqual(data["due_on"], "2026-12-01")
        self.assertIn("Order the tent", self.biwak("todos", self.list.pk).output)

        self.biwak("todo", "edit", data["id"], "--due", "none")
        self.assertIsNone(Item.objects.get(pk=data["id"]).todo.due_on)

        result = self.biwak("todo", "comment", data["id"], input="Done *soon*\n")
        self.assertIn("Clients can see this comment.", result.output)
        self.assertIn(
            "Done *soon*", self.biwak("todo", "show", data["id"], "--comments").output
        )

        self.biwak("todo", "done", data["id"])
        self.assertIn(
            "Order the tent", self.biwak("todos", self.list.pk, "--completed").output
        )

    def test_repeat(self):
        result = self.biwak(
            "todo", "add", self.list.pk, "Pay rent", "--due", "2026-11-20",
            "--repeat", "monthly", "--json",
        )  # fmt: skip
        data = json.loads(result.stdout)
        self.assertEqual(data["recurrence"], "FREQ=MONTHLY;BYMONTHDAY=20")
        self.assertIn(
            "Repeats: the 20th of every month",
            self.biwak("todo", "show", data["id"]).output,
        )
        self.biwak("todo", "edit", data["id"], "--repeat", "FREQ=WEEKLY;BYDAY=MO,TH")
        self.assertEqual(
            Item.objects.get(pk=data["id"]).todo.recurrence, "FREQ=WEEKLY;BYDAY=MO,TH"
        )
        self.biwak("todo", "edit", data["id"], "--repeat", "none")
        self.assertEqual(Item.objects.get(pk=data["id"]).todo.recurrence, "")
        result = self.biwak("todo", "edit", data["id"], "--repeat", "sometimes")
        self.assertEqual(result.exit_code, 1)

    def test_todos_across_projects(self):
        other = project("Other", members=[self.ada])
        other_list = ops.create_list(project=other, title="Chores", creator=self.ada)
        ops.create_todo(
            todolist=self.list,
            title="Mine",
            creator=self.ada,
            assignees=[self.ada],
            due_on=dt.date(2020, 1, 1),
        )
        ops.create_todo(todolist=self.list, title="Nobodys", creator=self.ada)
        ops.create_todo(todolist=other_list, title="Elsewhere", creator=self.ada)
        output = self.biwak("todos").output
        for title in ["Mine", "Nobodys", "Elsewhere", "Website / Launch", "2020-01-01"]:
            self.assertIn(title, output)
        output = self.biwak("todos", "--mine").output
        self.assertIn("Mine", output)
        self.assertNotIn("Nobodys", output)
        output = self.biwak("todos", "--project", other.pk).output
        self.assertIn("Elsewhere", output)
        self.assertNotIn("Mine", output)
        output = self.biwak("todos", "--due", "overdue").output
        self.assertIn("Mine", output)
        self.assertNotIn("Elsewhere", output)
        data = json.loads(self.biwak("todos", "--due", "none", "--json").stdout)
        self.assertEqual({t["title"] for t in data}, {"Nobodys", "Elsewhere"})
        self.assertEqual(data[0]["due_group"], "none")
        self.assertEqual(self.biwak("todos", self.list.pk, "--mine").exit_code, 1)
        # The list's own to-dos stay
        self.assertIn("Nobodys", self.biwak("todos", self.list.pk).output)

    def test_read_only_and_errors(self):
        result = self.biwak("todo", "add", self.list.pk, "Nope", access="read")
        self.assertEqual(result.exit_code, 1)
        self.assertIn("only allows reading", result.output)
        result = self.biwak("todo", "show", 999999)
        self.assertEqual(result.exit_code, 1)
        self.assertIn("404", result.output)

    def test_logout(self):
        self.biwak("logout")
        self.assertFalse(APIToken.objects.exists())

    def test_attach(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        plan = Path(directory.name) / "plan.pdf"
        plan.write_bytes(b"%PDF-1.7")
        sketch = Path(directory.name) / "sketch.png"
        sketch.write_bytes(b"\x89PNG\r\n")

        result = self.biwak(
            "todo", "add", self.list.pk, "Pitch the tent", "--attach", plan, "--json"
        )
        data = json.loads(result.stdout)
        attachment = Attachment.objects.get()
        self.assertEqual(attachment.item_id, data["id"])
        self.assertEqual(data["notes"], f"[plan.pdf](attachment:{attachment.key})")

        self.biwak("todo", "edit", data["id"], "--attach", sketch)
        notes = Item.objects.get(pk=data["id"]).todo.notes
        self.assertIn("[plan.pdf]", notes)
        self.assertIn("![sketch.png]", notes)

        self.biwak(
            "todo", "comment", data["id"], "Both", "--attach", plan, "--attach", sketch
        )
        comment = Comment.objects.get()
        self.assertTrue(comment.content.startswith("Both\n\n[plan.pdf](attachment:"))
        self.assertEqual(Attachment.objects.filter(item_id=data["id"]).count(), 4)

    def test_notifications(self):
        output = self.biwak("notifications").output
        self.assertIn("Level: everything", output)
        self.assertIn("Delivery: each", output)
        self.biwak("notifications", "--level", "concerns_me", "--delivery", "digest")
        self.ada.refresh_from_db()
        self.assertEqual(
            (self.ada.notification_level, self.ada.mail_delivery),
            ("concerns_me", "digest"),
        )
        data = json.loads(self.biwak("notifications", "--json").stdout)
        self.assertEqual(data, {"level": "concerns_me", "delivery": "digest"})

        # A project's and an item's own level
        project_id = self.project.pk
        self.assertIn(
            "Level: as usual",
            self.biwak("notifications", "--project", project_id).output,
        )
        self.biwak("notifications", "--project", project_id, "--level", "nothing")
        self.assertIn(
            "Level: nothing",
            self.biwak("notifications", "--project", project_id).output,
        )
        self.biwak("notifications", "--project", project_id, "--level", "default")
        self.assertFalse(LevelOverride.objects.exists())
        result = self.biwak(
            "notifications", "--item", self.list.pk, "--level", "everything", "--json"
        )
        self.assertEqual(
            json.loads(result.stdout), {"item_id": self.list.pk, "level": "everything"}
        )

        # Mistakes
        for args in [
            ["--project", project_id, "--item", self.list.pk],
            ["--project", project_id, "--delivery", "each"],
            ["--level", "default"],
        ]:
            self.assertEqual(self.biwak("notifications", *args).exit_code, 1)
        # Somebody else's project
        other = project("Other", all_access=False)
        result = self.biwak("notifications", "--project", other.pk)
        self.assertEqual(result.exit_code, 1)
        self.assertIn("404", result.output)
