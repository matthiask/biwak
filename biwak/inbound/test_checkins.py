"""Answering check-in questions by mail (specs/checkins.md,
specs/notifications.md stage 2)"""

from django.core import mail

from biwak.checkins import operations as ops
from biwak.checkins.models import Answer, Occurrence
from biwak.checkins.support import CheckinTestCase
from biwak.inbound.models import InboundStatus
from biwak.inbound.support import replying
from biwak.inbound.support_mails import ReceiveMixin, sample
from biwak.items import operations as item_ops


@replying
class AnsweringByMailTest(ReceiveMixin, CheckinTestCase):
    def setUp(self):
        super().setUp()
        self.run_at("2027-03-22 09:00")
        self.first = Occurrence.objects.get()
        self.mails = {m.to[0]: m for m in self.sent()}

    def token(self, user=None):
        address = self.mails[(user or self.ada).email].extra_headers["Reply-To"]
        return address.removeprefix("r-").split("@")[0]

    def test_replying_answers(self):
        message = self.receive(sample("gmail_de.eml", self.token()))
        self.assertEqual(message.status, InboundStatus.POSTED)
        answer = Answer.objects.get()
        self.assertEqual(
            (answer.author, answer.occurrence, answer.content),
            (
                self.ada,
                self.first,
                "Danke, ich kümmere mich morgen darum.\n\nGrüße\nAda",
            ),
        )
        self.assertEqual(message.answer, answer.item)

    def test_answers_the_occurrence_asked_not_the_latest(self):
        token = self.token()
        self.run_at("2027-03-29 09:00")
        self.receive(sample("outlook_en.eml", token))
        self.assertEqual(Answer.objects.get().occurrence, self.first)

    def test_replying_again_changes_the_answer(self):
        """Like answering again in the app"""
        token = self.token()
        self.receive(sample("gmail_de.eml", token))
        self.receive(sample("outlook_en.eml", token))
        answer = Answer.objects.get()
        self.assertEqual(
            answer.content, "Looks good to me, go ahead.\n\nBest regards\nAda"
        )

    def test_attachments(self):
        self.receive(sample("apple_mail_en.eml", self.token()))
        answer = Answer.objects.get()
        self.assertIn("(attachment:", answer.content)
        self.assertEqual(answer.item.attachments.get().name, "Brief v2.pdf")

    def test_removed_from_the_question(self):
        token = self.token()
        ops.set_people(self.item, [self.bob], actor=self.ada)
        message = self.receive(sample("gmail_en.eml", token))
        self.assertEqual(message.status, InboundStatus.NO_ACCESS)
        self.assertFalse(Answer.objects.exists())
        self.assertEqual([m.to for m in mail.outbox], [[self.ada.email]])

    def test_question_trashed(self):
        token = self.token()
        item_ops.trash(self.item, actor=self.ada)
        message = self.receive(sample("gmail_en.eml", token))
        self.assertEqual(message.status, InboundStatus.NO_ACCESS)

    def test_client_and_question_made_internal(self):
        item = self.question("What do you think?", people=[self.cleo], visible=True)
        self.run_at("2027-03-29 09:00")
        address = next(
            m for m in self.sent() if m.to == [self.cleo.email]
        ).extra_headers["Reply-To"]
        token = address.removeprefix("r-").split("@")[0]
        item_ops.set_visibility(item, visible=False, actor=self.ada)
        message = self.receive(sample("iphone_de.eml", token))
        self.assertEqual(message.status, InboundStatus.NO_ACCESS)
        self.assertFalse(Answer.objects.exists())
        item_ops.set_visibility(item, visible=True, actor=self.ada)
        message = self.receive(sample("outlook_ios_de.eml", token))
        self.assertEqual(message.status, InboundStatus.POSTED)
        self.assertEqual(Answer.objects.get().author, self.cleo)
