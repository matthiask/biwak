import datetime as dt

from django.core import mail

from biwak.accounts.models import NotificationLevel
from biwak.activity.models import LevelOverride
from biwak.activity.operations import unsubscribe
from biwak.checkins import operations as ops
from biwak.checkins.models import Mode, Occurrence
from biwak.checkins.support import CheckinTestCase, at
from biwak.items import operations as item_ops
from biwak.items.models import Item
from biwak.test_utils import person


class SummaryTest(CheckinTestCase):
    """Asked on Monday 22 March 2027 at 09:00; the summary goes out on
    Tuesday at 07:00"""

    def setUp(self):
        super().setUp()
        self.run_at("2027-03-22 09:00")
        self.occurrence = Occurrence.objects.get()
        self.sent()

    def summaries(self):
        return [m for m in self.sent() if ": answers of " in m.subject]

    def summarize(self, text="2027-03-23 07:00"):
        return self.run_at(text)["summarized"]

    def test_one_mail_the_morning_after_with_all_answers(self):
        ops.answer(self.item, user=self.ada, content="Busy with the **launch**")
        ops.answer(self.item, user=self.bob, content="Reading a book")
        self.assertEqual(self.summarize("2027-03-23 06:59"), 0)
        self.assertEqual(self.summaries(), [])
        self.assertEqual(self.summarize(), 1)
        messages = self.summaries()
        self.assertEqual(
            sorted(m.to[0] for m in messages), [self.ada.email, self.bob.email]
        )
        message = messages[0]
        self.assertEqual(
            message.subject, "[Website] How are you?: answers of 22. March 2027"
        )
        for text in [
            "Ada Example",
            "Busy with the **launch**",
            "Bob Example",
            "Reading a book",
        ]:
            self.assertIn(text, message.body)
        self.assertIn("<strong>launch</strong>", message.alternatives[0].content)
        self.assertIn(
            f"https://biwak.example.org/questions/{self.item.pk}/", message.body
        )
        self.assertEqual(
            message.extra_headers["In-Reply-To"],
            f"<question-{self.item.pk}-{self.occurrence.pk}-{self.ada.pk}@biwak.example.org>"
            if message.to == [self.ada.email]
            else f"<question-{self.item.pk}-{self.occurrence.pk}-{self.bob.pk}@biwak.example.org>",
        )

    def test_not_for_every_answer(self):
        ops.answer(self.item, user=self.ada, content="One")
        with self.captureOnCommitCallbacks(execute=True):
            from biwak.activity.mails import send_mails

            send_mails(now=at("2027-03-22 12:00"))
        self.assertEqual(mail.outbox, [], "the default is the summary")

    def test_only_once(self):
        ops.answer(self.item, user=self.ada, content="One")
        self.summarize()
        self.sent()
        ops.answer(self.item, user=self.bob, content="Late")
        self.assertEqual(self.summarize("2027-03-23 07:01"), 0)
        self.assertEqual(self.summarize("2027-03-24 07:00"), 0)
        self.assertEqual(self.summaries(), [])

    def test_none_without_answers(self):
        self.assertEqual(self.summarize(), 1, "done")
        self.assertEqual(self.summaries(), [])
        self.occurrence.refresh_from_db()
        self.assertEqual(self.occurrence.summarized_at, at("2027-03-23 07:00"))
        # Answers coming later don't bring it back
        ops.answer(self.item, user=self.ada, content="Late")
        self.assertEqual(self.summarize("2027-03-23 08:00"), 0)
        self.assertEqual(self.summaries(), [])

    def test_the_mode_of_each_person(self):
        ops.set_mail_mode(self.item, user=self.bob, mode=Mode.EACH)
        ops.set_mail_mode(self.item, user=self.ada, mode=Mode.NONE)
        dora = person("Dora")
        from biwak.projects import operations as project_ops

        project_ops.add_member(self.project, dora, actor=self.ada)
        ops.set_people(self.item, [self.ada, self.bob, dora], actor=self.ada)
        ops.answer(self.item, user=self.ada, content="One")
        self.summarize()
        self.assertEqual([m.to for m in self.summaries()], [[dora.email]])

    def test_not_to_people_who_unsubscribed(self):
        unsubscribe(self.bob, self.item)
        ops.answer(self.item, user=self.ada, content="One")
        self.summarize()
        self.assertEqual([m.to for m in self.summaries()], [[self.ada.email]])

    def test_not_to_people_with_the_level_nothing(self):
        self.bob.notification_level = NotificationLevel.NOTHING
        self.bob.save()
        ops.answer(self.item, user=self.ada, content="One")
        self.summarize()
        self.assertEqual([m.to for m in self.summaries()], [[self.ada.email]])

    def test_not_to_people_with_the_level_nothing_for_the_item(self):
        LevelOverride.objects.create(
            user=self.ada, item=self.item, level=NotificationLevel.NOTHING
        )
        ops.answer(self.item, user=self.ada, content="One")
        self.summarize()
        self.assertEqual([m.to for m in self.summaries()], [[self.bob.email]])

    def test_concerns_me_still_gets_the_summary(self):
        self.bob.notification_level = NotificationLevel.CONCERNS_ME
        self.bob.save()
        ops.answer(self.item, user=self.ada, content="One")
        self.summarize()
        self.assertEqual(len(self.summaries()), 2)

    def test_trashed_answers_arent_in_it(self):
        answer = ops.answer(self.item, user=self.ada, content="Secret")
        ops.answer(self.item, user=self.bob, content="Fine")
        item_ops.trash(answer, actor=self.ada)
        self.summarize()
        for message in self.summaries():
            self.assertNotIn("Secret", message.body)
            self.assertIn("Fine", message.body)

    def test_none_when_all_answers_are_trashed(self):
        answer = ops.answer(self.item, user=self.ada, content="Oops")
        item_ops.trash(answer, actor=self.ada)
        self.assertEqual(self.summarize(), 1)
        self.assertEqual(self.summaries(), [])

    def test_clients_only_on_visible_questions(self):
        visible = self.question("Shared", visible=True, people=[self.ada, self.cleo])
        self.run_at("2027-03-29 09:00")
        self.sent()
        ops.answer(visible, user=self.cleo, content="Hello from the client")
        ops.set_mail_mode(visible, user=self.cleo, mode=Mode.SUMMARY)
        ops.answer(self.item, user=self.ada, content="Internal")
        self.summarize("2027-03-30 07:00")
        by_subject = {}
        for message in self.summaries():
            by_subject.setdefault(message.subject.split(":")[0], []).append(message)
        self.assertEqual(
            sorted(m.to[0] for m in by_subject["[Website] Shared"]),
            sorted([self.ada.email, self.cleo.email]),
        )
        # The client never hears of the internal question
        self.assertNotIn(
            self.cleo.email, [m.to[0] for m in by_subject["[Website] How are you?"]]
        )

    def test_a_client_loses_it_when_the_question_turns_internal(self):
        visible = self.question("Shared", visible=True, people=[self.ada, self.cleo])
        self.run_at("2027-03-29 09:00")
        ops.set_mail_mode(visible, user=self.cleo, mode=Mode.SUMMARY)
        ops.answer(visible, user=self.ada, content="One")
        item_ops.set_visibility(
            Item.objects.get(pk=visible.pk), visible=False, actor=self.ada
        )
        self.sent()
        self.summarize("2027-03-30 07:00")
        self.assertNotIn(self.cleo.email, [m.to[0] for m in self.summaries()])

    def test_visibility_is_checked_again_when_sending(self):
        """The mails go out after the commit: a question turned internal
        in between doesn't reach the client (like ``_deliverable()``)"""
        visible = self.question("Shared", visible=True, people=[self.ada, self.cleo])
        self.run_at("2027-03-29 09:00")
        ops.set_mail_mode(visible, user=self.cleo, mode=Mode.SUMMARY)
        ops.answer(visible, user=self.ada, content="One")
        self.sent()
        with self.captureOnCommitCallbacks() as callbacks:
            ops.run(now=at("2027-03-30 07:00"))
        item_ops.set_visibility(
            Item.objects.get(pk=visible.pk), visible=False, actor=self.ada
        )
        for callback in callbacks:
            callback()
        recipients = [m.to[0] for m in self.summaries()]
        self.assertIn(self.ada.email, recipients)
        self.assertNotIn(self.cleo.email, recipients)

    def test_the_morning_is_in_the_questions_time_zone(self):
        tokyo = self.question(
            "Tokyo", time_zone="Asia/Tokyo", now=at("2027-03-19 12:00")
        )
        utc = dt.UTC
        # Monday 09:00 Tokyo is 00:00 UTC; Tuesday 07:00 Tokyo is Monday 22:00 UTC
        self.run_at("2027-03-22 00:00", utc)
        self.sent()
        ops.answer(tokyo, user=self.ada, content="Konnichiwa")
        self.run_at("2027-03-22 21:59", utc)
        self.assertEqual(self.summaries(), [])
        self.run_at("2027-03-22 22:00", utc)
        self.assertEqual(
            [m.subject for m in self.summaries()],
            ["[Website] Tokyo: answers of 22. March 2027"] * 2,
        )

    def test_across_the_change_to_summer_time(self):
        item = self.question(
            "Saturdays", rule="FREQ=WEEKLY;BYDAY=SA", starts_on=dt.date(2027, 3, 20),
            now=at("2027-03-26 12:00"),
        )  # fmt: skip
        self.run_at("2027-03-27 09:00")
        self.sent()
        ops.answer(item, user=self.ada, content="One")
        # Sunday 28 March, 07:00 is CEST (05:00 UTC): the clocks went
        # forward at 02:00
        self.run_at("2027-03-28 06:59")
        self.assertEqual(self.summaries(), [])
        self.run_at("2027-03-28 07:00")
        self.assertEqual(len(self.summaries()), 2)

    def test_a_paused_question_still_sends_what_was_asked(self):
        ops.answer(self.item, user=self.ada, content="One")
        ops.pause(self.item, actor=self.ada)
        self.summarize()
        self.assertEqual(len(self.summaries()), 2)

    def test_not_for_a_trashed_question(self):
        ops.answer(self.item, user=self.ada, content="One")
        item_ops.trash(self.item, actor=self.ada)
        self.assertEqual(self.summarize(), 1)
        self.assertEqual(self.summaries(), [])

    def test_late_runs_send_it(self):
        ops.answer(self.item, user=self.ada, content="One")
        self.assertEqual(self.summarize("2027-03-25 12:00"), 1)
        self.assertEqual(len(self.summaries()), 2)


class SummaryAfterDowntimeTest(CheckinTestCase):
    def test_the_morning_after_it_was_really_asked(self):
        """Down from Monday 08:00 to Tuesday 08:00: Monday's question is
        asked on Tuesday, its summary goes out on Wednesday"""
        self.run_at("2027-03-23 08:00")
        self.sent()
        ops.answer(self.item, user=self.ada, content="Fine")
        self.assertEqual(self.run_at("2027-03-24 06:59")["summarized"], 0)
        self.assertEqual(self.run_at("2027-03-24 07:00")["summarized"], 1)
        self.assertEqual(
            len([m for m in self.sent() if ": answers of 22. March" in m.subject]), 2
        )
