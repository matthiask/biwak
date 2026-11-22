"""``biwak share``, ``biwak unshare`` and ``biwak public-links``
(specs/public-links.md); the CLI test case is the one of test_cli.py"""

import json

from biwak import test_cli
from biwak.items import operations as ops
from biwak.public_links.models import PublicLink


class PublicLinksCLITest(test_cli.CLITest):
    def test_share_list_unshare(self):
        todo = ops.create_todo(todolist=self.list, title="Tent", creator=self.ada)
        result = self.biwak("share", todo.pk, "--days", "3")
        self.assertEqual(result.exit_code, 0, result.output)
        link = PublicLink.objects.get()
        self.assertIn(f"#{todo.pk} Tent [clients]", result.output)
        self.assertIn(f"/p/{link.token}/", result.output)
        # Replacing it
        data = json.loads(self.biwak("share", todo.pk, "--json").stdout)
        self.assertNotEqual(PublicLink.objects.get().token, link.token)
        listed = self.biwak("public-links").output
        self.assertIn(data["url"], listed)
        self.assertIn("Tent", listed)
        result = self.biwak("unshare", todo.pk)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Stopped sharing", result.output)
        self.assertFalse(PublicLink.objects.exists())
        self.assertEqual(json.loads(self.biwak("public-links", "--json").stdout), [])

    def test_only_the_days_offered(self):
        todo = ops.create_todo(todolist=self.list, title="Tent", creator=self.ada)
        result = self.biwak("share", todo.pk, "--days", "14")
        self.assertNotEqual(result.exit_code, 0)
        self.assertFalse(PublicLink.objects.exists())

    def test_not_lists(self):
        result = self.biwak("share", self.list.pk)
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("can be shared", result.output)
