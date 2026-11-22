"""Receiving forwarded mails at inbox@REPLY_DOMAIN (specs/forwarding.md)"""

import io
import itertools
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings

from biwak.forwarding import operations
from biwak.forwarding.models import ForwardedFile, ForwardedMail
from biwak.forwarding.support import IMAGE, raw_sample, sample
from biwak.inbound.models import InboundMessage, InboundStatus
from biwak.inbound.receive import receive
from biwak.inbound.support import replying
from biwak.test_utils import external, person


_ids = itertools.count()
FAIL = {"spf": "pass", "dkim": "fail", "dmarc": "fail"}


@replying
class ForwardTestCase(TestCase):
    """Ada (staff) forwards; Cleo is a client"""

    def setUp(self):
        self.ada = person("Ada")
        self.cleo = person("Cleo", client=True)

    def receive(self, parsed):
        with self.captureOnCommitCallbacks(execute=True):
            return receive(parsed, provider="test", provider_id=f"fwd-{next(_ids)}")


class ReceiveTest(ForwardTestCase):
    def test_staff_forward_lands_in_their_list(self):
        message = self.receive(sample("outlook_en.eml"))
        self.assertEqual(message.status, InboundStatus.FORWARDED)
        forwarded = ForwardedMail.objects.get()
        self.assertEqual(forwarded.user, self.ada)
        self.assertEqual(forwarded.subject, "Revised quote for the landing page")
        self.assertEqual(forwarded.sender, "Dora Example <dora@example.com>")
        self.assertEqual(str(forwarded.sent_on), "2026-11-20")
        self.assertIn("Bea Example <bea@example.org>", forwarded.to)
        self.assertEqual(forwarded.cc, "Finn Example <finn@example.com>")
        image, pdf = forwarded.files.all()
        with image.file.open("rb") as handle:
            self.assertEqual(handle.read(), IMAGE)
        self.assertTrue(image.is_image)
        self.assertEqual(pdf.name, "Quote 2026-117.pdf")
        # The image where it was, the PDF below
        self.assertIn(
            f"below:\n\n![image001.png](forwarded:{image.key})\n\nTwo changes",
            forwarded.text,
        )
        self.assertTrue(
            forwarded.text.endswith(f"[Quote 2026-117.pdf](forwarded:{pdf.key})")
        )
        self.assertEqual(mail.outbox, [])

    def test_every_shape(self):
        for name in [
            "outlook_de.eml",
            "gmail_en.eml",
            "gmail_de.eml",
            "apple_mail_en.eml",
            "apple_mail_de.eml",
            "html_only.eml",
            "attached.eml",
            "not_forwarded.eml",
        ]:
            with self.subTest(name):
                message = self.receive(sample(name))
                self.assertEqual(message.status, InboundStatus.FORWARDED)
        self.assertEqual(ForwardedMail.objects.filter(user=self.ada).count(), 8)

    def test_externals_forward_too(self):
        pia = external("Pia")
        self.receive(
            sample(
                "gmail_en.eml", replace=[("From: Ada", "From: Pia"), ("ada@", "pia@")]
            )
        )
        self.assertEqual(ForwardedMail.objects.get().user, pia)

    def test_too_large_files_are_left_out_with_a_line(self):
        with patch.object(operations, "MAX_FILE_SIZE", 1000):
            self.receive(sample("outlook_en.eml"))
        forwarded = ForwardedMail.objects.get()
        self.assertEqual(
            [f.name for f in forwarded.files.all()], ["Quote 2026-117.pdf"]
        )
        self.assertIn(
            "An attachment was too large and is not included: image001.png",
            forwarded.text,
        )
        self.assertNotIn("BIWAKFILE", forwarded.text)

    def test_auto_replies_are_dropped(self):
        message = self.receive(
            sample(
                "not_forwarded.eml",
                replace=[
                    ("MIME-Version", "Auto-Submitted: auto-replied\nMIME-Version")
                ],
            )
        )
        self.assertEqual(message.status, InboundStatus.LOOP)
        self.assertFalse(ForwardedMail.objects.exists())

    @override_settings(REPLY_DOMAIN="")
    def test_off_without_the_reply_domain(self):
        message = self.receive(sample("gmail_en.eml"))
        self.assertEqual(message.status, InboundStatus.UNKNOWN_TOKEN)
        self.assertFalse(ForwardedMail.objects.exists())

    def test_receive_mail_command(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "forward.eml"
        path.write_bytes(raw_sample("apple_mail_en.eml"))
        out = io.StringIO()
        call_command("receive_mail", str(path), "--dkim", "pass", stdout=out)
        self.assertEqual(out.getvalue().strip(), "forwarded")
        self.assertEqual(ForwardedMail.objects.get().user, self.ada)


class RefusedTest(ForwardTestCase):
    def assertRefused(self, message, status, to=None):
        self.assertEqual(message.status, status)
        self.assertFalse(ForwardedMail.objects.exists())
        self.assertFalse(ForwardedFile.objects.exists())
        if to is None:
            self.assertEqual(mail.outbox, [])
            return None
        [answer] = mail.outbox
        self.assertEqual(answer.to, [to])
        self.assertEqual(answer.extra_headers["Auto-Submitted"], "auto-replied")
        self.assertNotIn("Reply-To", answer.extra_headers)
        return answer

    def from_(self, address):
        return [("From: Ada Example <ada@example.org>", f"From: Someone <{address}>")]

    def test_clients_are_refused(self):
        message = self.receive(
            sample("gmail_en.eml", replace=self.from_(self.cleo.email))
        )
        answer = self.assertRefused(
            message, InboundStatus.WRONG_SENDER, to=self.cleo.email
        )
        self.assertEqual(answer.subject, "Your forwarded mail couldn't be kept")
        self.assertIn("address of a staff member", answer.body)
        self.assertIn("Fwd: Analytics export", answer.body)

    def test_unknown_senders_are_refused(self):
        message = self.receive(
            sample("outlook_en.eml", replace=self.from_("zoe@example.net"))
        )
        self.assertRefused(message, InboundStatus.WRONG_SENDER, to="zoe@example.net")

    def test_inactive_staff_are_refused(self):
        self.ada.is_active = False
        self.ada.save()
        message = self.receive(sample("gmail_en.eml"))
        self.assertRefused(message, InboundStatus.WRONG_SENDER, to=self.ada.email)

    def test_unconfirmed_staff_address_is_answered_to_them(self):
        self.ada.language = "de"
        self.ada.save()
        message = self.receive(sample("gmail_en.eml", auth=FAIL))
        answer = self.assertRefused(
            message, InboundStatus.UNAUTHENTICATED, to=self.ada.email
        )
        self.assertEqual(
            answer.subject, "Deine weitergeleitete Mail konnte nicht behalten werden"
        )

    def test_unconfirmed_unknown_address_isnt_answered(self):
        message = self.receive(
            sample("gmail_en.eml", replace=self.from_("zoe@example.net"), auth=FAIL)
        )
        self.assertRefused(message, InboundStatus.WRONG_SENDER)

    def test_answers_are_limited_per_sender_and_hour(self):
        replace = self.from_("zoe@example.net")
        with patch.object(operations, "RATE_LIMIT", 2):
            for _i in range(3):
                message = self.receive(sample("gmail_en.eml", replace=replace))
        self.assertEqual(message.status, InboundStatus.RATE_LIMITED)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(InboundMessage.objects.count(), 3)
