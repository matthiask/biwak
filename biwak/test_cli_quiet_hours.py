"""``biwak notifications`` with quiet hours and ``biwak away``
(specs/quiet-hours.md)"""

import datetime as dt
import json
import zoneinfo

import time_machine

from biwak import test_cli
from biwak.accounts.models import User
from biwak.test_utils import person


NOW = dt.datetime(2026, 11, 23, 10, 0, tzinfo=zoneinfo.ZoneInfo("Europe/Zurich"))


class QuietHoursCLITest(test_cli.CLITest):
    def setUp(self):
        traveller = time_machine.travel(NOW, tick=False)
        traveller.start()
        self.addCleanup(traveller.stop)
        super().setUp()

    def refresh(self, user):
        user.refresh_from_db()
        return user

    def test_quiet_hours(self):
        self.assertIn("Quiet hours: off", self.biwak("notifications").output)
        output = self.biwak(
            "notifications",
            "--quiet-hours",
            "on",
            "--working-days",
            "mon-wed,fri",
            "--from",
            "07:30",
            "--until",
            "16:00",
        ).output
        self.assertIn(
            "Quiet hours: on, mails go mon,tue,wed,fri 07:30-16:00 (Europe/Zurich)",
            output,
        )
        ada = self.refresh(self.ada)
        self.assertEqual(
            (ada.quiet_hours, ada.working_days, ada.working_from, ada.working_until),
            (True, [0, 1, 2, 4], dt.time(7, 30), dt.time(16)),
        )
        data = json.loads(self.biwak("notifications", "--json").stdout)
        self.assertEqual(data["working_days"], [0, 1, 2, 4])
        self.biwak("notifications", "--quiet-hours", "off")
        self.assertFalse(self.refresh(self.ada).quiet_hours)

    def test_mistakes(self):
        result = self.biwak("notifications", "--working-days", "fri-mon")
        self.assertEqual(result.exit_code, 2)
        result = self.biwak("notifications", "--from", "19:00")
        self.assertEqual(result.exit_code, 1)
        self.assertIn("The working hours end after they start.", result.output)
        result = self.biwak("notifications", "--project", 1, "--quiet-hours", "on")
        self.assertEqual(result.exit_code, 1)

    def test_away(self):
        self.assertIn("Ada Example isn't away.", self.biwak("away").output)
        output = self.biwak(
            "away", "--until", "2026-12-03", "--note", "Ask Bob meanwhile"
        ).output
        self.assertIn("Ada Example is away until 2026-12-03: Ask Bob meanwhile", output)
        self.assertTrue(self.refresh(self.ada).is_away)
        data = json.loads(self.biwak("away", "--json").stdout)
        self.assertEqual(data["away_until"], "2026-12-03")
        self.biwak("away", "--back")
        self.assertFalse(self.refresh(self.ada).is_away)
        result = self.biwak("away", "--until", "2026-11-01")
        self.assertEqual(result.exit_code, 1)
        self.assertIn("Choose today or a later day.", result.output)

    def test_others_are_for_admins(self):
        bob = person("Bob")
        result = self.biwak("away", "--person", bob.pk, "--until", "2026-12-01")
        self.assertEqual(result.exit_code, 1)
        User.objects.filter(pk=self.ada.pk).update(is_admin=True)
        output = self.biwak("away", "--person", bob.pk, "--until", "2026-12-01").output
        self.assertIn("Bob Example is away until 2026-12-01", output)
        self.biwak("away", "--person", bob.pk, "--back")
        self.assertFalse(self.refresh(bob).is_away)

    def test_people_say_it(self):
        self.ada.away_until = dt.date(2026, 12, 3)
        self.ada.save()
        self.assertIn(
            "Ada Example (away until 2026-12-03)",
            self.biwak("members", "--project", self.project.pk).output,
        )
        self.assertIn(
            "Ada Example (away until 2026-12-03)", self.biwak("people").output
        )

    def test_away_assignees(self):
        """``todos list``, ``show`` and ``assign`` say who is away, ``show``
        and ``assign`` with the note; not on a completed to-do"""
        from biwak.accounts.operations import set_away
        from biwak.items import operations as ops
        from biwak.projects.models import Membership

        bob = person("Bob")
        Membership.objects.create(project=self.project, user=bob)
        set_away(bob, until=dt.date(2026, 12, 3), note="Ask Ada", actor=bob)
        todo = ops.create_todo(
            todolist=self.list, title="Order the tent", creator=self.ada
        )
        output = self.biwak("todos", "assign", todo.pk, "--to", bob.pk).output
        self.assertIn("Bob (away until 2026-12-03: Ask Ada)", output)
        output = self.biwak("todos", "--list", self.list.pk).output
        self.assertIn("Bob (away until 2026-12-03)", output)
        output = self.biwak("todos", "show", todo.pk).output
        self.assertIn("Assignees: Bob (away until 2026-12-03: Ask Ada)", output)
        ops.complete(todo, actor=self.ada)
        output = self.biwak("todos", "show", todo.pk).output
        self.assertIn("Assignees: Bob\n", output)
