"""The search command of search.md; the CLI test case is the one of test_cli.py"""

import json

from biwak import test_cli
from biwak.items import operations as ops
from biwak.projects.operations import archive_project
from biwak.test_utils import person, project


class SearchCLITest(test_cli.CLITest):
    def seed(self):
        self.todo = ops.create_todo(
            todolist=self.list,
            title="Order the tent",
            creator=self.ada,
            notes="Bring pegs",
        )
        self.internal = ops.create_message(
            project=self.project,
            title="Budget",
            creator=self.ada,
            content="Raise the pegs budget",
        )

    def test_search(self):
        self.seed()
        output = self.biwak("search", "peg").output
        self.assertIn("Order the tent", output)
        self.assertIn("Budget", output)
        self.assertIn("Bring pegs", output)
        self.assertIn("[clients]", output)
        data = json.loads(self.biwak("search", "--json", "order", "tent").stdout)
        self.assertEqual([r["title"] for r in data], ["Order the tent"])
        self.assertTrue(data[0]["visible_to_clients"])
        self.assertEqual(data[0]["excerpt"], "")
        self.assertIn("<mark>", data[0]["title_html"])
        self.assertNotIn("Order", self.biwak("search", "nothing").output)

    def test_filters(self):
        self.seed()
        data = json.loads(
            self.biwak("search", "pegs", "--kind", "todo", "--json").stdout
        )
        self.assertEqual([r["title"] for r in data], ["Order the tent"])
        other = project("Camp", members=[self.ada])
        ops.create_message(project=other, title="Camp pegs", creator=self.ada)
        data = json.loads(
            self.biwak("search", "pegs", "--project", other.pk, "--json").stdout
        )
        self.assertEqual([r["title"] for r in data], ["Camp pegs"])
        data = json.loads(self.biwak("search", "pegs", "--mine", "--json").stdout)
        self.assertEqual(len(data), 3)
        bob = person("Bob")
        theirs = ops.create_list(project=other, title="Gear", creator=bob)
        ops.create_todo(todolist=theirs, title="Camp pegs, not mine", creator=bob)
        assigned = ops.create_todo(todolist=theirs, title="Camp pegs list", creator=bob)
        ops.assign(assigned, [self.ada], actor=bob)
        data = json.loads(self.biwak("search", "pegs", "--mine", "--json").stdout)
        self.assertEqual(len(data), 4)
        archive_project(other, actor=self.ada)
        self.assertNotIn("Camp", self.biwak("search", "camp").output)
        self.assertIn("(archived)", self.biwak("search", "camp", "--archived").output)
        data = json.loads(self.biwak("search", "pegs", "--json").stdout)
        self.assertEqual(len(data), 2)
        data = json.loads(self.biwak("search", "pegs", "--archived", "--json").stdout)
        self.assertEqual(len(data), 5)
        self.assertEqual([r["archived"] for r in data].count(True), 3)
        self.assertEqual(self.biwak("search", "pegs", "--project", 999999).exit_code, 1)

    def test_comments_are_marked(self):
        self.seed()
        ops.add_comment(self.todo, author=self.ada, content="The parrot colors")
        output = self.biwak("search", "parrot").output
        self.assertIn("(comment)", output)
        self.assertIn("The parrot colors", output)

    def test_limit_and_cursor(self):
        self.seed()
        for n in range(60):
            ops.create_message(
                project=self.project, title=f"Pegs {n}", creator=self.ada
            )
        data = json.loads(self.biwak("search", "pegs", "--limit", 55, "--json").stdout)
        self.assertEqual(len({r["id"] for r in data}), 55)
        data = json.loads(self.biwak("search", "pegs", "--limit", 5, "--json").stdout)
        self.assertEqual(len(data), 5)
