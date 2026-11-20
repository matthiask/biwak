import datetime as dt

from django.core import mail
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction

from biwak.accounts.models import NotificationLevel
from biwak.activity import mentions
from biwak.activity.mails import send_mails
from biwak.activity.models import Action, Event, Notification, Subscription
from biwak.checkins import operations as ops
from biwak.checkins.models import Answer, Mode, Occurrence, QuestionMail
from biwak.checkins.support import CheckinTestCase, at
from biwak.files import attachments
from biwak.items import operations as item_ops, visibility
from biwak.items.models import Comment, Item, Kind, Status
from biwak.projects import operations as project_ops
from biwak.test_utils import person


class AnswerTestCase(CheckinTestCase):
    def setUp(self):
        super().setUp()
        self.run_at("2027-03-22 09:00")
        self.first = Occurrence.objects.get()
        self.run_at("2027-03-29 09:00")
        self.second = Occurrence.objects.latest("date")
        self.sent()


class AnsweringTest(AnswerTestCase):
    def test_answering_the_latest_occurrence(self):
        item = ops.answer(self.item, user=self.ada, content="Fine")
        self.assertEqual(item.kind, Kind.ANSWER)
        self.assertEqual(item.parent_id, self.item.pk)
        self.assertEqual(item.creator, self.ada)
        self.assertEqual(item.title, "How are you?")
        answer = item.answer
        self.assertEqual(
            (answer.occurrence, answer.author, answer.content),
            (self.second, self.ada, "Fine"),
        )
        self.assertEqual(ops.answers_of(self.second), [answer])
        self.assertEqual(ops.answers_of(self.first), [])

    def test_answering_an_older_occurrence(self):
        item = ops.answer(
            self.item, user=self.ada, content="Last week", occurrence=self.first
        )
        self.assertEqual(item.answer.occurrence, self.first)
        self.assertEqual(ops.answers_of(self.second), [])

    def test_one_answer_per_person_and_occurrence(self):
        first = ops.answer(self.item, user=self.ada, content="Fine")
        again = ops.answer(self.item, user=self.ada, content="Better")
        self.assertEqual(first.pk, again.pk, "the answer is changed")
        self.assertEqual(Answer.objects.filter(author=self.ada).count(), 1)
        self.assertEqual(Item.objects.get(pk=first.pk).answer.content, "Better")
        # Another occurrence: another answer
        other = ops.answer(
            self.item, user=self.ada, content="Then", occurrence=self.first
        )
        self.assertNotEqual(other.pk, first.pk)
        # And the database says so too
        with self.assertRaises(IntegrityError), transaction.atomic():
            Answer.objects.create(
                item=Item.objects.create(
                    project=self.project, parent=self.item, kind=Kind.ANSWER,
                    title="x", creator=self.ada,
                ),
                occurrence=self.second,
                author=self.ada,
                content="Twice",
            )  # fmt: skip

    def test_two_people_answer_the_same_occurrence(self):
        ops.answer(self.item, user=self.ada, content="One")
        ops.answer(self.item, user=self.bob, content="Two")
        self.assertEqual(
            [a.content for a in ops.answers_of(self.second)],
            ["Two", "One"],
            "newest first",
        )

    def test_editing_records_an_event_only_for_changes(self):
        item = ops.answer(self.item, user=self.ada, content="Fine")
        count = Event.objects.count()
        ops.answer(self.item, user=self.ada, content="Fine")
        self.assertEqual(Event.objects.count(), count)
        ops.answer(self.item, user=self.ada, content="Better")
        self.assertEqual(
            Event.objects.filter(item=item, action=Action.EDITED).count(), 1
        )

    def test_events_and_subscriptions(self):
        item = ops.answer(self.item, user=self.ada, content="Fine")
        event = Event.objects.get(item=item, action=Action.CREATED)
        self.assertEqual((event.actor, event.project), (self.ada, self.project))
        self.assertTrue(Subscription.objects.filter(item=item, user=self.ada).exists())

    def test_the_answer_inherits_the_questions_visibility(self):
        visible = self.question("Shared", visible=True, people=[self.ada, self.cleo])
        self.run_at("2027-04-05 09:00")
        answer = ops.answer(visible, user=self.cleo, content="Hello")
        self.assertTrue(answer.is_client_visible)
        internal = ops.answer(self.item, user=self.ada, content="Hello")
        self.assertFalse(internal.is_client_visible)
        self.assertEqual(visibility.check(), [])
        item_ops.set_visibility(
            Item.objects.get(pk=visible.pk), visible=False, actor=self.ada
        )
        self.assertFalse(Item.objects.get(pk=answer.pk).is_client_visible)
        self.assertEqual(visibility.check(), [])

    def test_not_asked_yet(self):
        item = self.question("New", people=[self.ada])
        with self.assertRaises(ValueError):
            ops.answer(item, user=self.ada, content="Too early")

    def test_the_occurrence_must_belong_to_the_question(self):
        other = self.question("Other", people=[self.ada])
        self.run_at("2027-04-05 09:00")
        elsewhere = Occurrence.objects.filter(question__item=other).get()
        with self.assertRaises(ValueError):
            ops.answer(self.item, user=self.ada, content="Wrong", occurrence=elsewhere)

    def test_only_people_asked_answer(self):
        dora = person("Dora")
        project_ops.add_member(self.project, dora, actor=self.ada)
        for user in [dora, self.cleo]:
            with self.assertRaises(ops.NotAllowed):
                ops.answer(self.item, user=user, content="Hi")
        self.assertFalse(Answer.objects.exists())

    def test_people_removed_cant_answer_but_their_answers_stay(self):
        ops.answer(self.item, user=self.bob, content="Before")
        ops.set_people(self.item, [self.ada], actor=self.ada)
        with self.assertRaises(ops.NotAllowed):
            ops.answer(self.item, user=self.bob, content="After")
        self.assertEqual([a.content for a in ops.answers_of(self.second)], ["Before"])

    def test_a_client_on_an_internal_question_isnt_allowed(self):
        visible = self.question("Shared", visible=True, people=[self.cleo])
        self.run_at("2027-04-05 09:00")
        item_ops.set_visibility(
            Item.objects.get(pk=visible.pk), visible=False, actor=self.ada
        )
        with self.assertRaises(ops.NotAllowed):
            ops.answer(visible, user=self.cleo, content="Still here")

    def test_a_trashed_answer_is_brought_back_by_answering_again(self):
        item = ops.answer(self.item, user=self.ada, content="Oops")
        item_ops.trash(item, actor=self.ada)
        self.assertEqual(ops.answers_of(self.second), [])
        again = ops.answer(self.item, user=self.ada, content="Better")
        self.assertEqual(again.pk, item.pk)
        self.assertEqual(Item.objects.get(pk=item.pk).status, Status.ACTIVE)
        self.assertEqual([a.content for a in ops.answers_of(self.second)], ["Better"])

    def test_attachments_are_linked_to_the_answer(self):
        attachment = attachments.upload(
            project=self.project,
            file=ContentFile(b"\x89PNG\r\n", name="photo.png"),
            uploaded_by=self.ada,
        )
        item = ops.answer(
            self.item, user=self.ada, content=f"![photo](attachment:{attachment.key})"
        )
        attachment.refresh_from_db()
        self.assertEqual(attachment.item_id, item.pk)

    def test_mentions_in_answers(self):
        item = ops.answer(
            self.item, user=self.ada, content=f"Ask {mentions.syntax(self.bob)}"
        )
        self.assertTrue(item.mentions.filter(user=self.bob).exists())

    def test_comments_on_answers(self):
        item = ops.answer(self.item, user=self.ada, content="Fine")
        self.assertTrue(item.is_commentable)
        comment = item_ops.add_comment(item, author=self.bob, content="Glad to hear")
        self.assertEqual(Comment.objects.get(), comment)
        # The question itself has no comments
        with self.assertRaises(ValidationError):
            item_ops.add_comment(self.item, author=self.bob, content="No")

    def test_trashing_the_question_trashes_its_answers(self):
        item = ops.answer(self.item, user=self.ada, content="Fine")
        item_ops.trash(Item.objects.get(pk=self.item.pk), actor=self.ada)
        self.assertEqual(Item.objects.get(pk=item.pk).status, Status.TRASHED)
        item_ops.restore(Item.objects.get(pk=self.item.pk), actor=self.ada)
        self.assertEqual(Item.objects.get(pk=item.pk).status, Status.ACTIVE)

    def test_the_mail_mode(self):
        self.assertEqual(
            ops.set_mail_mode(self.item, user=self.bob, mode="each"), Mode.EACH
        )
        self.assertEqual(QuestionMail.objects.get().mode, Mode.EACH)
        ops.set_mail_mode(self.item, user=self.bob, mode="none")
        self.assertEqual(QuestionMail.objects.count(), 1)
        with self.assertRaises(ValueError):
            ops.set_mail_mode(self.item, user=self.bob, mode="sometimes")

    def test_choosing_a_mail_subscribes(self):
        dora = person("Dora")
        project_ops.add_member(self.project, dora, actor=self.ada)
        ops.set_mail_mode(self.item, user=dora, mode=Mode.NONE)
        self.assertFalse(
            Subscription.objects.filter(user=dora, item=self.item).exists()
        )
        ops.set_mail_mode(self.item, user=dora, mode=Mode.SUMMARY)
        self.assertTrue(Subscription.objects.filter(user=dora, item=self.item).exists())


class DueTest(AnswerTestCase):
    def due(self, user, **kwargs):
        return [o.question.item_id for o in ops.due(user, **kwargs)]

    def test_the_latest_occurrence_not_answered(self):
        self.assertEqual(self.due(self.ada), [self.item.pk])
        self.assertEqual(self.due(self.ada, project=self.project), [self.item.pk])
        ops.answer(self.item, user=self.ada, content="Fine")
        self.assertEqual(self.due(self.ada), [])
        self.assertEqual(self.due(self.bob), [self.item.pk])

    def test_answering_an_older_occurrence_doesnt_change_what_is_due(self):
        ops.answer(self.item, user=self.ada, content="Then", occurrence=self.first)
        self.assertEqual(self.due(self.ada), [self.item.pk])

    def test_a_trashed_answer_is_due_again(self):
        item = ops.answer(self.item, user=self.ada, content="Oops")
        item_ops.trash(item, actor=self.ada)
        self.assertEqual(self.due(self.ada), [self.item.pk])

    def test_not_for_people_not_asked_then(self):
        dora = person("Dora")
        project_ops.add_member(self.project, dora, actor=self.ada)
        ops.set_people(self.item, [self.ada, self.bob, dora], actor=self.ada)
        self.assertEqual(self.due(dora), [], "from the next occurrence on")
        self.run_at("2027-04-05 09:00")
        self.assertEqual(self.due(dora), [self.item.pk])
        # Removed: not any more
        ops.set_people(self.item, [self.ada, self.bob], actor=self.ada)
        self.assertEqual(self.due(dora), [])

    def test_not_while_paused_trashed_or_in_archived_projects(self):
        ops.pause(self.item, actor=self.ada)
        self.assertEqual(self.due(self.ada), [])
        ops.resume(self.item, actor=self.ada)
        self.assertEqual(self.due(self.ada), [self.item.pk])
        item_ops.trash(Item.objects.get(pk=self.item.pk), actor=self.ada)
        self.assertEqual(self.due(self.ada), [])
        item_ops.restore(Item.objects.get(pk=self.item.pk), actor=self.ada)
        project_ops.archive_project(self.project, actor=self.ada)
        self.assertEqual(self.due(self.ada), [])

    def test_clients_only_what_they_see(self):
        visible = self.question("Shared", visible=True, people=[self.cleo])
        self.run_at("2027-04-05 09:00")
        self.assertEqual(self.due(self.cleo), [visible.pk])
        item_ops.set_visibility(
            Item.objects.get(pk=visible.pk), visible=False, actor=self.ada
        )
        self.assertEqual(self.due(self.cleo), [])

    def test_across_projects(self):
        from biwak.test_utils import project

        other = project("Other", members=[self.ada])
        item = ops.create_question(
            project=other, title="Elsewhere", creator=self.ada, people=[self.ada],
            now=at("2027-03-19 12:00"), rule="FREQ=DAILY",
            starts_on=dt.date(2027, 3, 1), time_of_day=dt.time(9),
        )  # fmt: skip
        self.run_at("2027-03-29 09:00")
        self.assertEqual(sorted(self.due(self.ada)), sorted([self.item.pk, item.pk]))
        self.assertEqual(self.due(self.ada, project=other), [item.pk])


class NotificationsTest(AnswerTestCase):
    """The mails of single answers are the normal notifications, only for
    those who chose "each" (or are mentioned)"""

    def notified(self, run):
        before = set(Notification.objects.values_list("pk", flat=True))
        with self.captureOnCommitCallbacks(execute=True):
            run()
        return {
            n.user
            for n in Notification.objects.exclude(pk__in=before).select_related("user")
        }

    def test_nobody_by_default(self):
        told = self.notified(
            lambda: ops.answer(self.item, user=self.ada, content="Fine")
        )
        self.assertEqual(told, set())

    def test_those_who_chose_each(self):
        ops.set_mail_mode(self.item, user=self.bob, mode=Mode.EACH)
        told = self.notified(
            lambda: ops.answer(self.item, user=self.ada, content="Fine")
        )
        self.assertEqual(told, {self.bob})
        with self.captureOnCommitCallbacks(execute=True):
            send_mails(now=at("2027-03-29 12:00"))
        message = mail.outbox[0]
        self.assertEqual(message.to, [self.bob.email])
        self.assertEqual(message.subject, "[Website] How are you?")
        self.assertIn("Ada Example answered.", message.body)
        self.assertIn("Fine", message.body)

    def test_never_the_author(self):
        ops.set_mail_mode(self.item, user=self.ada, mode=Mode.EACH)
        told = self.notified(
            lambda: ops.answer(self.item, user=self.ada, content="Fine")
        )
        self.assertEqual(told, set())

    def test_each_passes_the_level_concerns_me_but_not_nothing(self):
        for user, level in [
            (self.bob, NotificationLevel.CONCERNS_ME),
        ]:
            user.notification_level = level
            user.save()
        ops.set_mail_mode(self.item, user=self.bob, mode=Mode.EACH)
        told = self.notified(
            lambda: ops.answer(self.item, user=self.ada, content="One")
        )
        self.assertEqual(told, {self.bob})
        self.bob.notification_level = NotificationLevel.NOTHING
        self.bob.save()
        told = self.notified(
            lambda: ops.answer(
                self.item, user=self.ada, content="Two", occurrence=self.first
            )
        )
        self.assertEqual(told, set())

    def test_the_mode_none_and_summary_get_nothing(self):
        ops.set_mail_mode(self.item, user=self.bob, mode=Mode.NONE)
        told = self.notified(
            lambda: ops.answer(self.item, user=self.ada, content="One")
        )
        self.assertEqual(told, set())

    def test_mentioned_people_are_told_whatever_their_mode(self):
        ops.set_mail_mode(self.item, user=self.bob, mode=Mode.NONE)
        told = self.notified(
            lambda: ops.answer(
                self.item, user=self.ada, content=f"Thanks {mentions.syntax(self.bob)}"
            )
        )
        self.assertEqual(told, {self.bob})

    def test_comments_on_an_answer_notify_its_author_and_commenters(self):
        item = ops.answer(self.item, user=self.ada, content="Fine")
        told = self.notified(
            lambda: item_ops.add_comment(item, author=self.bob, content="Glad")
        )
        self.assertEqual(told, {self.ada})
        told = self.notified(
            lambda: item_ops.add_comment(item, author=self.ada, content="Thanks")
        )
        self.assertEqual(told, {self.bob})

    def test_clients_each_on_visible_questions_only(self):
        visible = self.question("Shared", visible=True, people=[self.ada, self.cleo])
        self.run_at("2027-04-05 09:00")
        ops.set_mail_mode(visible, user=self.cleo, mode=Mode.EACH)
        ops.set_mail_mode(
            self.item, user=self.cleo, mode=Mode.EACH
        )  # not allowed to see
        told = self.notified(lambda: ops.answer(visible, user=self.ada, content="One"))
        self.assertEqual(told, {self.cleo})
        told = self.notified(
            lambda: ops.answer(self.item, user=self.ada, content="Two")
        )
        self.assertNotIn(self.cleo, told)
