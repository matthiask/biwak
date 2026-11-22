"""The CLI's part of handing over (specs/handover.md)"""

import json

from biwak import test_cli
from biwak.items import operations as ops
from biwak.organizations import activation
from biwak.test_utils import person


class HandoverCLITest(test_cli.CLITest):
    def setUp(self):
        super().setUp()
        self.root = person("Root", is_admin=True)
        self.gil = person("Gil")
        self.todo = ops.create_todo(
            todolist=self.list, title="Copy", creator=self.ada, assignees=[self.gil]
        )

    def test_inactive_assignees(self):
        activation.deactivate([self.gil], actor=self.root)
        output = self.biwak("todos", "show", self.todo.pk).output
        self.assertIn("Gil (inactive)", output)

    def test_assign_several(self):
        bob = person("Bob")
        other = ops.create_todo(todolist=self.list, title="Photos", creator=self.ada)
        output = self.biwak(
            "todos", "assign", self.todo.pk, other.pk, "--to", bob.pk
        ).output
        self.assertIn("Copy [clients]: Bob, Gil", output)
        self.assertIn("Photos [clients]: Bob", output)
        data = json.loads(
            self.biwak(
                "todos",
                "assign",
                self.todo.pk,
                "--to",
                self.ada.pk,
                "--replace",
                "--json",
            ).stdout
        )
        self.assertEqual([a["id"] for a in data[0]["assignees"]], [self.ada.pk])
        # All or nothing
        result = self.biwak("todos", "assign", self.todo.pk, 999999, "--to", bob.pk)
        self.assertNotEqual(result.exit_code, 0)
        self.assertEqual(set(self.todo.todo.assignees.all()), {self.ada})
