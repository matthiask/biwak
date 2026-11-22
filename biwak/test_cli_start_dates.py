"""``biwak todo … --starts`` (specs/start-dates.md)"""

import datetime as dt
import json

from biwak.items.models import Item
from biwak.test_cli import CLITest


class StartDatesCLITest(CLITest):
    def test_adding_and_changing_the_start_date(self):
        result = self.biwak(
            "todo", "add", self.list.pk, "Book the hall",
            "--due", "2026-12-07", "--starts", "2026-12-03", "--json",
        )  # fmt: skip
        data = json.loads(result.stdout)
        self.assertEqual(data["starts_on"], "2026-12-03")
        output = self.biwak("todo", "show", data["id"]).output
        self.assertIn("Due: 2026-12-07", output)
        self.assertIn("Starts: 2026-12-03", output)
        self.assertIn(
            "2026-12-03 – 2026-12-07",
            self.biwak("todos", "--project", self.project.pk).output,
        )
        self.biwak("todo", "edit", data["id"], "--starts", "2026-12-05")
        todo = Item.objects.get(pk=data["id"]).todo
        self.assertEqual(todo.starts_on, dt.date(2026, 12, 5))
        result = self.biwak("todo", "edit", data["id"], "--starts", "2026-12-08")
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("can't be after the due date", result.output)
        self.biwak("todo", "edit", data["id"], "--starts", "none")
        todo.refresh_from_db()
        self.assertIsNone(todo.starts_on)

    def test_no_start_date_without_a_due_date(self):
        result = self.biwak(
            "todo", "add", self.list.pk, "Nope", "--starts", "2026-12-03"
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("A start date needs a due date.", result.output)
        self.assertFalse(Item.objects.filter(title="Nope").exists())
