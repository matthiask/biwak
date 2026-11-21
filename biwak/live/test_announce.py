"""The order of what ``record()`` sends after the commit"""

from unittest import mock

from django.test import TestCase

from biwak.collab import live as collab
from biwak.items import operations as ops
from biwak.live import announce
from biwak.test_utils import person, project


class OrderTest(TestCase):
    def test_access_is_checked_before_the_pages_are_told(self):
        """A page losing access closes before it hears of the change (the
        channel layer keeps the order of one sender's messages)"""
        ada = person("Ada")
        shared = ops.create_list(
            project=project(members=[ada]), title="Shared", creator=ada, visible=True
        )
        sent = []
        with (
            mock.patch.object(
                collab, "_send", lambda group, message: sent.append(message["type"])
            ),
            mock.patch.object(
                announce,
                "_send",
                lambda groups, message: sent.append(message["type"]),
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            ops.set_visibility(shared, visible=False, actor=ada)
        self.assertIn("live.changed", sent)
        self.assertLess(sent.index("access.check"), sent.index("live.changed"))
