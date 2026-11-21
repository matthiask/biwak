import io
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase


class FairyTasksTest(TestCase):
    def test_one_failing_task_stops_no_other(self):
        with (
            patch(
                "biwak.management.commands.fairy_tasks.purge_trash",
                side_effect=RuntimeError,
            ),
            patch("biwak.management.commands.fairy_tasks.recompute_activity") as later,
            self.assertLogs("biwak.management.commands.fairy_tasks", "ERROR"),
        ):
            call_command("fairy_tasks", stdout=io.StringIO())
        later.assert_called_once()
