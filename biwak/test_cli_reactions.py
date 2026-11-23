"""``biwak reactions create`` and the reactions in ``biwak todos show``; the
CLI test case is the one of test_cli.py"""

import json

from biwak import test_cli
from biwak.activity.models import Action, Event
from biwak.items import operations as ops
from biwak.reactions import operations
from biwak.reactions.models import Reaction
from biwak.test_utils import person


class ReactionsCLITest(test_cli.CLITest):
    def make(self):
        self.bob = person("Bob")
        self.todo = ops.create_todo(
            todolist=self.list, title="Order the tent", creator=self.bob
        )
        self.comment = ops.add_comment(self.todo, author=self.bob, content="Hi")

    def test_react_toggles(self):
        self.make()
        output = self.biwak("reactions", "create", self.todo.pk, "👍").output
        self.assertIn("Reacted with 👍", output)
        self.assertEqual(Reaction.objects.get().user, self.ada)
        self.assertIn(
            "Removed your 👍",
            self.biwak("reactions", "create", self.todo.pk, "👍").output,
        )
        self.assertFalse(Reaction.objects.exists())

    def test_react_to_a_comment_and_json(self):
        self.make()
        data = json.loads(
            self.biwak(
                "reactions",
                "create",
                self.todo.pk,
                "Thanks!",
                "--comment",
                self.comment.pk,
                "--json",
            ).stdout
        )
        self.assertEqual(data[0]["content"], "Thanks!")
        self.assertTrue(data[0]["mine"])
        self.assertEqual(Reaction.objects.get().comment, self.comment)

    def test_too_long_and_read_access(self):
        self.make()
        result = self.biwak("reactions", "create", self.todo.pk, "x" * 41)
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("at most 40", result.output)
        result = self.biwak("reactions", "create", self.todo.pk, "👍", access="read")
        self.assertNotEqual(result.exit_code, 0)
        self.assertFalse(Reaction.objects.exists())

    def test_shown_in_todo_show(self):
        self.make()
        operations.toggle_reaction(self.bob, "👍", item=self.todo)
        operations.toggle_reaction(self.ada, "👍", item=self.todo)
        operations.toggle_reaction(self.ada, "Nice", comment=self.comment)
        output = self.biwak("todos", "show", self.todo.pk, "--comments").output
        self.assertIn("Reactions: 👍 2* (Bob, Ada)", output)
        self.assertIn("Reactions: Nice 1* (Ada)", output)

    def test_react_to_completing(self):
        self.make()
        ops.complete(self.todo, actor=self.bob)
        event = Event.objects.get(action=Action.COMPLETED)
        args = ["reactions", "create", self.todo.pk, "🎉", "--event", event.pk]
        output = self.biwak(*args).output
        self.assertIn(f"Reacted with 🎉 on completing #{self.todo.pk}", output)
        self.assertEqual(Reaction.objects.get().event, event)
        self.assertIn("Removed your 🎉", self.biwak(*args).output)
        self.assertFalse(Reaction.objects.exists())
        result = self.biwak(*args, "--comment", self.comment.pk)
        self.assertNotEqual(result.exit_code, 0)
