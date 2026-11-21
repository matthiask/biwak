import datetime as dt
import json

from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from biwak.accounts.models import MailDelivery
from biwak.activity.mails import send_mails
from biwak.activity.models import Notification
from biwak.activity.operations import subscribe
from biwak.inbound.support import SECRET
from biwak.inbound.test_webhook import event as received, signed
from biwak.items import operations as ops
from biwak.outbox import sending as outbox
from biwak.outbox.models import Delivery, Kind, OutgoingMail
from biwak.outbox.test_sending import message
from biwak.test_utils import person, project


EMAIL_ID = "56761188-7520-42d8-8898-ff6fc54ce618"


def event(type, *, to="cleo@example.org", email_id=EMAIL_ID, bounce=None):
    """Shaped like Resend's documentation"""
    data = {
        "email_id": email_id,
        "created_at": "2026-11-21T10:00:00.000Z",
        "from": "Biwak <biwak@biwak.example.org>",
        "to": [to],
        "subject": "[Website] Order the tent",
    }
    if bounce:
        data["bounce"] = bounce
    return json.dumps({
        "type": type,
        "created_at": "2026-11-21T10:00:05.000Z",
        "data": data,
    }).encode()


PERMANENT = {
    "message": "The recipient's mail server rejected the address.",
    "subType": "General",
    "type": "Permanent",
}


@override_settings(
    RESEND_WEBHOOK_SECRET=SECRET,
    REPLY_DOMAIN="",
    BASE_URL="https://biwak.example.org",
)
class DeliveryEventsTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.cleo])
        shared = ops.create_list(
            project=self.project, title="Shared", creator=self.ada, visible=True
        )
        self.todo = ops.create_todo(
            todolist=shared, title="Order the tent", creator=self.ada
        )
        subscribe(self.cleo, self.todo)
        with self.captureOnCommitCallbacks(execute=True):
            self.row = outbox.send(message(to=self.cleo.email), Kind.NOTIFICATION)
        OutgoingMail.objects.filter(pk=self.row.pk).update(provider_id=EMAIL_ID)
        mail.outbox.clear()

    def post(self, body, **headers):
        return self.client.post(
            "/inbound/resend/",
            body,
            content_type="application/json",
            **(headers or signed(body)),
        )

    def comment(self):
        with self.captureOnCommitCallbacks(execute=True):
            ops.add_comment(self.todo, author=self.ada, content="Hi")
        with self.captureOnCommitCallbacks(execute=True):
            return send_mails(now=timezone.now() + dt.timedelta(minutes=11))

    def test_delivered(self):
        self.assertEqual(self.post(event("email.delivered")).status_code, 204)
        self.row.refresh_from_db()
        self.assertEqual(self.row.delivery, Delivery.DELIVERED)
        self.assertIsNotNone(self.row.delivery_at)
        self.cleo.refresh_from_db()
        self.assertIsNone(self.cleo.mail_undeliverable_at)

    def test_hard_bounce_stops_notification_mails(self):
        self.post(event("email.delivered"))
        response = self.post(event("email.bounced", bounce=PERMANENT))
        self.assertEqual(response.status_code, 204)
        self.row.refresh_from_db()
        self.assertEqual(self.row.delivery, Delivery.BOUNCED)
        self.assertIn("rejected the address", self.row.delivery_detail)
        self.cleo.refresh_from_db()
        self.assertIsNotNone(self.cleo.mail_undeliverable_at)
        # A later delivered (Resend retried, or events out of order) doesn't
        # hide it
        self.post(event("email.delivered"))
        self.row.refresh_from_db()
        self.assertEqual(self.row.delivery, Delivery.BOUNCED)

        self.assertEqual(self.comment(), 0)
        self.assertEqual(mail.outbox, [])
        # The lantern still has it; the mail waits like with "No mails"
        self.assertTrue(
            Notification.objects.filter(user=self.cleo, sent_at=None).exists()
        )

    def test_digests_stop_too(self):
        self.cleo.mail_delivery = MailDelivery.DIGEST
        self.cleo.mail_undeliverable_at = timezone.now()
        self.cleo.save()
        with self.captureOnCommitCallbacks(execute=True):
            ops.add_comment(self.todo, author=self.ada, content="Hi")
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(
                send_mails(now=timezone.now() + dt.timedelta(days=1, hours=8)), 0
            )

    def test_complaint(self):
        self.post(event("email.complained"))
        self.row.refresh_from_db()
        self.assertEqual(self.row.delivery, Delivery.COMPLAINED)
        self.cleo.refresh_from_db()
        self.assertIsNotNone(self.cleo.mail_undeliverable_at)

    def test_temporary_bounce_marks_nothing(self):
        self.post(
            event(
                "email.bounced",
                bounce={"type": "Temporary", "subType": "MailboxFull", "message": ""},
            )
        )
        self.row.refresh_from_db()
        self.assertEqual(self.row.delivery, "")
        self.assertEqual(self.row.delivery_detail, "Temporary MailboxFull")
        self.cleo.refresh_from_db()
        self.assertIsNone(self.cleo.mail_undeliverable_at)
        self.assertEqual(self.comment(), 1)

    def test_only_the_mails_recipients(self):
        """An address Resend names which isn't the mail's is left alone"""
        self.post(event("email.bounced", to=self.ada.email, bounce=PERMANENT))
        self.ada.refresh_from_db()
        self.assertIsNone(self.ada.mail_undeliverable_at)
        self.cleo.refresh_from_db()
        self.assertIsNotNone(self.cleo.mail_undeliverable_at)

    def test_unknown_mails_ignored(self):
        body = event("email.bounced", email_id="other", bounce=PERMANENT)
        self.assertEqual(self.post(body).status_code, 204)
        self.cleo.refresh_from_db()
        self.assertIsNone(self.cleo.mail_undeliverable_at)

    def test_signature_checked(self):
        body = event("email.complained")
        headers = signed(body, secret="whsec_" + "b3RoZXIgc2VjcmV0")
        self.assertEqual(self.post(body, **headers).status_code, 401)
        self.row.refresh_from_db()
        self.assertEqual(self.row.delivery, "")
        self.cleo.refresh_from_db()
        self.assertIsNone(self.cleo.mail_undeliverable_at)

    def test_invalid_payloads(self):
        for body in (
            b'{"type": "email.bounced"}',
            b'{"type": "email.bounced", "data": []}',
            b'{"type": "email.bounced", "data": {"email_id": 1}}',
        ):
            with self.subTest(body):
                self.assertEqual(self.post(body).status_code, 204)

    def test_off_without_the_secret(self):
        with override_settings(RESEND_WEBHOOK_SECRET=""):
            self.assertEqual(self.post(event("email.complained")).status_code, 404)

    def test_received_mails_while_replying_is_off(self):
        """Delivery events work without replying; received mails don't"""
        self.assertEqual(self.post(received()).status_code, 404)

    def test_cleared_when_the_address_changes(self):
        self.post(event("email.bounced", bounce=PERMANENT))
        self.cleo.refresh_from_db()
        self.cleo.full_name = "Cleo Renamed"
        self.cleo.save()
        self.cleo.refresh_from_db()
        self.assertIsNotNone(self.cleo.mail_undeliverable_at)
        self.cleo.email = "cleo@new.example.org"
        self.cleo.save(update_fields=["email"])
        self.cleo.refresh_from_db()
        self.assertIsNone(self.cleo.mail_undeliverable_at)
        self.assertEqual(self.comment(), 1)

    def test_cleared_by_an_admin(self):
        self.post(event("email.bounced", bounce=PERMANENT))
        admin = person("Root", is_admin=True)
        self.client.force_login(admin)
        response = self.client.get("/admin/accounts/user/", {"undeliverable": "1"})
        self.assertContains(response, self.cleo.email)
        self.assertNotContains(response, self.ada.email)
        self.client.post(
            "/admin/accounts/user/",
            {"action": "clear_undeliverable", "_selected_action": [self.cleo.pk]},
        )
        self.cleo.refresh_from_db()
        self.assertIsNone(self.cleo.mail_undeliverable_at)

    def test_shown_on_the_persons_page(self):
        self.post(event("email.bounced", bounce=PERMANENT))
        url = f"/people/{self.cleo.pk}/feed/"
        notice = "bounced or was marked as spam"
        self.client.force_login(self.ada)
        self.assertContains(self.client.get(url), notice)
        self.client.force_login(self.cleo)
        self.assertContains(self.client.get(url), notice)
        # Not to other clients
        other = person("Dora", client=True)
        self.project.memberships.create(user=other)
        self.client.force_login(other)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, notice)
        # Nor about people whose mail works
        self.client.force_login(self.cleo)
        self.assertNotContains(self.client.get(f"/people/{self.ada.pk}/feed/"), notice)

    def test_signing_in_by_code_says_nothing(self):
        """The login page doesn't tell whoever types the address that it
        bounced: that would reveal the account (decided 2026-11-21)"""
        cache.clear()
        self.post(event("email.bounced", bounce=PERMANENT))
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                "/accounts/login/code/", {"email": self.cleo.email}, follow=True
            )
        self.assertNotContains(response, "bounced")
        # The code is sent anyway: the address may work again
        self.assertEqual([m.to for m in mail.outbox], [[self.cleo.email]])

    def test_shown_on_the_settings_page(self):
        self.post(event("email.bounced", bounce=PERMANENT))
        notice = "bounced or was marked as spam"
        self.client.force_login(self.cleo)
        response = self.client.get("/accounts/settings/")
        self.assertContains(response, notice)
        self.assertContains(response, self.cleo.email)
        self.client.force_login(self.ada)
        self.assertNotContains(self.client.get("/accounts/settings/"), notice)

    def test_what_piled_up_is_dropped_when_cleared(self):
        """In the lantern, never mailed (decided 2026-11-21)"""
        self.post(event("email.bounced", bounce=PERMANENT))
        self.assertEqual(self.comment(), 0)
        self.cleo.refresh_from_db()
        self.cleo.mail_undeliverable_at = None
        self.cleo.save(update_fields=["mail_undeliverable_at"])
        piled = Notification.objects.get(user=self.cleo)
        self.assertIsNotNone(piled.sent_at)
        self.assertIsNone(piled.read_at)
        self.assertEqual(send_mails(now=timezone.now() + dt.timedelta(minutes=10)), 0)
        # What comes after is mailed again
        self.assertEqual(self.comment(), 1)
        self.assertEqual([m.to for m in mail.outbox], [[self.cleo.email]])

    def test_dropped_when_cleared_by_changing_the_address(self):
        self.post(event("email.bounced", bounce=PERMANENT))
        self.assertEqual(self.comment(), 0)
        self.cleo.refresh_from_db()
        self.cleo.email = "cleo@new.example.org"
        self.cleo.save()
        self.assertFalse(
            Notification.objects.filter(user=self.cleo, sent_at=None).exists()
        )

    def test_dropped_when_cleared_by_an_admin(self):
        self.post(event("email.bounced", bounce=PERMANENT))
        self.assertEqual(self.comment(), 0)
        self.client.force_login(person("Root", is_admin=True))
        self.client.post(
            "/admin/accounts/user/",
            {"action": "clear_undeliverable", "_selected_action": [self.cleo.pk]},
        )
        self.assertFalse(
            Notification.objects.filter(user=self.cleo, sent_at=None).exists()
        )
