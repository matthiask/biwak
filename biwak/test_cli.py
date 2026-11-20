import json
import tempfile
import urllib.parse
from pathlib import Path
from unittest.mock import patch

import biwak_cli
from click.testing import CliRunner
from django.test import Client, TestCase

from biwak.accounts.models import APIToken
from biwak.items import operations as ops
from biwak.items.models import Item
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

    def request(self, method, url, *, headers, timeout, params=None, json=None):
        path = urllib.parse.urlsplit(url).path
        if method == "GET":
            response = self.api_client.get(path, params, headers=headers)
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
