"""Reply tokens in the Reply-To of notification and check-in question
mails (specs/notifications.md, stage 2)"""

import datetime as dt

from django.core import mail
from django.utils import timezone

from biwak.accounts.models import MailDelivery
from biwak.activity.mails import send_mails
from biwak.activity.models import Notification
from biwak.checkins import operations as checkin_ops
from biwak.checkins.models import Occurrence
from biwak.checkins.support import CheckinTestCase
from biwak.inbound.models import ReplyToken
from biwak.inbound.support import ReplyTestCase, replying
from biwak.items import operations as ops


class ReplyToTest(ReplyTestCase):
    def notify(self):
        """Bea comments, the mails go out"""
        with self.captureOnCommitCallbacks(execute=True):
            ops.add_comment(
                self.todo, author=self.bea, content="The headline is too long."
            )
        with self.captureOnCommitCallbacks(execute=True):
            send_mails(now=timezone.now() + dt.timedelta(minutes=3))
        return {message.to[0]: message for message in mail.outbox}

    def test_notification_mails_carry_a_token_each(self):
        messages = self.notify()
        tokens = {token.user: token for token in ReplyToken.objects.all()}
        self.assertEqual(set(tokens), {self.ada, self.cleo})
        for user, token in tokens.items():
            self.assertEqual(
                messages[user.email].extra_headers["Reply-To"],
                f"r-{token.token}@reply.example.org",
            )
            self.assertEqual(token.item, self.todo)
            self.assertRegex(token.token, r"^[a-z0-9]{20}$")
            self.assertIsNone(token.occurrence)
            self.assertAlmostEqual(
                token.expires_at,
                timezone.now() + dt.timedelta(days=182),
                delta=dt.timedelta(days=2),
            )

    def test_off_without_settings(self):
        for name in ("REPLY_DOMAIN", "RESEND_API_KEY", "RESEND_WEBHOOK_SECRET"):
            with self.subTest(name), self.settings(**{name: ""}):
                mail.outbox.clear()
                messages = self.notify()
                self.assertNotIn("Reply-To", messages[self.ada.email].extra_headers)
                self.assertFalse(ReplyToken.objects.exists())

    def test_digests_have_no_reply_to(self):
        """A digest is about many items"""
        self.ada.mail_delivery = MailDelivery.DIGEST
        self.ada.save()
        with self.captureOnCommitCallbacks(execute=True):
            ops.add_comment(self.todo, author=self.bea, content="Hi")
        Notification.objects.update(created_at=timezone.now() - dt.timedelta(days=1))
        tomorrow = timezone.localtime() + dt.timedelta(days=1)
        with self.captureOnCommitCallbacks(execute=True):
            send_mails(now=tomorrow.replace(hour=7, minute=5))
        digest = next(m for m in mail.outbox if m.to == [self.ada.email])
        self.assertNotIn("Reply-To", digest.extra_headers)
        self.assertFalse(ReplyToken.objects.filter(user=self.ada).exists())


@replying
class QuestionMailTest(CheckinTestCase):
    def setUp(self):
        super().setUp()
        self.run_at("2027-03-22 09:00")
        self.first = Occurrence.objects.get()
        self.mails = {m.to[0]: m for m in self.sent()}

    def test_question_mail_has_a_token(self):
        token = ReplyToken.objects.get(user=self.ada)
        self.assertEqual((token.item, token.occurrence), (self.item, self.first))
        self.assertEqual(
            self.mails[self.ada.email].extra_headers["Reply-To"],
            f"r-{token.token}@reply.example.org",
        )

    def test_summary_has_no_reply_to(self):
        """Replying to the summary isn't an answer"""
        checkin_ops.answer(self.item, user=self.bob, content="Fine")
        self.sent()
        self.run_at("2027-03-23 07:00")
        [summary] = self.sent(self.ada)
        self.assertIn("answers of", summary.subject)
        self.assertNotIn("Reply-To", summary.extra_headers)
