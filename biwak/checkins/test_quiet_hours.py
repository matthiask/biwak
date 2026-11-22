"""Check-ins and people away or in quiet hours (specs/quiet-hours.md,
decided 2026-11-22): people away aren't asked; summaries wait like other
mails"""

import datetime as dt

from biwak.checkins import operations as ops
from biwak.checkins.models import HeldSummary, Occurrence
from biwak.checkins.support import CheckinTestCase


class AwayAskingTest(CheckinTestCase):
    def test_people_away_arent_asked(self):
        self.bob.away_until = dt.date(2027, 3, 22)
        self.bob.save()
        self.run_at("2027-03-22 09:00")
        occurrence = Occurrence.objects.get()
        self.assertEqual(list(occurrence.asked.all()), [self.ada])
        self.assertEqual(self.recipients(), [self.ada.email])
        # Not missing either
        self.assertEqual(ops.missing(occurrence), [self.ada])
        # Back the next week: asked again
        self.run_at("2027-03-29 09:00")
        self.assertEqual(self.recipients(), [self.ada.email, self.bob.email])

    def test_quiet_hours_dont_keep_questions_back(self):
        self.bob.quiet_hours = True
        self.bob.working_from = dt.time(10)
        self.bob.save()
        self.run_at("2027-03-22 09:00")
        self.assertEqual(self.recipients(), [self.ada.email, self.bob.email])


class HeldSummaryTest(CheckinTestCase):
    def setUp(self):
        super().setUp()
        self.run_at("2027-03-22 09:00")
        self.sent()
        ops.answer(self.item, user=self.ada, content="Fine")

    def test_waiting_for_the_working_time(self):
        self.bob.quiet_hours = True
        self.bob.working_from = dt.time(10)
        self.bob.save()
        self.run_at("2027-03-23 07:00")
        self.assertEqual(self.recipients(), [self.ada.email])
        self.assertTrue(HeldSummary.objects.filter(user=self.bob).exists())
        self.run_at("2027-03-23 09:59")
        self.assertEqual(self.sent(), [])
        self.run_at("2027-03-23 10:00")
        (message,) = self.sent(self.bob)
        self.assertIn("answers of 22 March 2027", message.subject)
        self.assertFalse(HeldSummary.objects.exists())
        self.run_at("2027-03-23 10:01")
        self.assertEqual(self.sent(), [])

    def test_waiting_while_away(self):
        self.bob.away_until = dt.date(2027, 3, 24)
        self.bob.save()
        self.run_at("2027-03-23 07:00")
        self.assertEqual(self.recipients(), [self.ada.email])
        self.run_at("2027-03-24 23:59")
        self.assertEqual(self.sent(), [])
        self.run_at("2027-03-25 00:00")
        self.assertEqual(self.recipients(), [self.bob.email])
