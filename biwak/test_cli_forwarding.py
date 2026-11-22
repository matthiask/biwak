"""``biwak forwarded`` (specs/forwarding.md); the CLI test case is the one
of test_cli.py"""

import json

from biwak import test_cli
from biwak.forwarding import operations as forwarding
from biwak.forwarding.models import ForwardedMail
from biwak.forwarding.support import sample
from biwak.inbound.support import replying
from biwak.items import operations as ops
from biwak.items.models import Item


@replying
class ForwardedCLITest(test_cli.CLITest):
    def setUp(self):
        super().setUp()
        self.internal = ops.create_list(
            project=self.project, title="Internal", creator=self.ada
        )

    def test_list_file_delete(self):
        quote = forwarding.store(self.ada, sample("outlook_en.eml"))
        export = forwarding.store(self.ada, sample("gmail_en.eml"))
        footer = forwarding.store(self.ada, sample("apple_mail_en.eml"))
        result = self.biwak("forwarded")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Revised quote for the landing page", result.output)
        self.assertIn("Dora Example <dora@example.com>", result.output)
        data = json.loads(self.biwak("forwarded", "--json").stdout)
        self.assertEqual([m["id"] for m in data], [footer.pk, export.pk, quote.pk])

        result = self.biwak("forwarded", "file", quote.pk, "--message", self.project.pk)
        self.assertEqual(result.exit_code, 0, result.output)
        message = Item.objects.get(kind="message")
        self.assertIn(f"Filed as #{message.pk} Revised quote", result.output)
        self.assertFalse(message.is_client_visible)

        result = self.biwak(
            "forwarded",
            "file",
            export.pk,
            "--todo",
            self.internal.pk,
            "--title",
            "Look at the export",
            "--json",
        )
        self.assertEqual(result.exit_code, 0, result.output)
        todo = Item.objects.get(pk=json.loads(result.stdout)["id"])
        self.assertEqual(todo.title, "Look at the export")
        self.assertEqual(todo.parent, self.internal)

        result = self.biwak("forwarded", "delete", footer.pk)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Deleted", result.output)
        self.assertFalse(ForwardedMail.objects.exists())

    def test_message_or_todo(self):
        mail = forwarding.store(self.ada, sample("gmail_en.eml"))
        result = self.biwak("forwarded", "file", mail.pk)
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("--message PROJECT or --todo LIST", result.output)
        self.assertTrue(ForwardedMail.objects.exists())
        # Lists clients see too: the to-do follows its list
        result = self.biwak("forwarded", "file", mail.pk, "--todo", self.list.pk)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue(Item.objects.get(kind="todo").is_client_visible)
