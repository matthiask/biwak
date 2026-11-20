import datetime as dt

from biwak.checkins import operations as ops
from biwak.checkins.models import Occurrence, Question
from biwak.checkins.support import CheckinTestCase, at
from biwak.items import operations as item_ops
from biwak.items.models import Item
from biwak.projects import operations as project_ops
from biwak.test_utils import person


class ReminderTest(CheckinTestCase):
    """Asked on Monday 22 March 2027 at 09:00, reminded after 24 hours"""

    def setUp(self):
        super().setUp()
        self.run_at("2027-03-22 09:00")
        self.sent()
        self.occurrence = Occurrence.objects.get()

    def remind(self, text="2027-03-23 09:00"):
        return self.run_at(text)["reminded"]

    def test_those_who_havent_answered_get_one_reminder(self):
        ops.answer(self.item, user=self.ada, content="Fine")
        self.assertEqual(self.remind(), 1)
        message = self.reminders()[0]
        self.assertEqual(message.to, [self.bob.email])
        self.assertEqual(message.subject, "Reminder: [Website] How are you?")
        self.assertIn("A reminder", message.body)
        self.assertIn(f"?occurrence={self.occurrence.pk}", message.body)
        self.assertEqual(
            message.extra_headers["In-Reply-To"],
            f"<question-{self.item.pk}-{self.occurrence.pk}-{self.bob.pk}@biwak.example.org>",
        )
        self.occurrence.refresh_from_db()
        self.assertEqual(self.occurrence.reminded_at, at("2027-03-23 09:00"))

    def test_not_before_the_hours_have_passed(self):
        self.assertEqual(self.remind("2027-03-23 08:59"), 0)
        self.assertEqual(self.reminders(), [])
        self.assertEqual(self.remind("2027-03-23 09:00"), 1)
        self.assertEqual(len(self.reminders()), 2)

    def test_only_once(self):
        self.remind()
        self.reminders()
        for text in ["2027-03-23 09:01", "2027-03-23 15:00", "2027-03-24 08:00"]:
            self.assertEqual(self.remind(text), 0)
        self.assertEqual(self.reminders(), [])

    def test_not_those_who_skipped(self):
        ops.skip(self.item, user=self.bob)
        self.remind()
        self.assertEqual([m.to for m in self.reminders()], [[self.ada.email]])

    def test_not_those_who_answered_or_skipped(self):
        ops.answer(self.item, user=self.ada, content="Fine")
        ops.skip(self.item, user=self.bob)
        self.assertEqual(self.remind(), 1, "the reminder is used up")
        self.assertEqual(self.reminders(), [])
        self.occurrence.refresh_from_db()
        self.assertIsNotNone(self.occurrence.reminded_at)

    def test_a_trashed_answer_doesnt_count(self):
        answer = ops.answer(self.item, user=self.ada, content="Fine")
        item_ops.trash(answer, actor=self.ada)
        self.remind()
        self.assertEqual(
            sorted(m.to[0] for m in self.reminders()), [self.ada.email, self.bob.email]
        )

    def test_no_reminder_without_remind_after(self):
        ops.update_question(self.item, actor=self.ada, remind_after=None)
        self.assertEqual(self.remind("2027-03-25 09:00"), 0)
        self.assertEqual(self.reminders(), [])

    def test_remind_after_is_read_when_the_time_comes(self):
        ops.update_question(self.item, actor=self.ada, remind_after=2)
        self.assertEqual(self.remind("2027-03-22 10:59"), 0)
        self.assertEqual(self.remind("2027-03-22 11:00"), 1)

    def test_people_removed_since_arent_reminded(self):
        ops.set_people(self.item, [self.ada], actor=self.ada)
        self.remind()
        self.assertEqual([m.to for m in self.reminders()], [[self.ada.email]])

    def test_people_added_since_werent_asked_so_arent_reminded(self):
        dora = person("Dora")
        project_ops.add_member(self.project, dora, actor=self.ada)
        ops.set_people(self.item, [self.ada, self.bob, dora], actor=self.ada)
        self.remind()
        self.assertNotIn(dora.email, [m.to[0] for m in self.reminders()])

    def test_inactive_people_arent_reminded(self):
        self.bob.is_active = False
        self.bob.save()
        self.remind()
        self.assertEqual([m.to for m in self.reminders()], [[self.ada.email]])

    def test_a_client_who_cant_see_the_question_any_more(self):
        visible = self.question("Shared", visible=True, people=[self.cleo])
        self.run_at("2027-03-22 09:00")  # asked: the other already was
        self.reminders()
        Occurrence.objects.filter(question__item=visible).update(
            asked_at=at("2027-03-22 09:00")
        )
        item_ops.set_visibility(
            Item.objects.get(pk=visible.pk), visible=False, actor=self.ada
        )
        self.remind()
        self.assertNotIn(self.cleo.email, [m.to[0] for m in self.reminders()])

    def test_a_client_on_a_visible_question_is_reminded(self):
        visible = self.question("Shared", visible=True, people=[self.cleo])
        self.run_at("2027-03-29 09:00")
        self.reminders()
        self.assertEqual(self.remind("2027-03-30 09:00"), 2)
        self.assertIn(self.cleo.email, [m.to[0] for m in self.reminders()])
        self.assertTrue(visible.is_client_visible)

    def test_not_when_the_next_occurrence_has_been_asked(self):
        """A daily question reminded after 24 hours is asked again first"""
        daily = self.question(
            "Daily", rule="FREQ=DAILY", starts_on=dt.date(2027, 3, 1),
            now=at("2027-03-22 10:00"),
        )  # fmt: skip
        self.run_at("2027-03-23 09:00")
        self.sent()
        # Its reminder is due on the 24th, at the moment the next occurrence
        # is asked: the 23rd is history by then
        self.run_at("2027-03-24 09:00")
        self.assertEqual(Occurrence.objects.filter(question__item=daily).count(), 2)
        self.assertFalse(
            Occurrence.objects.filter(
                question__item=daily, reminded_at__isnull=False
            ).exists()
        )
        # A reminder after 12 hours does come in time
        ops.update_question(daily, actor=self.ada, remind_after=12)
        self.assertEqual(self.run_at("2027-03-24 21:00")["reminded"], 1)

    def test_not_while_paused_and_not_late_after_resuming(self):
        ops.pause(self.item, actor=self.ada)
        self.assertEqual(self.remind("2027-03-23 09:00"), 0)
        ops.resume(self.item, actor=self.ada, now=at("2027-03-25 09:00"))
        # Next minute: the reminder came due while paused, it's dropped
        self.assertEqual(self.remind("2027-03-25 09:01"), 0)
        self.assertEqual(self.reminders(), [])
        self.occurrence.refresh_from_db()
        self.assertIsNotNone(self.occurrence.reminded_at)

    def test_not_for_trashed_questions_nor_when_restored_late(self):
        item_ops.trash(self.item, actor=self.ada)
        self.assertEqual(self.remind(), 0)
        item_ops.restore(Item.objects.get(pk=self.item.pk), actor=self.ada)
        self.assertEqual(self.remind("2027-03-23 09:05"), 0)
        self.assertEqual(self.reminders(), [])

    def test_not_for_archived_projects(self):
        project_ops.archive_project(self.project, actor=self.ada)
        self.assertEqual(self.remind(), 0)
        self.assertEqual(self.reminders(), [])

    def test_late_runs_still_remind(self):
        """cron was down: the next run sends it"""
        self.assertEqual(self.remind("2027-03-23 13:00"), 1)
        self.assertEqual(len(self.reminders()), 2)


class ReminderAcrossDaylightSavingTimeTest(CheckinTestCase):
    def test_hours_are_hours_not_wall_clock_time(self):
        """Asked Saturday 27 March 09:00 CET (08:00 UTC): 24 hours later is
        Sunday 10:00 CEST, not 09:00"""
        item = self.question(
            "Saturdays", rule="FREQ=WEEKLY;BYDAY=SA", starts_on=dt.date(2027, 3, 20),
            now=at("2027-03-26 12:00"),
        )  # fmt: skip
        ops.pause(self.item, actor=self.ada)
        self.run_at("2027-03-27 09:00")
        self.sent()
        self.assertEqual(self.run_at("2027-03-28 09:59")["reminded"], 0)
        self.assertEqual(self.run_at("2027-03-28 10:00")["reminded"], 1)
        self.assertEqual(len(self.reminders()), 2)
        self.assertEqual(Question.objects.get(item=item).remind_after, 24)
