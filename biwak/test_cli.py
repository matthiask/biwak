import datetime as dt
import json
import tempfile
import urllib.parse
from pathlib import Path
from unittest.mock import patch

import biwak_cli
from click.shell_completion import get_completion_class
from click.testing import CliRunner
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.test.client import BOUNDARY, MULTIPART_CONTENT, encode_multipart
from rich.color import ColorSystem

from biwak import api_conventions, cli_version
from biwak.accounts.models import APIToken
from biwak.activity.models import LevelOverride
from biwak.files.models import Attachment
from biwak.items import operations as ops
from biwak.items.models import Comment, Item
from biwak.projects.models import Membership
from biwak.test_utils import person, project


class Response:
    """The parts of a requests response the CLI uses"""

    def __init__(self, response):
        self.status_code = response.status_code
        self.ok = response.status_code < 400
        self.headers = response.headers
        # Streamed files (downloads) have no content to decode
        self.content = (
            b"".join(response.streaming_content)
            if response.streaming
            else response.content
        )
        self.text = self.content.decode(errors="replace")
        self._response = response

    def iter_content(self, size):
        yield self.content

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
            patch.object(biwak_cli.core.console, "_width", 200),
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
        self,
        method,
        url,
        *,
        headers,
        timeout,
        params=None,
        json=None,
        files=None,
        data=None,
        stream=False,
    ):
        path = urllib.parse.urlsplit(url).path
        if method == "GET":
            response = self.api_client.get(path, params, headers=headers)
        elif files:
            body = {
                field: SimpleUploadedFile(name, file.read())
                for field, (name, file) in files.items()
            } | (data or {})
            if method == "POST":
                response = self.api_client.post(path, body, headers=headers)
            else:  # PUT: multipart by hand, the test client only does POST
                response = self.api_client.generic(
                    method,
                    path,
                    encode_multipart(BOUNDARY, body),
                    content_type=MULTIPART_CONTENT,
                    headers=headers,
                )
        else:
            response = getattr(self.api_client, method.lower())(
                path, json, content_type="application/json", headers=headers
            )
        return Response(response)

    def biwak(self, *args, access="write", input=None, terminal=False):
        """``terminal``: as in a terminal with colors and links"""
        _token, token = APIToken.create_for(user=self.ada, title="T", access=access)
        biwak_cli.core.write_config({"url": "http://testserver", "token": token})
        system = ColorSystem.TRUECOLOR if terminal else None
        with patch.object(biwak_cli.core.console, "_color_system", system):
            result = CliRunner().invoke(
                biwak_cli.cli, [str(a) for a in args], input=input
            )
        if result.exception and not isinstance(result.exception, SystemExit):
            raise result.exception
        return result


class CLICommandsTest(CLITest):
    """The core's commands; the base class has no tests to rerun"""

    @patch.object(cli_version, "MINIMUM", (0, 14, 0))
    def test_version_warnings(self):
        for version, warning in [
            ("0.14.0", "available"),  # older than the server's
            ("99.0.0", "This Biwak is older than your biwak"),
            (cli_version.LATEST, None),
        ]:
            with self.subTest(version=version):
                biwak_cli.core._check_version.cache_clear()
                with patch.object(biwak_cli.core, "VERSION", version):
                    result = self.biwak("me")
                self.assertEqual(result.exit_code, 0, result.output)
                if warning is None:
                    self.assertNotIn("older than", result.output)
                    self.assertNotIn("is available", result.output)
                else:
                    self.assertIn(warning, result.output)
                    self.assertEqual(result.output.count(warning), 1)
        biwak_cli.core._check_version.cache_clear()
        with patch.object(biwak_cli.core, "VERSION", "0.14.0"):
            result = self.biwak("me")
        self.assertIn(f"biwak {cli_version.LATEST} is available", result.output)
        self.assertIn(cli_version.UPGRADE, result.output)

    def test_titles_link_to_the_page(self):
        """In a terminal, titles are links (OSC 8) to the page, as in gov
        and wb; piped or redirected, plain text"""
        todo = ops.create_todo(
            todolist=self.list, title="Order the tent", creator=self.ada
        )
        url = f"/todos/{todo.pk}/\x1b\\Order the tent"
        for args in [
            ("todos", "--list", self.list.pk),
            ("todos", "show", todo.pk),
            ("lists", "--project", self.project.pk),
            ("projects",),
        ]:
            with self.subTest(args=args):
                linked = self.biwak(*args, terminal=True).output
                self.assertIn("\x1b]8;", linked)
                self.assertNotIn("\x1b]8;", self.biwak(*args).output)
        self.assertIn(url, self.biwak("todos", "show", todo.pk, terminal=True).output)

    def test_headings_by_project_without_markup_tags(self):
        """The console prints no markup (names may have brackets): the
        headings are styled, not tagged"""
        group = ops.create_group(todolist=self.list.todolist, title="[Week 1]")
        ops.create_todo(
            todolist=self.list,
            title="Order the tent",
            creator=self.ada,
            group=group,
            assignees=[self.ada],
        )
        output = self.biwak("todos", "--mine").output
        self.assertNotIn("[bold]", output)
        self.assertNotIn("[dim]", output)
        self.assertIn(f"{self.project.name}\n  Launch\n    [Week 1]\n", output)

    def test_completion_scripts(self):
        for shell in ["bash", "zsh", "fish"]:
            with self.subTest(shell=shell):
                self.assertIn("_BIWAK_COMPLETE", self.biwak("completion", shell).output)

    def test_bash_completion(self):
        """Commands with their descriptions when there are several (bash
        has none of its own), a single one alone, which bash inserts"""

        def complete(words):
            env = {"COMP_WORDS": words, "COMP_CWORD": str(len(words.split(" ")) - 1)}
            with patch.dict("os.environ", env):
                bash = get_completion_class("bash")(
                    biwak_cli.cli, {}, "biwak", "_BIWAK_COMPLETE"
                )
                return bash.complete().splitlines()

        self.assertEqual(complete("biwak complet"), ["plain,completion"])
        listed = complete("biwak todos ")
        self.assertTrue(
            any(
                line.startswith("plain,complete ") and "  -- " in line
                for line in listed
            ),
            listed,
        )
        # Nothing typed after a command without subcommands: its options
        options = complete("biwak settings ")
        self.assertTrue(
            any(line.startswith("plain,--language") for line in options), options
        )

    def test_workflow(self):
        self.assertIn("Ada Example", self.biwak("me").output)
        self.assertIn("Website", self.biwak("projects").output)
        output = self.biwak("lists", "--project", self.project.pk).output
        self.assertIn("Launch", output)
        self.assertIn("[clients]", output)

        result = self.biwak(
            "todos",
            "create",
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
        self.assertIn(
            "Order the tent", self.biwak("todos", "--list", self.list.pk).output
        )

        self.biwak("todos", "update", data["id"], "--due", "none")
        self.assertIsNone(Item.objects.get(pk=data["id"]).todo.due_on)

        result = self.biwak("todos", "comment", data["id"], input="Done *soon*\n")
        self.assertIn("Clients can see this comment.", result.output)
        self.assertIn(
            "Done *soon*", self.biwak("todos", "show", data["id"], "--comments").output
        )

        self.biwak("todos", "complete", data["id"])
        self.assertIn(
            "Order the tent",
            self.biwak("todos", "--list", self.list.pk, "--completed").output,
        )

    def test_settings_language(self):
        output = self.biwak("settings").output
        self.assertIn("Language: auto", output)
        self.assertIn("Single-key shortcuts: on", output)
        self.assertIn("Language: de", self.biwak("settings", "--language", "de").output)
        self.ada.refresh_from_db()
        self.assertEqual(self.ada.language, "de")
        # The CLI stays English (specs/languages.md)
        self.assertIn("Theme: auto", self.biwak("settings").output)
        data = json.loads(self.biwak("settings", "--language", "auto", "--json").output)
        self.assertEqual(data["language"], "")
        self.assertNotEqual(self.biwak("settings", "--language", "fr").exit_code, 0)

    def test_groups_list_and_need_what_they_list(self):
        """The group alone lists (specs/cli-style.md); what it lists by is an
        option only listing needs"""
        for group, option in [
            ("lists", "--project"),
            ("members", "--project"),
            ("messages", "--project"),
            ("checkins", "--project"),
            ("files", "--project"),
            ("links", "--project"),
            ("subscriptions", "--item"),
        ]:
            with self.subTest(group=group):
                result = self.biwak(group)
                self.assertEqual(result.exit_code, 2)
                self.assertIn(f"Missing option '{option}'", result.output)
        self.assertIn(
            "Launch", self.biwak("lists", "--project", self.project.pk).output
        )
        self.assertEqual(self.biwak("todos").exit_code, 0)
        self.assertIn("Commands:", self.biwak("docs").output)

    def test_archiving_lists(self):
        self.assertIn(
            "Archived Launch", self.biwak("lists", "archive", self.list.pk).output
        )
        self.assertNotIn(
            "Launch", self.biwak("lists", "--project", self.project.pk).output
        )
        archived = self.biwak(
            "lists", "--project", self.project.pk, "--archived", "--json"
        )
        self.assertEqual([i["title"] for i in json.loads(archived.stdout)], ["Launch"])
        data = json.loads(
            self.biwak("lists", "unarchive", self.list.pk, "--json").stdout
        )
        self.assertEqual(data["status"], "active")
        self.assertIn(
            "Launch", self.biwak("lists", "--project", self.project.pk).output
        )

    # Small pages, server and CLI: every list comes in several of them
    @patch.object(api_conventions, "PAGE_SIZE", 3)
    @patch.object(api_conventions, "MAX_PAGE_SIZE", 4)
    @patch.object(biwak_cli.core, "MAX_PAGE_SIZE", 4)
    def test_long_lists_are_complete(self):
        """Not only the first page: completed to-dos, comments, to-dos
        across projects"""
        todos = [
            ops.create_todo(todolist=self.list, title=f"Task {n}", creator=self.ada)
            for n in range(10)
        ]
        for todo in todos[:5]:
            ops.complete(todo, actor=self.ada)
        for n in range(5):
            ops.add_comment(todos[0], author=self.ada, content=f"Comment {n}")

        def count(*args):
            return len(json.loads(self.biwak(*args, "--json").stdout))

        self.assertEqual(count("todos", "--list", self.list.pk, "--completed"), 5)
        self.assertEqual(count("todos"), 5)
        self.assertEqual(count("todos", "--completed"), 5)
        data = json.loads(
            self.biwak("todos", "show", todos[0].pk, "--comments", "--json").stdout
        )
        self.assertEqual(len(data["comments"]), 5)
        for todo in todos[:6]:
            ops.reopen(todo, actor=self.ada)
        self.assertEqual(count("todos"), 10)

    def test_no_content(self):
        """request() decoded every answer as JSON: a 204 crashed"""
        group = ops.create_group(todolist=self.list.todolist, title="Later")
        self.biwak("me")  # logs in
        self.assertIsNone(biwak_cli.core.request("DELETE", f"groups/{group.pk}/"))
        self.assertFalse(self.list.todolist.groups.exists())

    def test_groups(self):
        """Groups with their colors (specs/core.md, "Group colors")"""
        output = self.biwak(
            "groups", "create", self.list.pk, "Later", "--color", "lake"
        )
        self.assertIn("Later (Lake)", output.output)
        group = self.list.todolist.groups.get()
        self.assertEqual(group.color, "lake")
        self.biwak("groups", "create", self.list.pk, "Soon")
        listed = self.biwak("groups", "--list", self.list.pk).output
        self.assertIn("Later", listed)
        self.assertIn("Lake", listed)
        output = self.biwak("groups", "update", group.pk, "--color", "none").output
        self.assertIn("Later (no color)", output)
        data = json.loads(
            self.biwak(
                "groups", "update", group.pk, "--title", "Next", "--color", "berry",
                "--index", "1", "--json",
            ).stdout
        )  # fmt: skip
        self.assertEqual(
            (data["title"], data["color"], data["position"]), ("Next", "berry", 2)
        )
        result = self.biwak("groups", "update", group.pk, "--color", "amber")
        self.assertEqual(result.exit_code, 2)
        self.assertEqual(self.biwak("groups", "update", group.pk).exit_code, 2)
        self.assertEqual(self.biwak("groups").exit_code, 2)
        self.biwak("groups", "delete", group.pk)
        self.assertEqual(
            list(self.list.todolist.groups.values_list("title", flat=True)), ["Soon"]
        )

    def test_repeat(self):
        result = self.biwak(
            "todos", "create", self.list.pk, "Pay rent", "--due", "2026-11-20",
            "--repeat", "monthly", "--json",
        )  # fmt: skip
        data = json.loads(result.stdout)
        self.assertEqual(data["recurrence"], "FREQ=MONTHLY;BYMONTHDAY=20")
        self.assertIn(
            "Repeats: the 20th of every month",
            self.biwak("todos", "show", data["id"]).output,
        )
        # Stored and shown in the canonical form (decided 2026-11-21)
        result = self.biwak(
            "todos",
            "update",
            data["id"],
            "--repeat",
            "FREQ=WEEKLY;BYDAY=TH,MO",
            "--json",
        )
        self.assertEqual(
            json.loads(result.stdout)["recurrence"], "FREQ=WEEKLY;BYDAY=MO,TH"
        )
        self.assertEqual(
            Item.objects.get(pk=data["id"]).todo.recurrence, "FREQ=WEEKLY;BYDAY=MO,TH"
        )
        self.biwak("todos", "update", data["id"], "--repeat", "none")
        self.assertEqual(Item.objects.get(pk=data["id"]).todo.recurrence, "")
        result = self.biwak("todos", "update", data["id"], "--repeat", "sometimes")
        self.assertEqual(result.exit_code, 1)

    def test_project_colors(self):
        from biwak.accounts.models import Color

        # The CLI has its own copy of the palette's names
        self.assertEqual(biwak_cli.core.PALETTE, Color.values)
        output = self.biwak(
            "projects", "update", self.project.pk, "--color", "lake"
        ).output
        self.assertIn("Lake", output)
        self.project.refresh_from_db()
        self.assertEqual(self.project.color, "lake")
        self.assertIn("Lake", self.biwak("projects").output)
        data = json.loads(
            self.biwak(
                "projects", "update", self.project.pk, "--color", "none", "--json"
            ).output
        )
        self.assertEqual((data["color"], data["color_name"]), ("", ""))
        # Not a color of the palette
        self.assertNotEqual(
            self.biwak(
                "projects", "update", self.project.pk, "--color", "amber"
            ).exit_code,
            0,
        )
        self.assertNotEqual(
            self.biwak("projects", "update", self.project.pk).exit_code, 0
        )
        data = json.loads(
            self.biwak("projects", "create", "Camp", "--color", "bark", "--json").output
        )
        self.assertEqual(data["color"], "bark")
        data = json.loads(self.biwak("projects", "create", "Other", "--json").output)
        self.assertNotEqual(data["color"], "")

    def test_project_colors_are_staff_only(self):
        client = person("Kim", client=True)
        self.project.memberships.create(user=client)
        self.ada = client
        result = self.biwak("projects", "update", self.project.pk, "--color", "lake")
        self.assertNotEqual(result.exit_code, 0)
        self.project.refresh_from_db()
        self.assertEqual(self.project.color, "")

    def test_checklists(self):
        todo = ops.create_todo(
            todolist=self.list,
            title="Pack",
            creator=self.ada,
            notes="- [x] tent\n- [ ] stove",
        )
        self.assertIn("Checklist: 1/2", self.biwak("todos", "show", todo.pk).output)
        data = json.loads(self.biwak("todos", "show", todo.pk, "--json").stdout)
        self.assertEqual((data["checklist_done"], data["checklist_total"]), (1, 2))
        self.assertIn('type="checkbox"', data["notes_html"])
        # Editing the text changes the count
        self.biwak("todos", "update", todo.pk, "--notes", "- [x] a\n- [x] b\n- [x] c")
        self.assertIn("Checklist: 3/3", self.biwak("todos", "show", todo.pk).output)
        plain = ops.create_todo(todolist=self.list, title="Plain", creator=self.ada)
        self.assertNotIn("Checklist", self.biwak("todos", "show", plain.pk).output)

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
        # By project, with headings
        for title in [
            "Mine",
            "Nobodys",
            "Elsewhere",
            "Website",
            "Launch",
            "2020-01-01",
        ]:
            self.assertIn(title, output)
        self.assertNotIn("Website / Launch", output)
        self.assertLess(output.index("Other"), output.index("Website"))
        self.assertLess(output.index("Chores"), output.index("Elsewhere"))
        self.assertLess(output.index("Website"), output.index("Launch"))
        # By due date: a column with project and list
        output = self.biwak("todos", "--by-due").output
        for title in ["Mine", "Website / Launch", "Other / Chores"]:
            self.assertIn(title, output)
        self.assertLess(output.index("Mine"), output.index("Nobodys"))
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
        for group in ["next_week", "later"]:
            result = self.biwak("todos", "--due", group, "--json")
            self.assertEqual(result.exit_code, 0, group)
            self.assertEqual(json.loads(result.stdout), [])
        self.assertEqual(
            self.biwak("todos", "--list", self.list.pk, "--mine").exit_code, 1
        )
        self.assertEqual(
            self.biwak("todos", "--list", self.list.pk, "--by-due").exit_code, 1
        )
        # The list's own to-dos stay
        self.assertIn("Nobodys", self.biwak("todos", "--list", self.list.pk).output)

    def test_todos_assigned_by_me(self):
        ops.create_todo(
            todolist=self.list, title="Mine", creator=self.ada, assignees=[self.ada]
        )
        ops.create_todo(todolist=self.list, title="Nobodys", creator=self.ada)
        eve = person("Zoe")
        Membership.objects.create(project=self.project, user=eve)
        ops.create_todo(
            todolist=self.list, title="Theirs", creator=eve, assignees=[eve]
        )
        ops.create_todo(
            todolist=self.list, title="Given", creator=self.ada, assignees=[eve]
        )
        # To anybody else: not what Ada gave herself
        output = self.biwak("todos", "--assigned-by-me").output
        self.assertIn("Given", output)
        self.assertNotIn("Mine", output)
        self.assertNotIn("Theirs", output)
        self.assertNotIn("Nobodys", output)
        output = self.biwak("todos", "--assigned-by-me", "--mine").output
        self.assertIn("Mine", output)
        self.assertNotIn("Given", output)
        data = json.loads(self.biwak("todos", "--assigned-by-me", "--json").stdout)
        self.assertEqual({t["title"] for t in data}, {"Given"})
        self.assertEqual(data[0]["assignees"][0]["assigned_by"]["id"], self.ada.pk)
        self.assertEqual(
            self.biwak("todos", "--list", self.list.pk, "--assigned-by-me").exit_code, 1
        )

    def test_optional_arguments_show_in_brackets(self):
        for command, usage in [
            (["todos", "move"], "move [OPTIONS] [TODO]..."),
            (["checkins", "resume"], "resume [OPTIONS] [QUESTION]"),
        ]:
            with self.subTest(command=command):
                self.assertIn(usage, self.biwak(*command, "--help").output)

    def test_read_only_and_errors(self):
        result = self.biwak("todos", "create", self.list.pk, "Nope", access="read")
        self.assertEqual(result.exit_code, 1)
        self.assertIn("only allows reading", result.output)
        result = self.biwak("todos", "show", 999999)
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
            "todos",
            "create",
            self.list.pk,
            "Pitch the tent",
            "--attach",
            plan,
            "--json",
        )
        data = json.loads(result.stdout)
        attachment = Attachment.objects.get()
        self.assertEqual(attachment.item_id, data["id"])
        self.assertEqual(data["notes"], f"[plan.pdf](attachment:{attachment.key})")

        self.biwak("todos", "update", data["id"], "--attach", sketch)
        notes = Item.objects.get(pk=data["id"]).todo.notes
        self.assertIn("[plan.pdf]", notes)
        self.assertIn("![sketch.png]", notes)

        self.biwak(
            "todos", "comment", data["id"], "Both", "--attach", plan, "--attach", sketch
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
        self.assertEqual(
            data,
            {
                "level": "concerns_me",
                "delivery": "digest",
                "lantern_in_favicon": True,
                "quiet_hours": False,
                "working_days": [0, 1, 2, 3, 4],
                "working_from": "08:00:00",
                "working_until": "18:00:00",
                "time_zone": "Europe/Zurich",
            },
        )
        self.biwak("notifications", "--delivery", "none")
        self.ada.refresh_from_db()
        self.assertEqual(self.ada.mail_delivery, "none")
        self.biwak("notifications", "--delivery", "digest")

        # A project's and an item's own level
        project_id = self.project.pk
        self.assertIn(
            "Level: as usual",
            self.biwak("notifications", "--project", project_id).output,
        )
        self.biwak("notifications", "--project", project_id, "--level", "concerns_me")
        self.assertIn(
            "Level: concerns_me",
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


class CLIImageTest(CLITest):
    def picture(self):
        from biwak.accounts.test_images import picture

        directory = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: [f.unlink() for f in directory.iterdir()])
        path = directory / "ada.png"
        path.write_bytes(picture())
        return path

    def test_setting_and_removing_the_profile_image(self):
        path = self.picture()
        result = self.biwak("me", "image", path)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn(
            f"Your profile image: {settings.BASE_URL}/accounts/people/", result.output
        )
        self.ada.refresh_from_db()
        self.assertTrue(self.ada.image)
        data = json.loads(self.biwak("me", "--json").output)
        self.assertTrue(data["image_url"].endswith(self.ada.image_url))
        result = self.biwak("me", "image", "--remove")
        self.assertIn("Removed your profile image.", result.output)
        self.ada.refresh_from_db()
        self.assertEqual(self.ada.image, "")

    def test_json(self):
        data = json.loads(self.biwak("me", "image", self.picture(), "--json").output)
        self.assertIsNotNone(data["image_url"])

    def test_a_file_or_remove_but_not_both_or_neither(self):
        self.assertNotEqual(self.biwak("me", "image").exit_code, 0)
        self.assertNotEqual(
            self.biwak("me", "image", self.picture(), "--remove").exit_code, 0
        )

    def test_a_wrong_file_says_so(self):
        path = self.picture()
        path.write_bytes(b"text")
        result = self.biwak("me", "image", path)
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("JPEG, PNG or WebP", result.output)
