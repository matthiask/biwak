"""Mails waiting for the working time or the return (specs/quiet-hours.md),
with frozen time in the installation's time zone (Europe/Zurich), the days
the clocks change included"""

import datetime as dt

import time_machine
from django.core import mail

from biwak.accounts.models import MailDelivery
from biwak.activity import lantern, mentions
from biwak.activity.mails import send_mails
from biwak.activity.models import Notification
from biwak.activity.operations import subscribe
from biwak.activity.test_mails import ZURICH, MailsBase
from biwak.checkins import operations as checkins
from biwak.checkins.support import MONDAY_9
from biwak.items import operations as ops


def at(text):
    """A moment from the wall clock time in Zurich"""
    return dt.datetime.fromisoformat(text).replace(tzinfo=ZURICH)


# Friday 20 November 2026, a working day; the 21st and 22nd are the weekend
FRIDAY_EVENING = "2026-11-20 18:30"
MONDAY = "2026-11-23"


class QuietBase(MailsBase):
    def setUp(self):
        super().setUp()
        self.other = ops.create_todo(
            todolist=self.internal, title="Pack", creator=self.ada
        )
        subscribe(self.bob, self.other)
        self.bob.quiet_hours = True
        self.bob.save()

    def comment(self, when, item=None, content="Hi"):
        with time_machine.travel(at(when), tick=False):
            self.act(
                lambda: ops.add_comment(
                    item or self.todo, author=self.ada, content=content
                )
            )

    def send(self, when):
        return self.send_at(at(when))

    def send_at(self, moment):
        with (
            time_machine.travel(moment, tick=False),
            self.captureOnCommitCallbacks(execute=True),
        ):
            return send_mails(now=moment)

    def to_bob(self):
        messages = [m for m in mail.outbox if m.to == [self.bob.email]]
        mail.outbox.clear()
        return messages


class QuietHoursTest(QuietBase):
    def test_off_by_default(self):
        self.assertFalse(self.ada.quiet_hours)
        self.assertEqual(self.ada.working_days, [0, 1, 2, 3, 4])
        self.assertEqual(
            (self.ada.working_from, self.ada.working_until),
            (dt.time(8), dt.time(18)),
        )

    def test_waiting_changes_go_as_one_mail_at_the_next_working_time(self):
        self.comment(FRIDAY_EVENING, content="One")
        self.comment(FRIDAY_EVENING, self.other, content="Two")
        for when in [
            "2026-11-20 18:45",
            "2026-11-21 10:00",
            "2026-11-22 12:00",
            f"{MONDAY} 07:59",
        ]:
            self.send(when)
            self.assertEqual(self.to_bob(), [], when)
        # The lantern has them meanwhile
        self.assertEqual(lantern.unread_count(self.bob), 2)
        self.assertEqual(
            Notification.objects.filter(user=self.bob, held_at__isnull=False).count(),
            2,
        )
        self.send(f"{MONDAY} 08:00")
        (message,) = self.to_bob()
        # The digest's form: everything, grouped by project
        self.assertEqual(message.subject, "[Biwak] What happened on 20 November 2026")
        self.assertIn("== Website ==", message.body)
        self.assertIn("One", message.body)
        self.assertIn("Two", message.body)
        self.assertFalse(
            Notification.objects.filter(user=self.bob, sent_at__isnull=True).exists()
        )
        self.send(f"{MONDAY} 08:30")
        self.assertEqual(self.to_bob(), [])

    def test_one_waiting_goes_as_usual(self):
        self.comment(FRIDAY_EVENING, content="One")
        self.comment("2026-11-21 09:00", content="Two")
        self.send("2026-11-21 10:00")
        self.send(f"{MONDAY} 08:00")
        (message,) = self.to_bob()
        self.assertEqual(message.subject, "[Website] Order the tent")
        self.assertIn("One", message.body)
        self.assertIn("Two", message.body)

    def test_mails_as_usual_in_the_working_time(self):
        self.comment(f"{MONDAY} 09:00")
        self.send(f"{MONDAY} 09:05")
        self.assertEqual(self.to_bob(), [])
        self.send(f"{MONDAY} 09:10")
        (message,) = self.to_bob()
        self.assertEqual(message.subject, "[Website] Order the tent")

    def test_a_change_late_in_the_working_time_waits(self):
        """Not due before the working time ends: it waits for the next"""
        self.comment(f"{MONDAY} 17:55")
        self.send(f"{MONDAY} 18:00")
        self.send(f"{MONDAY} 18:10")
        self.assertEqual(self.to_bob(), [])
        self.send("2026-11-24 08:00")
        self.assertEqual(len(self.to_bob()), 1)

    def test_others_get_theirs(self):
        """Quiet hours are per person"""
        self.comment(FRIDAY_EVENING)
        with time_machine.travel(at(FRIDAY_EVENING), tick=False):
            self.act(lambda: ops.add_comment(self.todo, author=self.bob, content="Hey"))
        self.send("2026-11-20 18:45")
        self.assertEqual([m.to for m in mail.outbox], [[self.ada.email]])

    def test_mentions_wait_too(self):
        """Nothing bypasses (decided 2026-11-22)"""
        with time_machine.travel(at(FRIDAY_EVENING), tick=False):
            self.act(
                lambda: ops.add_comment(
                    self.other,
                    author=self.ada,
                    content=f"Look, {mentions.syntax(self.bob)}",
                )
            )
        self.send("2026-11-20 19:00")
        self.assertEqual(self.to_bob(), [])
        self.send(f"{MONDAY} 08:00")
        self.assertEqual(len(self.to_bob()), 1)

    def test_read_meanwhile_isnt_mailed(self):
        self.comment(FRIDAY_EVENING)
        self.send("2026-11-20 19:00")
        lantern.read(self.bob, item=self.todo)
        self.send(f"{MONDAY} 08:00")
        self.assertEqual(self.to_bob(), [])
        # Kept for the lantern
        self.assertTrue(Notification.objects.filter(user=self.bob).exists())

    def test_turning_them_off_sends_what_waited(self):
        self.comment(FRIDAY_EVENING)
        self.comment(FRIDAY_EVENING, self.other)
        self.send("2026-11-20 19:00")
        self.bob.quiet_hours = False
        self.bob.save()
        self.send("2026-11-21 10:00")
        self.assertEqual(len(self.to_bob()), 1)

    def test_no_mails_keeps_them(self):
        """Switching to no mails while they wait: nothing lost, they go
        when mails are switched on again"""
        self.comment(FRIDAY_EVENING)
        self.send("2026-11-20 19:00")
        self.bob.mail_delivery = MailDelivery.NONE
        self.bob.save()
        self.send(f"{MONDAY} 08:00")
        self.assertEqual(self.to_bob(), [])
        self.bob.mail_delivery = MailDelivery.EACH
        self.bob.save()
        self.send(f"{MONDAY} 08:01")
        self.assertEqual(len(self.to_bob()), 1)

    def test_working_days(self):
        self.bob.working_days = [5]  # Saturdays only
        self.bob.save()
        self.comment(f"{MONDAY} 09:00")
        for when in [f"{MONDAY} 10:00", "2026-11-27 12:00", "2026-11-28 07:59"]:
            self.send(when)
            self.assertEqual(self.to_bob(), [], when)
        self.send("2026-11-28 08:00")
        self.assertEqual(len(self.to_bob()), 1)

    def test_the_days_the_clocks_change(self):
        """08:00 is the wall clock's in the installation's time zone: an
        hour apart in UTC before and after the change"""
        self.bob.working_days = list(range(7))
        self.bob.save()
        utc = dt.UTC
        for night, before, after in [
            # Summer time from Sunday 29 March 2026, 02:00
            (
                "2026-03-28 20:00",
                dt.datetime(2026, 3, 29, 5, 59, tzinfo=utc),
                dt.datetime(2026, 3, 29, 6, 0, tzinfo=utc),
            ),
            # Winter time from Sunday 25 October 2026, 03:00
            (
                "2026-10-24 20:00",
                dt.datetime(2026, 10, 25, 6, 59, tzinfo=utc),
                dt.datetime(2026, 10, 25, 7, 0, tzinfo=utc),
            ),
        ]:
            self.comment(night)
            self.comment(night, self.other)
            for moment in [before, after]:
                self.send_at(moment)
                self.assertEqual(
                    len(self.to_bob()), 0 if moment == before else 1, moment
                )

    def test_the_end_of_the_working_time_on_the_days_the_clocks_change(self):
        self.bob.working_days = list(range(7))
        self.bob.save()
        utc = dt.UTC
        # 18:00 in Zurich: 16:00 UTC in summer, 17:00 in winter
        for day, last, first_quiet in [
            ("2026-03-29", (15, 59), (16, 0)),
            ("2026-10-25", (16, 59), (17, 0)),
        ]:
            date = dt.date.fromisoformat(day)
            self.comment(f"{day} 17:40")
            moment = dt.datetime.combine(date, dt.time(*last), tzinfo=utc)
            self.send_at(moment)
            self.assertEqual(len(self.to_bob()), 1, day)
            self.comment(f"{day} 17:45")
            moment = dt.datetime.combine(date, dt.time(*first_quiet), tzinfo=utc)
            self.send_at(moment)
            self.assertEqual(self.to_bob(), [], day)
            # Waiting for the next day
            self.assertTrue(
                Notification.objects.filter(user=self.bob, held_at__isnull=False)
            )
            Notification.objects.filter(user=self.bob).delete()


class QuietDigestTest(QuietBase):
    """Delivery "daily digest" with quiet hours: at the start of the first
    working time of the day instead of 07:00"""

    def setUp(self):
        super().setUp()
        self.bob.mail_delivery = MailDelivery.DIGEST
        self.bob.working_from = dt.time(9, 30)
        self.bob.save()

    def test_at_the_start_of_the_working_time(self):
        self.comment("2026-11-19 14:00", content="One")
        self.send("2026-11-20 07:00")
        self.send("2026-11-20 09:29")
        self.assertEqual(self.to_bob(), [])
        self.send("2026-11-20 09:30")
        (message,) = self.to_bob()
        self.assertEqual(message.subject, "[Biwak] What happened on 19 November 2026")
        self.assertIn("One", message.body)

    def test_not_on_other_days(self):
        """Not at the weekend: Monday's covers it"""
        self.comment("2026-11-20 14:00", content="Friday")
        self.comment("2026-11-21 14:00", content="Saturday")
        self.send("2026-11-21 09:30")
        self.send("2026-11-22 09:30")
        self.assertEqual(self.to_bob(), [])
        self.send(f"{MONDAY} 09:30")
        (message,) = self.to_bob()
        self.assertEqual(
            message.subject,
            "[Biwak] What happened from 20 November 2026 to 21 November 2026",
        )
        self.assertIn("Friday", message.body)
        self.assertIn("Saturday", message.body)

    def test_what_happened_in_the_quiet_time_today_comes_along(self):
        self.comment("2026-11-19 14:00", content="Yesterday")
        self.comment("2026-11-20 07:00", content="Early")
        self.send("2026-11-20 07:01")
        self.comment("2026-11-20 09:00", content="Before nine thirty")
        self.send("2026-11-20 09:10")
        self.send("2026-11-20 09:30")
        (message,) = self.to_bob()
        self.assertIn("Yesterday", message.body)
        self.assertIn("Early", message.body)
        self.assertIn("Before nine thirty", message.body)
        # What happens in the working time: tomorrow's
        self.comment("2026-11-20 10:00", content="Later")
        self.send("2026-11-20 10:30")
        self.assertEqual(self.to_bob(), [])

    def test_the_days_the_clocks_change(self):
        self.bob.working_days = list(range(7))
        self.bob.save()
        self.comment("2026-03-28 14:00")
        # 09:30 in summer time is 07:30 UTC
        for moment, count in [
            (dt.datetime(2026, 3, 29, 7, 29, tzinfo=dt.UTC), 0),
            (dt.datetime(2026, 3, 29, 7, 30, tzinfo=dt.UTC), 1),
        ]:
            self.send_at(moment)
            self.assertEqual(len(self.to_bob()), count, moment)


class AwayTest(QuietBase):
    """Away until Wednesday 25 November 2026"""

    def setUp(self):
        super().setUp()
        self.bob.quiet_hours = False
        self.bob.away_until = dt.date(2026, 11, 25)
        self.bob.away_note = "Back on Thursday"
        self.bob.save()

    def test_held_while_away_one_digest_on_return(self):
        self.comment(f"{MONDAY} 09:00", content="One")
        self.comment("2026-11-25 23:00", self.other, content="Two")
        for when in [f"{MONDAY} 09:30", "2026-11-25 12:00", "2026-11-25 23:59"]:
            self.send(when)
            self.assertEqual(self.to_bob(), [], when)
        self.send("2026-11-26 00:00")
        (message,) = self.to_bob()
        self.assertEqual(
            message.subject,
            "[Biwak] What happened from 23 November 2026 to 25 November 2026",
        )
        self.assertIn("One", message.body)
        self.assertIn("Two", message.body)

    def test_respecting_quiet_hours(self):
        self.bob.quiet_hours = True
        self.bob.save()
        self.comment(f"{MONDAY} 09:00")
        self.comment(f"{MONDAY} 09:00", self.other)
        self.send("2026-11-26 00:00")
        self.send("2026-11-26 07:59")
        self.assertEqual(self.to_bob(), [])
        self.send("2026-11-26 08:00")
        self.assertEqual(len(self.to_bob()), 1)

    def test_digests_wait_too(self):
        self.bob.mail_delivery = MailDelivery.DIGEST
        self.bob.save()
        self.comment(f"{MONDAY} 09:00", content="One")
        self.send("2026-11-24 07:00")
        self.send("2026-11-25 07:00")
        self.assertEqual(self.to_bob(), [])
        self.send("2026-11-26 07:00")
        (message,) = self.to_bob()
        self.assertIn("One", message.body)

    def test_back_early(self):
        """ "I'm back" ends it: what waited goes as one mail"""
        self.comment(f"{MONDAY} 09:00")
        self.comment(f"{MONDAY} 09:00", self.other)
        self.send(f"{MONDAY} 10:00")
        self.bob.away_until = None
        self.bob.save()
        self.send(f"{MONDAY} 10:01")
        (message,) = self.to_bob()
        self.assertTrue(message.subject.startswith("[Biwak] What happened"))

    def test_questions_arent_held_by_quiet_hours(self):
        """Check-in questions are asked at their own time; people away
        aren't asked at all (biwak/checkins/test_quiet_hours.py)"""
        with time_machine.travel(at("2027-03-19 12:00"), tick=False):
            checkins.create_question(
                project=self.project,
                title="How are you?",
                creator=self.ada,
                people=[self.bob],
                now=at("2027-03-19 12:00"),
                **MONDAY_9,
            )
        self.bob.away_until = None
        self.bob.quiet_hours = True
        self.bob.working_from = dt.time(10)
        self.bob.save()
        with (
            time_machine.travel(at("2027-03-22 09:00"), tick=False),
            self.captureOnCommitCallbacks(execute=True),
        ):
            checkins.run(now=at("2027-03-22 09:00"))
        (message,) = self.to_bob()
        self.assertEqual(message.subject, "[Website] How are you?")

    def test_away_ends_by_itself(self):
        with time_machine.travel(at("2026-11-25 23:59"), tick=False):
            self.assertTrue(self.bob.is_away)
        with time_machine.travel(at("2026-11-26 00:00"), tick=False):
            self.assertFalse(self.bob.is_away)
            self.assertEqual(self.bob.away_text, "")
