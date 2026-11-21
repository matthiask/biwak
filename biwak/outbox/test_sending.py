import datetime as dt
import json
import threading
from unittest.mock import Mock, patch

import time_machine
from django.core import mail
from django.core.cache import cache
from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.core.management import call_command
from django.db import close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from biwak.outbox import sending as outbox
from biwak.outbox.models import Kind, OutgoingMail, deserialize, serialize
from biwak.projects import operations as project_ops
from biwak.test_utils import person, project


def message(to="ada@example.org", subject="Hello"):
    message = EmailMultiAlternatives(
        subject,
        "Plain",
        '"Bea Example (Biwak)" <biwak@example.org>',
        [to],
        headers={"Message-ID": "<1@example.org>", "Auto-Submitted": "auto-generated"},
        reply_to=["r-token@reply.example.org"],
    )
    message.attach_alternative("<p>HTML</p>", "text/html")
    return message


def failing(exc=None):
    """The transport failing"""
    return patch.object(
        mail.mailers.default.__class__,
        "send_messages",
        side_effect=exc or OSError("down"),
    )


class RateLimited(Exception):
    status_code = 429


@override_settings(ADMINS=["admin@example.org"], BASE_URL="https://biwak.example.org")
class OutboxTest(TestCase):
    def queue(self, kind=Kind.NOTIFICATION, **kwargs):
        with self.captureOnCommitCallbacks(execute=True):
            return outbox.send(message(**kwargs), kind)

    def test_sent_at_once_after_the_commit(self):
        with self.captureOnCommitCallbacks() as callbacks:
            row = outbox.send(message(), Kind.NOTIFICATION)
            self.assertEqual(mail.outbox, [])
        self.assertEqual(len(callbacks), 1)
        callbacks[0]()
        (sent,) = mail.outbox
        self.assertEqual(sent.to, ["ada@example.org"])
        self.assertEqual(sent.from_email, '"Bea Example (Biwak)" <biwak@example.org>')
        self.assertEqual(sent.reply_to, ["r-token@reply.example.org"])
        self.assertEqual(sent.extra_headers["Message-ID"], "<1@example.org>")
        self.assertEqual(sent.alternatives[0].content, "<p>HTML</p>")
        row.refresh_from_db()
        self.assertIsNotNone(row.sent_at)
        self.assertIsNone(row.next_attempt_at)
        self.assertEqual(row.attempts, 1)
        self.assertEqual(row.recipients, ["ada@example.org"])
        # Only bookkeeping is kept
        self.assertIsNone(row.message)
        # Nothing twice
        self.assertIsNone(outbox.deliver(row.pk))
        self.assertEqual(outbox.retry(now=timezone.now() + dt.timedelta(hours=1)), {})
        self.assertEqual(len(mail.outbox), 1)

    def test_nothing_sent_on_rollback(self):
        with self.captureOnCommitCallbacks(execute=True):
            try:
                with transaction.atomic():
                    outbox.send(message(), Kind.NOTIFICATION)
                    raise ValueError
            except ValueError:
                pass
        self.assertFalse(OutgoingMail.objects.exists())
        self.assertEqual(mail.outbox, [])

    def test_failure_retried_with_backoff(self):
        start = timezone.now()
        with failing(), self.assertLogs("biwak.outbox.sending", "WARNING"):
            row = self.queue()
        row.refresh_from_db()
        self.assertEqual(row.attempts, 1)
        self.assertIn("OSError: down", row.last_error)
        self.assertIsNotNone(row.message)
        waits = []
        now = row.next_attempt_at
        with failing(), self.assertLogs("biwak.outbox.sending", "WARNING"):
            for _i in range(6):
                # Not before it's due
                self.assertEqual(outbox.retry(now=now - dt.timedelta(seconds=1)), {})
                self.assertEqual(outbox.retry(now=now), {"failed": 1})
                row.refresh_from_db()
                waits.append(row.next_attempt_at - now)
                now = row.next_attempt_at
        self.assertEqual(
            [round(w.total_seconds() / 60) for w in waits], [2, 5, 10, 30, 60, 60]
        )
        self.assertEqual(row.attempts, 7)
        self.assertLess(row.next_attempt_at, start + dt.timedelta(hours=4))
        self.assertEqual(outbox.retry(now=now), {"sent": 1})
        self.assertEqual(len(mail.outbox), 1)
        row.refresh_from_db()
        self.assertEqual(row.last_error, "")

    def test_given_up_after_a_day_and_the_admins_told(self):
        with failing(), self.assertLogs("biwak.outbox.sending", "WARNING"):
            row = self.queue(subject="Lost")
            self.queue(to="bea@example.org", subject="Also lost")
        later = timezone.now() + dt.timedelta(hours=24, minutes=1)
        with self.assertLogs("biwak.outbox.sending", "ERROR"):
            self.assertEqual(outbox.retry(now=later), {"given-up": 2})
        row.refresh_from_db()
        self.assertIsNotNone(row.given_up_at)
        self.assertIsNone(row.next_attempt_at)
        # Kept for the admins to look at
        self.assertEqual(row.subject, "Lost")
        self.assertIn("OSError: down", row.last_error)
        # One mail to the admins, around the outbox
        (notice,) = mail.outbox
        self.assertEqual(notice.to, ["admin@example.org"])
        self.assertIn("2 mails not sent", notice.subject)
        self.assertIn("'Lost'", notice.body)
        self.assertIn("bea@example.org", notice.body)
        self.assertIn(
            "https://biwak.example.org/admin/outbox/outgoingmail/?state=given_up",
            notice.body,
        )
        self.assertEqual(OutgoingMail.objects.count(), 2)
        self.assertEqual(outbox.retry(now=later), {})

    def test_login_codes_not_sent_after_they_expired(self):
        with failing(), self.assertLogs("biwak.outbox.sending", "WARNING"):
            row = self.queue(kind=Kind.LOGIN_CODE)
        row.refresh_from_db()
        self.assertEqual(row.expires_at, row.created_at + dt.timedelta(minutes=10))
        # Retried while the code is valid
        with failing(), self.assertLogs("biwak.outbox.sending", "WARNING"):
            outbox.retry(now=row.created_at + dt.timedelta(minutes=2))
        self.assertEqual(
            outbox.retry(now=row.created_at + dt.timedelta(minutes=10)),
            {"expired": 1},
        )
        row.refresh_from_db()
        self.assertIsNotNone(row.given_up_at)
        self.assertEqual(row.attempts, 2)
        # Nothing sent, and nothing for the admins to do
        self.assertEqual(mail.outbox, [])

    def test_rate_limited_not_counted(self):
        with failing(RateLimited()), self.assertLogs("biwak.outbox.sending"):
            first = self.queue()
            self.queue()
        due = timezone.now() + dt.timedelta(minutes=1)
        with failing(RateLimited()), self.assertLogs("biwak.outbox.sending"):
            # The run stops at the first: the others wait for the next
            self.assertEqual(outbox.retry(now=due), {"rate-limited": 1})
        first.refresh_from_db()
        self.assertEqual(first.attempts, 0)
        self.assertEqual(first.next_attempt_at, due + dt.timedelta(minutes=1))

    def test_retry_leaves_new_mails_to_the_attempt_after_the_commit(self):
        """A crash before the attempt after the commit: a retry a minute
        later sends it"""
        with self.captureOnCommitCallbacks():
            row = outbox.send(message(), Kind.NOTIFICATION)
        self.assertEqual(outbox.retry(now=row.created_at), {})
        self.assertEqual(
            outbox.retry(now=row.created_at + dt.timedelta(minutes=1)), {"sent": 1}
        )
        self.assertEqual(len(mail.outbox), 1)

    def test_send_mails_retries(self):
        with failing(), self.assertLogs("biwak.outbox.sending", "WARNING"):
            self.queue()
        with time_machine.travel(timezone.now() + dt.timedelta(minutes=1)):
            call_command("send_mails")
        self.assertEqual(len(mail.outbox), 1)

    def test_pruned_after_30_days(self):
        old = self.queue()
        OutgoingMail.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - dt.timedelta(days=30, minutes=1)
        )
        new = self.queue()
        self.assertEqual(outbox.prune(), 1)
        self.assertEqual(list(OutgoingMail.objects.all()), [new])

    def test_fairy_tasks_prune(self):
        row = self.queue()
        OutgoingMail.objects.update(created_at=timezone.now() - dt.timedelta(days=31))
        call_command("fairy_tasks")
        self.assertFalse(OutgoingMail.objects.filter(pk=row.pk).exists())

    def test_attachments_and_plain_messages(self):
        plain = EmailMessage("Hi", "Text", "biwak@example.org", ["ada@example.org"])
        plain.attach("a.pdf", b"%PDF-\x00\xff", "application/pdf")
        plain.attach("a.txt", "Text", "text/plain")
        copy = deserialize(json.loads(json.dumps(serialize(plain))))
        self.assertEqual(
            [tuple(a) for a in copy.attachments],
            [
                ("a.pdf", b"%PDF-\x00\xff", "application/pdf"),
                ("a.txt", "Text", "text/plain"),
            ],
        )
        self.assertEqual(copy.alternatives, [])
        self.assertEqual(copy.body, "Text")


@override_settings(BASE_URL="https://biwak.example.org")
class KindsTest(TestCase):
    """Every mail of the app goes through the outbox, with its kind"""

    def test_login_codes(self):
        cache.clear()
        ada = person("Ada")
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post("/accounts/login/code/", {"email": ada.email})
        (row,) = OutgoingMail.objects.all()
        self.assertEqual(row.kind, Kind.LOGIN_CODE)
        self.assertIsNotNone(row.expires_at)
        self.assertEqual(mail.outbox[0].to, [ada.email])

    def test_unknown_addresses_asking_for_a_code(self):
        cache.clear()
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post("/accounts/login/code/", {"email": "x@example.org"})
        self.assertEqual(
            list(OutgoingMail.objects.values_list("kind", flat=True)),
            [Kind.LOGIN_CODE] * len(mail.outbox),
        )

    def test_invitations(self):
        ada = person("Ada")
        with self.captureOnCommitCallbacks(execute=True):
            project_ops.invite(
                project(members=[ada]), email="new@example.org", actor=ada
            )
        (row,) = OutgoingMail.objects.all()
        self.assertEqual(row.kind, Kind.INVITATION)
        self.assertEqual(mail.outbox[0].to, ["new@example.org"])

    def test_invitation_not_sent_on_rollback(self):
        ada = person("Ada")
        with self.captureOnCommitCallbacks(execute=True):
            try:
                with transaction.atomic():
                    project_ops.invite(
                        project(members=[ada]), email="new@example.org", actor=ada
                    )
                    raise ValueError
            except ValueError:
                pass
        self.assertFalse(OutgoingMail.objects.exists())
        self.assertEqual(mail.outbox, [])


@override_settings(
    MAILERS={
        "default": {
            "BACKEND": "biwak.outbox.resend.EmailBackend",
            "OPTIONS": {"api_key": "re_test_key", "timeout": 10},
        }
    },
    BASE_URL="https://biwak.example.org",
)
class ResendTest(TestCase):
    """Resend's API through anymail, never called for real"""

    def setUp(self):
        self.requests = []

        def request(**params):
            self.requests.append(params)
            return Mock(
                status_code=200,
                json=lambda: {"id": "49a3999c-0ce1-4ea6-ab68-afcd6dc2e794"},
            )

        patcher = patch("requests.Session.request", side_effect=request)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_idempotency_key_tags_and_message_id(self):
        with self.captureOnCommitCallbacks(execute=True):
            row = outbox.send(message(), Kind.DIGEST)
        (params,) = self.requests
        self.assertEqual(params["url"], "https://api.resend.com/emails")
        self.assertEqual(params["timeout"], 10)
        self.assertEqual(
            params["headers"]["Idempotency-Key"],
            f"biwak.example.org/outgoing-mail/{row.pk}",
        )
        self.assertEqual(params["headers"]["Authorization"], "Bearer re_test_key")
        data = json.loads(params["data"])
        self.assertEqual(data["tags"], [{"name": "kind", "value": "digest"}])
        self.assertEqual(data["from"], '"Bea Example (Biwak)" <biwak@example.org>')
        self.assertEqual(data["to"], ["ada@example.org"])
        self.assertEqual(data["reply_to"], ["r-token@reply.example.org"])
        self.assertEqual(data["html"], "<p>HTML</p>")
        self.assertEqual(data["headers"]["Message-ID"], "<1@example.org>")
        row.refresh_from_db()
        self.assertEqual(row.provider_id, "49a3999c-0ce1-4ea6-ab68-afcd6dc2e794")

    def test_the_same_key_when_retried(self):
        with (
            patch(
                "requests.Session.request",
                side_effect=[Mock(status_code=500, text="", json=dict), Mock()],
            ),
            self.assertLogs("biwak.outbox.sending", "WARNING"),
            self.captureOnCommitCallbacks(execute=True),
        ):
            row = outbox.send(message(), Kind.NOTIFICATION)
        row.refresh_from_db()
        self.assertIn("AnymailRequestsAPIError", row.last_error)
        outbox.retry(now=row.next_attempt_at)
        (params,) = self.requests
        self.assertEqual(
            params["headers"]["Idempotency-Key"],
            f"biwak.example.org/outgoing-mail/{row.pk}",
        )
        row.refresh_from_db()
        self.assertEqual(row.attempts, 2)
        self.assertIsNotNone(row.sent_at)

    def test_admin_mails_tagged(self):
        with override_settings(ADMINS=["admin@example.org"]):
            mail.mail_admins("Hi", "Text")
        (params,) = self.requests
        self.assertEqual(
            json.loads(params["data"])["tags"], [{"name": "kind", "value": "admin"}]
        )
        self.assertNotIn("Idempotency-Key", params["headers"])
        self.assertFalse(OutgoingMail.objects.exists())


class AdminTest(TestCase):
    def test_list_and_detail(self):
        admin = person("Root", is_admin=True)
        self.client.force_login(admin)
        with self.captureOnCommitCallbacks(execute=True):
            sent = outbox.send(message(), Kind.NOTIFICATION)
        with (
            failing(),
            self.assertLogs("biwak.outbox.sending", "WARNING"),
            self.captureOnCommitCallbacks(execute=True),
        ):
            waiting = outbox.send(message(to="bea@example.org"), Kind.DIGEST)
        url = "/admin/outbox/outgoingmail/"
        response = self.client.get(url, {"q": "bea@example.org"})
        self.assertContains(response, "bea@example.org")
        self.assertNotContains(response, "ada@example.org")
        for state in ("waiting", "sent", "given_up"):
            self.assertEqual(self.client.get(url, {"state": state}).status_code, 200)
        self.assertContains(
            self.client.get(f"{url}{sent.pk}/change/"), "Resend&#x27;s log has it"
        )
        self.assertContains(self.client.get(f"{url}{waiting.pk}/change/"), "Hello")
        self.assertEqual(self.client.get(f"{url}add/").status_code, 403)


@override_settings(BASE_URL="https://biwak.example.org")
class TwoAtOnceTest(TransactionTestCase):
    def test_a_mail_being_sent_is_skipped(self):
        """While one run sends a mail (holding its lock), another skips it
        at once instead of sending it too"""
        with failing(), self.assertLogs("biwak.outbox.sending", "WARNING"):
            row = outbox.send(message(), Kind.NOTIFICATION)
        row.refresh_from_db()
        sending, release = threading.Event(), threading.Event()
        sent = []

        def slow(backend, messages):
            sending.set()
            release.wait(10)
            sent.extend(messages)
            return len(messages)

        results = {}

        def run(name):
            try:
                results[name] = outbox.retry(now=row.next_attempt_at)
            finally:
                close_old_connections()
                connection.close()

        with patch.object(mail.mailers.default.__class__, "send_messages", slow):
            first = threading.Thread(target=run, args=["first"])
            first.start()
            self.assertTrue(sending.wait(10))
            second = threading.Thread(target=run, args=["second"])
            second.start()
            second.join(5)
            waited = second.is_alive()
            release.set()
            first.join()
            second.join()
        self.assertFalse(waited, "the second run waited for the first")
        self.assertEqual(results, {"first": {"sent": 1}, "second": {}})
        self.assertEqual(len(sent), 1)
