"""``biwak todo add-from-text`` (specs/todos-from-text.md)"""

import json
import tempfile
from pathlib import Path

from biwak.items import operations as ops
from biwak.items.models import Item, Kind
from biwak.test_cli import CLITest


TEXT = "- Book the hall\n\n# Design\n- [x] Logo\n  - colors\n  - fonts\n"


class FromTextCLITest(CLITest):
    def titles(self):
        return list(
            Item.objects
            .filter(parent=self.list, kind=Kind.TODO)
            .order_by("pk")
            .values_list("title", flat=True)
        )

    def test_preview_from_stdin(self):
        result = self.biwak(
            "todo", "add-from-text", self.list.pk, "--preview", input=TEXT
        )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Design (new)", result.output)
        self.assertIn("[x] Logo (0/2)", result.output)
        self.assertIn("Would add 2 to-do(s) to Launch [clients].", result.output)
        self.assertEqual(self.titles(), [])

    def test_adding_a_file(self):
        ops.create_group(todolist=self.list.todolist, title="Design")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.md"
            path.write_text(TEXT)
            result = self.biwak("todo", "add-from-text", self.list.pk, path, "--json")
        data = json.loads(result.stdout)
        self.assertTrue(data["added"])
        self.assertEqual(data["groups"][1]["title"], "Design")
        self.assertFalse(data["groups"][1]["new"])
        self.assertEqual(self.titles(), ["Book the hall", "Logo"])

    def test_problems(self):
        result = self.biwak(
            "todo", "add-from-text", self.list.pk, input="# Only a heading\n"
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("This text has no to-dos.", result.output)
