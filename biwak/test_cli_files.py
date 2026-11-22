"""The commands of files.md, stage 2; the CLI test case is the one of
test_cli.py"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import biwak_cli
import click

from biwak import test_cli
from biwak.accounts.models import APIToken, NotificationLevel
from biwak.activity.models import Action, Event
from biwak.files import operations
from biwak.items import operations as ops
from biwak.items.models import Folder, Item, MessageCategory
from biwak.projects.models import Membership
from biwak.test_utils import bare_doc, person


class FilesCLITest(test_cli.CLITest):
    def setUp(self):
        super().setUp()
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        for user in [self.bob, self.cleo]:
            Membership.objects.create(project=self.project, user=user)
        self.news = MessageCategory.objects.create(name="News", emoji="📣")
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)

    def test_messages(self):
        shared = ops.create_message(
            project=self.project,
            title="Kick-off",
            content="We start **Monday**",
            creator=self.ada,
            visible=True,
            category=self.news,
        )
        ops.create_message(project=self.project, title="Internal", creator=self.ada)
        operations.pin_message(shared, actor=self.ada)
        output = self.biwak("messages", "--project", self.project.pk).output
        for text in ["Kick-off", "Internal", "pinned", "📣 News", "[clients]"]:
            self.assertIn(text, output)
        data = json.loads(
            self.biwak("messages", "--project", self.project.pk, "--json").stdout
        )
        self.assertEqual(
            [m["title"] for m in data["results"]], ["Kick-off", "Internal"]
        )
        output = self.biwak("messages", "show", shared.pk, "--comments").output
        self.assertIn("We start **Monday**", output)
        self.assertIn("(pinned)", output)
        self.assertIn("[clients]", output)

    def test_messages_in_either_order(self):
        """``--order`` looks the other way (specs/files.md, "The message
        board")"""
        first = ops.create_message(
            project=self.project, title="First", creator=self.ada, visible=True
        )
        ops.create_message(
            project=self.project, title="Second", creator=self.ada, visible=True
        )
        ops.add_comment(first, author=self.cleo, content="Bump")
        for user, order, expected in [
            (self.ada, None, ["First", "Second"]),
            (self.ada, "newest", ["Second", "First"]),
            (self.cleo, "latest", ["First", "Second"]),
            (self.cleo, "newest", ["Second", "First"]),
        ]:
            with self.subTest(user=user, order=order):
                args = ["messages", "--project", self.project.pk, "--json"]
                args += ["--order", order] if order else []
                data = json.loads(self.cli_as(user, *args))
                self.assertEqual([m["title"] for m in data["results"]], expected)

    def test_post(self):
        result = self.biwak(
            "messages",
            "create",
            self.project.pk,
            "News",
            "Hello",
            "--category",
            "News",
            "--visible",
            "--json",
        )
        data = json.loads(result.stdout)
        self.assertTrue(data["visible_to_clients"])
        self.assertEqual(data["category"]["name"], "News")
        self.assertIn("Clients can see this message.", result.output)
        item = Item.objects.get(pk=data["id"])
        self.assertEqual(item.message.content, "Hello")
        # Standard input, telling somebody too
        result = self.biwak(
            "messages",
            "create",
            self.project.pk,
            "Piped",
            "--also",
            f"{self.bob.pk}",
            input="From stdin\n",
        )
        self.assertIn("Posted #", result.output)
        self.assertEqual(
            Item.objects.get(title="Piped").message.content, "From stdin\n"
        )

    def test_post_tells_who_wants_and_also(self):
        """Those who want to hear, ``--also`` those added (decided
        2026-11-21: additive)"""
        self.bob.notification_level = NotificationLevel.CONCERNS_ME
        self.bob.save()
        with self.captureOnCommitCallbacks(execute=True):
            result = self.biwak(
                "messages", "create", self.project.pk, "Some", "Text", "--visible",
                "--also", str(self.bob.pk),
            )  # fmt: skip
        self.assertEqual(result.exit_code, 0, result.output)
        event = Event.objects.get(item__title="Some", action=Action.CREATED)
        self.assertEqual(
            {n.user for n in event.notifications.all()}, {self.bob, self.cleo}
        )

    def test_post_notifies_everybody_by_default(self):
        with self.captureOnCommitCallbacks(execute=True):
            result = self.biwak(
                "messages", "create", self.project.pk, "All", "Text", "--visible"
            )
        self.assertEqual(result.exit_code, 0, result.output)
        event = Event.objects.get(item__title="All", action=Action.CREATED)
        self.assertEqual(
            {n.user for n in event.notifications.all()}, {self.bob, self.cleo}
        )

    def test_post_needs_a_known_category(self):
        result = self.biwak(
            "messages", "create", self.project.pk, "No", "Text",
            "--category", "Nope",
        )  # fmt: skip
        self.assertEqual(result.exit_code, 1)
        self.assertIn("No category", result.output)
        result = self.biwak(
            "messages", "create", self.project.pk, "No", "Text", "--also", "some"
        )
        self.assertEqual(result.exit_code, 1)
        self.assertFalse(Item.objects.filter(title="No").exists())

    def test_pin(self):
        message = ops.create_message(project=self.project, title="Hi", creator=self.ada)
        self.assertIn("Pinned", self.biwak("messages", "pin", message.pk).output)
        message.message.refresh_from_db()
        self.assertIsNotNone(message.message.pinned_at)
        self.biwak("messages", "pin", message.pk, "--undo")
        message.message.refresh_from_db()
        self.assertIsNone(message.message.pinned_at)

    def test_attachments_in_messages(self):
        plan = self.directory / "plan.pdf"
        plan.write_bytes(b"%PDF-1.7")
        result = self.biwak(
            "messages", "create", self.project.pk, "With a plan", "See",
            "--attach", plan, "--json",
        )  # fmt: skip
        item = Item.objects.get(pk=json.loads(result.stdout)["id"])
        self.assertEqual(item.attachments.count(), 1)

    def test_folders_and_files(self):
        data = json.loads(
            self.biwak(
                "folders", "create", self.project.pk, "Specs", "--visible", "--json"
            ).stdout
        )
        folder = data["id"]
        self.assertTrue(data["visible_to_clients"])
        plan = self.directory / "plan.txt"
        plan.write_bytes(b"The plan")
        result = self.biwak(
            "files", "upload", self.project.pk, plan, "--folder", folder,
            "--description", "About it", "--json",
        )  # fmt: skip
        uploaded = json.loads(result.stdout)
        self.assertEqual(uploaded["parent_id"], folder)
        self.assertTrue(uploaded["visible_to_clients"])
        self.assertEqual(uploaded["description"], "About it")

        output = self.biwak("files", "--project", self.project.pk).output
        self.assertIn("Specs", output)
        self.assertIn("[clients]", output)
        output = self.biwak(
            "files", "--project", self.project.pk, "--folder", folder
        ).output
        self.assertIn("plan.txt", output)
        self.assertIn("/ Specs", output)
        data = json.loads(
            self.biwak("files", "--project", self.project.pk, "--json").stdout
        )
        self.assertEqual([e["title"] for e in data["entries"]], ["Specs"])

    def test_folder_colors(self):
        data = json.loads(
            self.biwak(
                "folders",
                "create",
                self.project.pk,
                "Tinted",
                "--color",
                "ember",
                "--json",
            ).stdout
        )
        self.assertEqual(Folder.objects.get(pk=data["id"]).color, "ember")
        plain = json.loads(
            self.biwak("folders", "create", self.project.pk, "Plain", "--json").stdout
        )
        self.assertEqual(Folder.objects.get(pk=plain["id"]).color, "")
        output = self.biwak("folders", "update", plain["id"], "--color", "lake").output
        self.assertIn("Lake", output)
        self.assertEqual(Folder.objects.get(pk=plain["id"]).color, "lake")
        output = self.biwak("folders", "update", plain["id"], "--color", "none").output
        self.assertIn("no color", output)
        self.assertEqual(Folder.objects.get(pk=plain["id"]).color, "")
        result = self.biwak("folders", "update", plain["id"], "--color", "amber")
        self.assertNotEqual(result.exit_code, 0)

    def test_renaming_and_ordering_folders(self):
        """Folders: renaming and ordering (specs/files.md, "Folders")"""
        folder = ops.create_folder(
            project=self.project, title="Specs", creator=self.ada
        )
        for title in ["b.md", "a.md"]:
            ops.create_doc(
                project=self.project, title=title, creator=self.ada, parent=folder
            )
        output = self.biwak("folders", "update", folder.pk, "--title", "Briefs").output
        self.assertIn("Briefs, no color", output)
        self.assertNotEqual(self.biwak("folders", "update", folder.pk).exit_code, 0)
        self.assertEqual(Item.objects.get(pk=folder.pk).title, "Briefs")
        output = self.biwak(
            "files", "--project", self.project.pk, "--folder", folder.pk
        ).output
        self.assertIn("Order: alphabetical", output)
        data = json.loads(
            self.biwak(
                "folders", "order", self.project.pk, "newest", "--folder", folder.pk,
                "--json",
            ).stdout
        )  # fmt: skip
        self.assertEqual(data["ordering"], "newest")
        self.assertEqual([e["title"] for e in data["entries"]], ["a.md", "b.md"])
        output = self.biwak("folders", "order", self.project.pk, "reverse").output
        self.assertIn("Order: reverse", output)
        self.project.refresh_from_db()
        self.assertEqual(self.project.files_ordering, "reverse")
        # Staff only
        output = self.cli_as(self.cleo, "folders", "order", self.project.pk, "oldest")
        self.assertIn("403", output)
        self.project.refresh_from_db()
        self.assertEqual(self.project.files_ordering, "reverse")

    def test_upload_download_and_replace(self):
        plan = self.directory / "plan.txt"
        plan.write_bytes(b"One")
        uploaded = json.loads(
            self.biwak("files", "upload", self.project.pk, plan, "--json").stdout
        )
        fid = uploaded["id"]
        self.assertFalse(uploaded["visible_to_clients"])
        target = self.directory / "saved.txt"
        result = self.biwak("files", "download", fid, "-o", target)
        self.assertIn("Saved", result.output)
        self.assertEqual(target.read_bytes(), b"One")

        newer = self.directory / "plan2.txt"
        newer.write_bytes(b"Two")
        self.assertIn("2 versions", self.biwak("files", "replace", fid, newer).output)
        self.biwak("files", "download", fid, "-o", target)
        self.assertEqual(target.read_bytes(), b"Two")
        old = uploaded["versions"][0]["id"]
        self.biwak("files", "download", fid, "--version", old, "-o", target)
        self.assertEqual(target.read_bytes(), b"One")
        result = self.biwak("files", "download", fid, "--version", 999999)
        self.assertEqual(result.exit_code, 1)

    def test_download_to_the_files_name(self):
        item = ops.create_upload(
            project=self.project,
            file=test_cli.SimpleUploadedFile("named.txt", b"Named"),
            creator=self.ada,
        )
        previous = Path.cwd()
        os.chdir(self.directory)
        self.addCleanup(os.chdir, previous)
        self.biwak("files", "download", item.pk)
        self.assertEqual((self.directory / "named.txt").read_bytes(), b"Named")

    def test_moving(self):
        folder = ops.create_folder(
            project=self.project, title="Specs", creator=self.ada, visible=True
        )
        doc = ops.create_doc(project=self.project, title="Notes", creator=self.ada)
        output = self.biwak("folders", "move", doc.pk, folder.pk).output
        self.assertIn("[clients]", output)
        self.assertEqual(Item.objects.get(pk=doc.pk).parent, folder)
        self.biwak("folders", "move", doc.pk)
        self.assertIsNone(Item.objects.get(pk=doc.pk).parent)

    def test_docs(self):
        data = json.loads(
            self.biwak(
                "docs", "create", self.project.pk, "Minutes", "Decided",
                "--json",
            ).stdout
        )  # fmt: skip
        did = data["id"]
        output = self.biwak("docs", "show", did).output
        self.assertIn("Minutes", output)
        self.assertIn("Decided", output)
        self.assertNotIn("[clients]", output)
        self.assertEqual(Item.objects.get(pk=did).doc.content, "# Minutes\n\nDecided")

    def test_the_title_is_the_first_line(self):
        doc = ops.create_doc(
            project=self.project, title="Minutes", content="One", creator=self.ada
        )
        with patch.object(click, "edit", return_value="# Notes\n\nOne"):
            self.biwak("docs", "update", doc.pk)
        doc.refresh_from_db()
        self.assertEqual(doc.title, "Notes")
        self.assertNotEqual(
            self.biwak("docs", "update", doc.pk, "--title", "x").exit_code, 0
        )

    def test_editing_a_doc(self):
        doc = bare_doc(
            project=self.project,
            title="Minutes",
            content="One",
            creator=self.ada,
            visible=True,
        )
        with patch.object(click, "edit", return_value="Two") as edit:
            result = self.biwak("docs", "update", doc.pk)
        edit.assert_called_once()
        self.assertEqual(edit.call_args.args[0], "One")
        self.assertIn("Clients can see this doc.", result.output)
        self.assertIn("Saved", result.output)
        doc.doc.refresh_from_db()
        self.assertEqual(doc.doc.content, "Two")

    def test_editing_without_changes(self):
        doc = bare_doc(
            project=self.project, title="Minutes", content="One", creator=self.ada
        )
        with patch.object(click, "edit", return_value="One"):
            result = self.biwak("docs", "update", doc.pk)
        self.assertIn("No changes", result.output)
        self.assertEqual(doc.doc.versions.count(), 1)

    def test_read_only_docs(self):
        doc = ops.create_doc(
            project=self.project, title="Minutes", content="One", creator=self.ada
        )
        self.assertIn("is read-only", self.biwak("docs", "read-only", doc.pk).output)
        self.assertIn("Read-only.", self.biwak("docs", "show", doc.pk).output)
        with patch.object(click, "edit", return_value="Two") as edit:
            result = self.biwak("docs", "update", doc.pk)
        self.assertEqual(result.exit_code, 1)
        self.assertIn("The doc is read-only.", result.output)
        edit.assert_not_called()
        output = self.biwak("docs", "read-only", doc.pk, "--off").output
        self.assertIn("is editable", output)
        self.assertNotIn("Read-only.", self.biwak("docs", "show", doc.pk).output)

    def test_editing_refuses_to_overwrite_a_newer_version(self):
        doc = ops.create_doc(
            project=self.project, title="Minutes", content="One", creator=self.ada
        )

        def editor(text, **kwargs):
            # Somebody else saves while the editor is open
            operations.update_doc(doc, actor=self.bob, content="Bob's")
            return "Ada's"

        with patch.object(click, "edit", side_effect=editor):
            result = self.biwak("docs", "update", doc.pk)
        self.assertEqual(result.exit_code, 1)
        self.assertIn("saved a newer version", result.output)
        doc.doc.refresh_from_db()
        self.assertEqual(doc.doc.content, "Bob's")

    def test_a_client_cannot_see_internal_items(self):
        secret = ops.create_doc(project=self.project, title="Secret", creator=self.ada)
        private = ops.create_folder(
            project=self.project, title="Private", creator=self.ada
        )
        hidden = ops.create_message(
            project=self.project, title="Hidden", creator=self.ada
        )
        _token, token = APIToken.create_for(user=self.cleo, title="T", access="write")
        biwak_cli.core.write_config({"url": "http://testserver", "token": token})
        for args in [
            ("docs", "show", secret.pk),
            ("files", "--project", self.project.pk, "--folder", private.pk),
            ("messages", "show", hidden.pk),
        ]:
            with patch.object(biwak_cli.commands.console, "_color_system", None):
                result = test_cli.CliRunner().invoke(
                    biwak_cli.cli, [str(a) for a in args]
                )
            self.assertEqual(result.exit_code, 1, args)
            self.assertIn("404", result.output)
        self.assertNotIn(
            "Hidden", self.cli_as(self.cleo, "messages", "--project", self.project.pk)
        )
        self.assertNotIn(
            "Secret", self.cli_as(self.cleo, "files", "--project", self.project.pk)
        )

    def cli_as(self, user, *args):
        _token, token = APIToken.create_for(user=user, title="T", access="write")
        biwak_cli.core.write_config({"url": "http://testserver", "token": token})
        with patch.object(biwak_cli.commands.console, "_color_system", None):
            return (
                test_cli
                .CliRunner()
                .invoke(biwak_cli.cli, [str(a) for a in args])
                .output
            )
