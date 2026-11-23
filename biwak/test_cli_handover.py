"""The CLI's part of handing over (specs/handover.md)"""

import json

from biwak import test_cli
from biwak.items import operations as ops
from biwak.organizations import activation
from biwak.test_utils import person, project


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

    def test_todos_of_a_person(self):
        """Somebody's open to-dos, also after they left (handing over)"""
        ops.create_todo(
            todolist=self.list, title="Print", creator=self.ada, assignees=[self.ada]
        )
        activation.deactivate([self.gil], actor=self.root)
        output = self.biwak("todos", "--assignee", self.gil.pk).output
        self.assertIn("Copy", output)
        self.assertNotIn("Print", output)
        data = json.loads(
            self.biwak("todos", "--assignee", self.gil.pk, "--by-due", "--json").stdout
        )
        self.assertEqual([t["id"] for t in data], [self.todo.pk])
        self.assertEqual(
            self.biwak("todos", "--assignee", self.gil.pk, "--mine").exit_code, 1
        )
        self.assertEqual(
            self.biwak("todos", "--list", self.list.pk, "--assignee", 1).exit_code, 1
        )

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

    def test_dates_several(self):
        other = ops.create_todo(todolist=self.list, title="Photos", creator=self.ada)
        output = self.biwak(
            "todos", "dates", self.todo.pk, other.pk, "--due", "2026-12-20"
        ).output
        self.assertIn("Copy: 2026-12-20", output)
        self.assertIn("Photos: 2026-12-20", output)
        data = json.loads(
            self.biwak("todos", "dates", other.pk, "--shift", "-2", "--json").stdout
        )
        self.assertEqual(data[0]["due_on"], "2026-12-18")
        output = self.biwak("todos", "dates", other.pk, "--remove").output
        self.assertIn("Photos: -", output)
        for args in [[], ["--remove", "--shift", "1"]]:
            with self.subTest(args=args):
                result = self.biwak("todos", "dates", other.pk, *args)
                self.assertNotEqual(result.exit_code, 0)

    def test_move_several(self):
        later = ops.create_list(project=self.project, title="Later", creator=self.ada)
        other = ops.create_todo(todolist=self.list, title="Photos", creator=self.ada)
        output = self.biwak(
            "todos", "move", other.pk, self.todo.pk, "--list", later.pk
        ).output
        self.assertIn(f"Moved #{other.pk} Photos.", output)
        self.todo.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(self.todo.parent_id, later.pk)
        self.assertLess(other.position, self.todo.position)

    def test_move_across_projects(self):
        other = project("Other", members=[self.ada], all_access=False)
        later = ops.create_list(project=other, title="Later", creator=self.ada)
        result = self.biwak("todos", "move", self.todo.pk, "--list", later.pk)
        self.assertEqual(result.exit_code, 1)
        self.assertIn("Gil Example will be added to Other.", result.output)
        output = self.biwak(
            "todos", "move", self.todo.pk, "--list", later.pk, "--confirm"
        ).output
        self.assertIn(f"Moved #{self.todo.pk} Copy.", output)
        self.todo.refresh_from_db()
        self.assertEqual(self.todo.project, other)
