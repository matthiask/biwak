"""The data migration putting a doc's title in front of its text
(specs/doc-titles.md)"""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from biwak.items.models import Doc
from biwak.test_utils import bare_doc, person, project


class DocTitleMigrationTest(TransactionTestCase):
    before = [("items", "0011_archived_lists_only")]

    def test_docs_get_their_title_as_a_heading_unless_it_is_the_first_line(self):
        ada = person("Ada")
        p = project(members=[ada])
        rows = {}
        for title, content in [
            ("Notes", "Body"),
            ("Plan", "# Plan\n\nAlready"),
            ("Meeting", "Meeting\nplain first line"),
            ("Empty", ""),
            ("Other", "# Something else\n\ntext"),
        ]:
            rows[title] = bare_doc(project=p, title=title, content=content, creator=ada)
        executor = MigrationExecutor(connection)
        executor.migrate(self.before)
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        self.assertEqual(
            {title: Doc.objects.get(item=item).content for title, item in rows.items()},
            {
                "Notes": "# Notes\n\nBody",
                "Plan": "# Plan\n\nAlready",
                "Meeting": "Meeting\nplain first line",
                "Empty": "# Empty\n\n",
                "Other": "# Other\n\n# Something else\n\ntext",
            },
        )
        # Versions stay as they are
        self.assertEqual(rows["Notes"].doc.versions.get().content, "Body")
        # A second run changes nothing more
        executor = MigrationExecutor(connection)
        executor.migrate(self.before)
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        self.assertEqual(Doc.objects.get(item=rows["Notes"]).content, "# Notes\n\nBody")
