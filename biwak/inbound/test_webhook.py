import base64
import hashlib
import hmac
import json
import time
from unittest.mock import patch

from django.core import mail
from django.test import SimpleTestCase, override_settings

from biwak.inbound import providers
from biwak.inbound.models import InboundMessage, InboundStatus
from biwak.inbound.support import SECRET, ReplyTestCase
from biwak.inbound.support_mails import raw_sample


def signed(body, *, secret=SECRET, msg_id="msg_2kXYZ", timestamp=None):
    """The headers Svix sends"""
    timestamp = str(int(time.time()) if timestamp is None else timestamp)
    key = base64.b64decode(secret.removeprefix("whsec_"))
    signature = base64.b64encode(
        hmac.new(key, f"{msg_id}.{timestamp}.".encode() + body, hashlib.sha256).digest()
    ).decode()
    return {
        "HTTP_SVIX_ID": msg_id,
        "HTTP_SVIX_TIMESTAMP": timestamp,
        "HTTP_SVIX_SIGNATURE": f"v1,c29tZXRoaW5nIGVsc2U= v1,{signature}",
    }


def event(email_id="4ef9a417-02e9-4d39-ad75-9611e0fcc33c", type="email.received"):
    """Shaped like Resend's documentation of ``email.received``"""
    return json.dumps({
        "type": type,
        "created_at": "2026-11-20T09:15:03.000Z",
        "data": {
            "email_id": email_id,
            "created_at": "2026-11-20T09:15:02.000Z",
            "from": "ada@example.org",
            "to": ["r-replytoken0000000000@reply.example.org"],
            "bcc": [],
            "cc": [],
            "received_for": [],
            "message_id": "<CAF1x+gmail-en-1@mail.example.com>",
            "subject": "Re: [Website] Update the copy on the landing page",
            "attachments": [],
        },
    }).encode()


class WebhookTest(ReplyTestCase):
    def setUp(self):
        super().setUp()
        self.token_ = self.token()
        self.raw = raw_sample("gmail_en.eml", self.token_)
        self.authentication = {"spf": "pass", "dkim": "pass", "dmarc": "pass"}
        self.fetched = []

    def api(self, url, *, auth=True):
        """Resend's API: the received mail, its original message"""
        self.fetched.append(url)
        if url.startswith("https://api.resend.com/emails/receiving/"):
            self.assertTrue(auth)
            return json.dumps({
                "object": "email",
                "id": url.rsplit("/", 1)[1],
                "to": [f"r-{self.token_.token}@reply.example.org"],
                "from": "ada@example.org",
                "created_at": "2026-11-20T09:15:02.000Z",
                "subject": "Re: [Website] Update the copy on the landing page",
                "html": "<div>Thanks</div>",
                "text": "Thanks",
                "headers": {"from": "Ada Example <ada@example.org>"},
                "bcc": [],
                "cc": [],
                "reply_to": [],
                "received_for": [],
                "authentication": self.authentication,
                "message_id": "<CAF1x+gmail-en-1@mail.example.com>",
                "raw": {
                    "download_url": "https://inbound-cdn.example.com/raw/1?Signature=x",
                    "expires_at": "2026-11-20T10:15:02.000Z",
                },
                "attachments": [],
            }).encode()
        self.assertFalse(auth, "the raw download URL is signed, no API key")
        return self.raw

    def post(self, body, **headers):
        with (
            patch.object(providers, "_get", self.api),
            self.captureOnCommitCallbacks(execute=True),
        ):
            return self.client.post(
                "/inbound/resend/",
                body,
                content_type="application/json",
                **(signed(body) | headers),
            )

    def test_reply_posted(self):
        response = self.post(event())
        self.assertEqual(response.status_code, 204)
        message = InboundMessage.objects.get()
        self.assertEqual(
            (message.provider, message.provider_id, message.status),
            ("resend", "4ef9a417-02e9-4d39-ad75-9611e0fcc33c", InboundStatus.POSTED),
        )
        self.assertEqual(message.comment.author, self.ada)
        self.assertEqual(
            self.fetched,
            [
                "https://api.resend.com/emails/receiving/4ef9a417-02e9-4d39-ad75-9611e0fcc33c",
                "https://inbound-cdn.example.com/raw/1?Signature=x",
            ],
        )

    def test_delivered_twice(self):
        self.assertEqual(self.post(event()).status_code, 204)
        self.assertEqual(self.post(event()).status_code, 204)
        self.assertEqual(len(self.comments()), 1)
        self.assertEqual(len(self.fetched), 2, "fetched once")

    def test_authentication_from_the_api(self):
        self.authentication = {"spf": "pass", "dkim": "fail", "dmarc": "fail"}
        self.post(event())
        self.assertEqual(
            InboundMessage.objects.get().status, InboundStatus.UNAUTHENTICATED
        )
        self.assertEqual(self.comments(), [])

    def test_missing_authentication(self):
        """Mails received before Resend reported results"""
        self.authentication = None
        self.post(event())
        self.assertEqual(
            InboundMessage.objects.get().status, InboundStatus.UNAUTHENTICATED
        )

    def test_results_about_another_from(self):
        """Resend's verdicts are about the From it parsed; if ours differs
        they don't count"""
        self.raw = raw_sample("gmail_en.eml", self.token_).replace(
            b"From: Ada Example <ada@example.org>",
            b"From: =?utf-8?q?ada=40example=2Eorg?= <bea@example.org>",
        )
        with patch.object(providers, "_get", self.api):
            mail_ = providers.resend_fetch("x")
        self.assertEqual(mail_.sender, "bea@example.org")
        self.assertEqual((mail_.spf, mail_.dkim, mail_.dmarc), ("unknown",) * 3)

    def test_invalid_signatures(self):
        body = event()
        cases = {
            "other secret": signed(
                body, secret="whsec_" + base64.b64encode(b"other").decode()
            ),
            "old": signed(body, timestamp=int(time.time()) - 600),
            "future": signed(body, timestamp=int(time.time()) + 600),
            "no signature": {"HTTP_SVIX_SIGNATURE": ""},
            "not base64": {"HTTP_SVIX_TIMESTAMP": "soon"},
            "other body": signed(event(email_id="other")),
        }
        for name, headers in cases.items():
            with self.subTest(name):
                self.assertEqual(self.post(body, **headers).status_code, 401)
        self.assertEqual(self.fetched, [])
        self.assertFalse(InboundMessage.objects.exists())

    def test_other_events(self):
        self.assertEqual(self.post(event(type="email.delivered")).status_code, 204)
        self.assertEqual(self.fetched, [])

    def test_invalid_payloads(self):
        for body in (b"nonsense", b'{"type": "email.received"}', b"[]"):
            with self.subTest(body):
                self.assertEqual(self.post(body).status_code, 400)
        body = json.dumps({"type": "email.received", "data": {"email_id": 42}})
        self.assertEqual(self.post(body.encode()).status_code, 400)

    def test_fetching_fails(self):
        """Resend tries again"""

        def broken(url, *, auth=True):
            raise providers.ProviderError("timeout")

        body = event()
        with (
            patch.object(providers, "_get", broken),
            self.assertLogs("biwak.inbound.views", "ERROR"),
        ):
            response = self.client.post(
                "/inbound/resend/",
                body,
                content_type="application/json",
                **signed(body),
            )
        self.assertEqual(response.status_code, 502)
        self.assertFalse(InboundMessage.objects.exists())
        self.assertEqual(self.post(body).status_code, 204)
        self.assertEqual(len(self.comments()), 1)

    def test_no_original_message(self):
        original = self.api

        def api(url, *, auth=True):
            data = json.loads(original(url, auth=auth))
            data["raw"] = None
            return json.dumps(data).encode()

        self.api = api
        with self.assertLogs("biwak.inbound.views", "ERROR"):
            self.assertEqual(self.post(event()).status_code, 502)
        self.assertFalse(InboundMessage.objects.exists())

    def test_get_not_allowed(self):
        self.assertEqual(self.client.get("/inbound/resend/").status_code, 405)

    def test_off_without_settings(self):
        with override_settings(RESEND_WEBHOOK_SECRET=""):
            self.assertEqual(self.post(event()).status_code, 404)
        self.assertEqual(mail.outbox, [])

    def test_network_errors_become_provider_errors(self):
        with (
            patch("urllib.request.urlopen", side_effect=OSError("refused")),
            self.assertRaises(providers.ProviderError),
        ):
            providers.resend_fetch("x")


class VerifyTest(SimpleTestCase):
    def test_svix_example(self):
        """The example of Svix's documentation and libraries"""
        secret = "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw"
        body = b'{"test": 2432232314}'
        headers = {
            "svix-id": "msg_p5jXN8AQM9LWM0D4loKWxJek",
            "svix-timestamp": "1614265330",
            "svix-signature": "v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE=",
        }
        now = 1614265330 + 60
        self.assertTrue(providers.verify_svix(secret, headers, body, now=now))
        self.assertFalse(providers.verify_svix(secret, headers, body + b" ", now=now))
        self.assertFalse(providers.verify_svix(secret, headers, body, now=now + 300))
        self.assertFalse(providers.verify_svix("", headers, body, now=now))
        self.assertFalse(
            providers.verify_svix(
                secret,
                headers
                | {"svix-signature": headers["svix-signature"].replace("v1", "v2")},
                body,
                now=now,
            )
        )
