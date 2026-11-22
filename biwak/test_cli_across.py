"""``biwak list copy`` and ``biwak move`` (specs/lists-across-projects.md);
the CLI test case is the one of test_cli.py"""

import datetime as dt
import json

from biwak import test_cli
from biwak.items import operations as ops
from biwak.items.models import Item
from biwak.projects.models import Membership
from biwak.test_utils import person, project


class AcrossCLITest(test_cli.CLITest):
    def setUp(self):
        super().setUp()
        self.shop = project("Shop", members=[self.ada])
        self.tent = ops.create_todo(
            todolist=self.list,
            title="Tent",
            creator=self.ada,
            due_on=dt.date(2026, 12, 1),
        )

    def test_list_copy(self):
        result = self.biwak("list", "copy", self.list.pk, "--to", self.project.pk)
        self.assertEqual(result.exit_code, 0, result.output)
        copy = Item.objects.get(title="Launch (copy)")
        self.assertIn(f"Copied to #{copy.pk} Launch (copy): http", result.output)
        self.assertNotIn("[clients]", result.output)
        data = json.loads(
            self.biwak(
                "list",
                "copy",
                self.list.pk,
                "--to",
                self.shop.pk,
                "--shift",
                "-1",
                "--visible",
                "--json",
            ).stdout
        )
        self.assertEqual(data["project_id"], self.shop.pk)
        self.assertTrue(data["visible_to_clients"])
        self.assertEqual(
            Item.objects.get(parent=data["id"]).todo.due_on, dt.date(2026, 11, 30)
        )
        data = json.loads(
            self.biwak(
                "list",
                "copy",
                self.list.pk,
                "--to",
                self.shop.pk,
                "--no-dates",
                "--title",
                "Next",
                "--json",
            ).stdout
        )
        self.assertEqual(data["title"], "Next")
        self.assertIsNone(Item.objects.get(parent=data["id"]).todo.due_on)
        result = self.biwak(
            "list",
            "copy",
            self.list.pk,
            "--to",
            self.shop.pk,
            "--shift",
            "1",
            "--no-dates",
        )
        self.assertNotEqual(result.exit_code, 0)

    def test_move(self):
        cleo = person("Cleo", client=True)
        Membership.objects.create(project=self.project, user=cleo)
        ops.assign(self.tent, [cleo], actor=self.ada)
        result = self.biwak("move", self.list.pk, "--to", self.shop.pk)
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Cleo Example won't see it in Shop", result.output)
        self.assertIn("confirm", result.output)
        result = self.biwak("move", self.list.pk, "--to", self.shop.pk, "--confirm")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn(
            f"Moved #{self.list.pk} to project {self.shop.pk}. [clients]",
            result.output,
        )
        self.list.refresh_from_db()
        self.assertEqual(self.list.project, self.shop)
