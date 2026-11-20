"""The commands of feed.md; the CLI test case is the one of test_cli.py"""

import json

from biwak import test_cli
from biwak.activity.models import Action, Event
from biwak.activity.operations import record
from biwak.items import operations as ops


class FeedCLITest(test_cli.CLITest):
    def test_feed(self):
        todo = ops.create_todo(
            todolist=self.list, title="Order the tent", creator=self.ada
        )
        record(actor=self.ada, action=Action.COMPLETED, project=self.project, item=todo)
        output = self.biwak("feed").output
        self.assertIn("Order the tent", output)
        self.assertIn("completed", output)
        self.assertIn("[clients]", output)
        data = json.loads(self.biwak("feed", "--json", "--action", "completed").stdout)
        self.assertEqual([e["action"] for e in data], ["completed"])
        data = json.loads(self.biwak("feed", "--json", "--limit", 1).stdout)
        self.assertEqual(len(data), 1)
        data = json.loads(
            self.biwak(
                "feed", "--project", self.project.pk, "--since", "2999-01-01", "--json"
            ).stdout
        )
        self.assertEqual(data, [])

    def test_feed_follows_the_cursor(self):
        Event.objects.bulk_create(
            Event(project=self.project, actor=self.ada, action=Action.EDITED_PROJECT)
            for _n in range(205)
        )
        data = json.loads(self.biwak("feed", "--limit", 300, "--json").stdout)
        self.assertEqual(len({e["id"] for e in data}), Event.objects.count())
        self.assertGreater(len(data), 205)


# The tests of test_cli.CLITest run there, not again here
for _name in dir(test_cli.CLITest):
    if _name.startswith("test_") and _name not in vars(FeedCLITest):
        setattr(FeedCLITest, _name, None)
