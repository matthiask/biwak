"""The ``biwak projects`` command of projects-overview.md"""

import json

from biwak import test_cli
from biwak.bookmarks import operations as bookmarks
from biwak.projects.models import Membership
from biwak.test_utils import project


class ProjectsCLITest(test_cli.CLITest):
    def setUp(self):
        super().setUp()
        self.zebra = project("Zebra", members=[self.ada])
        Membership.objects.get_or_create(project=self.zebra, user=self.ada)

    def names(self, *args):
        return [
            p["name"]
            for p in json.loads(self.biwak("projects", "--json", *args).stdout)
        ]

    def test_favorites_marked_and_first(self):
        self.assertEqual(self.names("--order", "name"), ["Website", "Zebra"])
        bookmarks.add_bookmark(self.ada, project=self.zebra)
        self.assertEqual(self.names("--order", "name"), ["Zebra", "Website"])
        output = self.biwak("projects", "--order", "name").output
        lines = [line for line in output.splitlines() if "Zebra" in line]
        self.assertTrue(lines[0].lstrip().startswith("*"))
        website = [line for line in output.splitlines() if "Website" in line]
        self.assertFalse(website[0].lstrip().startswith("*"))

    def test_order_and_last_activity(self):
        data = json.loads(self.biwak("projects", "--json").stdout)
        self.assertTrue(all("last_activity_at" in p for p in data))
        self.assertTrue(all("is_bookmarked" in p for p in data))
        # The CLI test case's project has events, Zebra none: it comes last
        self.assertEqual(self.names("--order", "activity"), ["Website", "Zebra"])
        self.assertIn("20", self.biwak("projects").output)
        self.assertEqual(self.biwak("projects", "--order", "x").exit_code, 2)
