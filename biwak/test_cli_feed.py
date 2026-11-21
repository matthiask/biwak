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

    def test_bookmarks(self):
        todo = ops.create_todo(
            todolist=self.list, title="Order the tent", creator=self.ada
        )
        self.biwak("bookmark", "add", todo.pk)
        self.biwak("bookmark", "add", "--project", self.project.pk)
        output = self.biwak("bookmarks").output
        self.assertIn("Order the tent", output)
        self.assertIn("todo", output)
        self.assertIn("Website", output)
        self.assertIn("[clients]", output)
        data = json.loads(self.biwak("bookmarks", "--json").stdout)
        self.assertEqual([b["project"] is None for b in data], [False, True])
        self.biwak("bookmark", "remove", todo.pk)
        self.biwak("bookmark", "remove", "--project", self.project.pk)
        self.assertNotIn("Order the tent", self.biwak("bookmarks").output)
        self.assertEqual(self.biwak("bookmark", "add", 999999).exit_code, 1)

    def test_links(self):
        result = self.biwak(
            "link",
            "add",
            self.project.pk,
            "https://figma.com/file/1",
            "--title",
            "Design",
            "--json",
        )
        link = json.loads(result.stdout)
        self.assertEqual(link["kind"], "figma")
        self.biwak(
            "link",
            "add",
            self.project.pk,
            "https://github.com/example/repo",
            "--clients",
        )
        output = self.biwak("links", self.project.pk).output
        self.assertIn("Design", output)
        self.assertIn("figma", output)
        self.assertIn("github", output)
        self.assertEqual(
            len(json.loads(self.biwak("links", self.project.pk, "--json").stdout)), 2
        )
        self.assertIn("Deleted", self.biwak("link", "delete", link["id"]).output)
        self.assertNotIn("Design", self.biwak("links", self.project.pk).output)
        result = self.biwak("link", "add", self.project.pk, "javascript:alert(1)")
        self.assertEqual(result.exit_code, 1)
        result = self.biwak(
            "link", "add", self.project.pk, "https://example.org/", access="read"
        )
        self.assertEqual(result.exit_code, 1)
