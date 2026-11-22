"""The CLI's part of handing over (specs/handover.md)"""

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
        output = self.biwak("todo", "show", self.todo.pk).output
        self.assertIn("Gil (inactive)", output)
