"""Check-ins and people away or in quiet hours (specs/quiet-hours.md,
decided 2026-11-22): people away aren't asked; summaries wait like other
mails"""

import datetime as dt

from biwak.activity.operations import unsubscribe
from biwak.checkins import operations as ops
from biwak.checkins.models import Answer, HeldSummary, Mode, Occurrence
from biwak.checkins.support import CheckinTestCase
from biwak.items import operations as items_ops


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

    def test_away_on_the_occurrences_date_not_the_runs(self):
        """Asked after midnight for the day before (a late run): away is
        judged by the occurrence's date (specs/checkins.md)"""
        self.item.question.time_of_day = dt.time(23, 30)
        self.item.question.save()
        self.bob.away_until = dt.date(2027, 3, 22)
        self.bob.save()
        self.run_at("2027-03-23 00:10")
        occurrence = Occurrence.objects.get()
        self.assertEqual(occurrence.date, dt.date(2027, 3, 22))
        self.assertEqual(list(occurrence.asked.all()), [self.ada])
        self.assertEqual(self.recipients(), [self.ada.email])

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


class HeldSummaryCheckedWhenSentTest(CheckinTestCase):
    """What waited is checked again when it goes, like ``summarize_due()``
    (decided 2026-11-28)"""

    def setUp(self):
        super().setUp()
        self.run_at("2027-03-22 09:00")
        self.sent()
        ops.answer(self.item, user=self.ada, content="Fine")
        self.bob.away_until = dt.date(2027, 3, 24)
        self.bob.save()
        self.run_at("2027-03-23 07:00")
        self.assertTrue(HeldSummary.objects.filter(user=self.bob).exists())
        self.sent()

    def back(self):
        self.run_at("2027-03-25 00:00")
        self.assertFalse(HeldSummary.objects.exists())
        return self.recipients()

    def test_sent(self):
        self.assertEqual(self.back(), [self.bob.email])

    def test_no_mails_chosen_meanwhile(self):
        ops.set_mail_mode(self.item, user=self.bob, mode=Mode.NONE)
        self.assertEqual(self.back(), [])

    def test_unsubscribed_meanwhile(self):
        unsubscribe(self.bob, self.item)
        self.assertEqual(self.back(), [])

    def test_every_answer_trashed_meanwhile(self):
        items_ops.trash(Answer.objects.get().item, actor=self.ada)
        self.assertEqual(self.back(), [])
