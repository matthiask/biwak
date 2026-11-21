"""The lantern's command (specs/lantern.md); the CLI test case is the one
of test_cli.py"""

import json

from biwak import test_cli
from biwak.activity import mentions
from biwak.activity.models import Notification
from biwak.activity.operations import subscribe
from biwak.items import operations as ops
from biwak.test_utils import person


class LanternCLITest(test_cli.CLITest):
    def setUp(self):
        super().setUp()
        self.bob = person("Bob")
        self.todo = ops.create_todo(
            todolist=self.list, title="Order the tent", creator=self.bob
        )
        subscribe(self.ada, self.todo)
        with self.captureOnCommitCallbacks(execute=True):
            ops.add_comment(
                self.todo, author=self.bob, content=f"Hi {mentions.syntax(self.ada)}"
            )

    def test_lantern(self):
        output = self.biwak("lantern").output
        self.assertIn("Order the tent", output)
        self.assertIn("new @", output)
        self.assertIn("[clients]", output)
        # Several notifications on one item are one row, as in the menu
        with self.captureOnCommitCallbacks(execute=True):
            ops.add_comment(self.todo, author=self.bob, content="Again")
        output = self.biwak("lantern").output
        self.assertEqual(output.count("Order the tent"), 1)
        self.assertIn("(+1)", output)
        data = json.loads(self.biwak("lantern", "--unread", "--json").stdout)
        self.assertEqual(len(data), 2)
        Notification.objects.filter(
            pk=Notification.objects.order_by("-pk").first().pk
        ).delete()
        data = json.loads(self.biwak("lantern", "--unread", "--json").stdout)
        self.assertEqual(len(data), 1)
        self.assertTrue(data[0]["mentioned"])
        self.assertIn(
            "Marked 1 as read.", self.biwak("lantern", "--read", self.todo.pk).output
        )
        self.assertEqual(
            json.loads(self.biwak("lantern", "--unread", "--json").stdout), []
        )
        self.assertEqual(
            len(json.loads(self.biwak("lantern", "--mentions", "--json").stdout)), 1
        )
        Notification.objects.update(read_at=None)
        self.assertIn("Marked 1 as read.", self.biwak("lantern", "--all").output)
        self.assertEqual(self.biwak("lantern", "--read", 999999).exit_code, 1)
        self.assertEqual(self.biwak("lantern", "--read", 1, "--all").exit_code, 1)
