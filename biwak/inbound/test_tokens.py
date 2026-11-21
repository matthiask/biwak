"""Reply tokens in the Reply-To of notification and check-in question
mails (specs/notifications.md, stage 2)"""

import datetime as dt
import io

from django.core import mail
from django.core.management import call_command
from django.utils import timezone

from biwak.accounts.models import MailDelivery
from biwak.activity.mails import send_mails
from biwak.activity.models import Notification
from biwak.checkins import operations as checkin_ops
from biwak.checkins.models import Occurrence
from biwak.checkins.support import CheckinTestCase
from biwak.inbound.models import (
    RETENTION_DAYS,
    InboundMessage,
    InboundStatus,
    ReplyToken,
)
from biwak.inbound.support import ReplyTestCase, replying
from biwak.inbound.tokens import prune
from biwak.items import operations as ops
from biwak.test_utils import person


class RevokeActionTest(ReplyTestCase):
    def test_admin_revokes_tokens(self):
        admin = person("Root", is_admin=True)
        token = self.token()
        done = self.token(revoked_at=timezone.now() - dt.timedelta(days=1))
        revoked_at = done.revoked_at
        self.client.force_login(admin)
        response = self.client.post(
            "/admin/inbound/replytoken/",
            {"action": "revoke", "_selected_action": [token.pk, done.pk]},
        )
        self.assertEqual(response.status_code, 302)
        token.refresh_from_db()
        done.refresh_from_db()
        self.assertIsNotNone(token.revoked_at)
        # Already revoked ones keep their time
        self.assertEqual(done.revoked_at, revoked_at)

    def test_staff_without_admin_cannot(self):
        token = self.token()
        self.client.force_login(self.ada)
        self.client.post(
            "/admin/inbound/replytoken/",
            {"action": "revoke", "_selected_action": [token.pk]},
        )
        token.refresh_from_db()
        self.assertIsNone(token.revoked_at)


class ReplyToTest(ReplyTestCase):
    def notify(self):
        """Bea comments, the mails go out"""
        with self.captureOnCommitCallbacks(execute=True):
            ops.add_comment(
                self.todo, author=self.bea, content="The headline is too long."
            )
        with self.captureOnCommitCallbacks(execute=True):
            send_mails(now=timezone.now() + dt.timedelta(minutes=11))
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

    def test_notification_says_so(self):
        message = self.notify()[self.ada.email]
        html = message.alternatives[0][0]
        self.assertIn("Reply to this mail to comment.", message.body)
        self.assertIn("Reply to this mail to comment.", html)
        self.assertLess(
            message.body.index("Reply to this mail"), message.body.index("--\nUnsub")
        )

    def test_off_without_settings(self):
        for name in ("REPLY_DOMAIN", "RESEND_API_KEY", "RESEND_WEBHOOK_SECRET"):
            with self.subTest(name), self.settings(**{name: ""}):
                mail.outbox.clear()
                messages = self.notify()
                message = messages[self.ada.email]
                self.assertNotIn("Reply-To", message.extra_headers)
                self.assertNotIn("Reply to this mail", message.body)
                self.assertNotIn("Reply to this mail", message.alternatives[0][0])
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
        self.assertNotIn("Reply to this mail", digest.body)
        self.assertNotIn("Reply to this mail", digest.alternatives[0][0])
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

    def test_question_says_so(self):
        message = self.mails[self.ada.email]
        self.assertIn("Reply to this mail to answer.", message.body)
        self.assertIn("Reply to this mail to answer.", message.alternatives[0][0])

    def test_summary_has_no_reply_to(self):
        """Replying to the summary isn't an answer"""
        checkin_ops.answer(self.item, user=self.bob, content="Fine")
        self.sent()
        self.run_at("2027-03-23 07:00")
        [summary] = self.sent(self.ada)
        self.assertIn("answers of", summary.subject)
        self.assertNotIn("Reply-To", summary.extra_headers)
        self.assertNotIn("Reply to this mail", summary.body)


class RetentionTest(ReplyTestCase):
    def test_boundary(self):
        now = timezone.now()
        day = dt.timedelta(days=1)
        old = now - dt.timedelta(days=RETENTION_DAYS)
        for name, received in (
            ("old", old - day),
            ("recent", old + day),
        ):
            InboundMessage.objects.create(
                provider="resend", provider_id=name, received_at=received
            )
        prune(now=now)
        self.assertEqual(
            list(InboundMessage.objects.values_list("provider_id", flat=True)),
            ["recent"],
        )

    def test_tokens(self):
        now = timezone.now()
        day = dt.timedelta(days=1)
        old = now - dt.timedelta(days=RETENTION_DAYS)
        gone = [
            self.token(expires_at=old - day),
            self.token(expires_at=now + day, revoked_at=old - day),
        ]
        stay = [
            self.token(),
            self.token(expires_at=old + day),
            self.token(expires_at=now + day, revoked_at=old + day),
        ]
        self.assertEqual(prune(now=now), (0, 2))
        self.assertEqual(
            set(ReplyToken.objects.values_list("pk", flat=True)),
            {t.pk for t in stay},
        )
        self.assertFalse(ReplyToken.objects.filter(pk__in=[t.pk for t in gone]))

    def test_comments_posted_from_replies_stay(self):
        token = self.token(expires_at=timezone.now() - dt.timedelta(days=200))
        comment = ops.add_comment(self.todo, author=self.ada, content="By mail")
        InboundMessage.objects.create(
            provider="resend",
            provider_id="x",
            received_at=timezone.now() - dt.timedelta(days=200),
            token=token,
            comment=comment,
            status=InboundStatus.POSTED,
        )
        call_command("fairy_tasks", stdout=io.StringIO())
        self.assertFalse(InboundMessage.objects.exists())
        self.assertFalse(ReplyToken.objects.exists())
        self.assertEqual(self.comments(), [comment])
