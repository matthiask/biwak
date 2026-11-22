"""Reading forwards of Outlook, Gmail and Apple Mail (made-up samples)"""

import datetime as dt

from django.test import SimpleTestCase

from biwak.forwarding.parse import find_header, forward, parse_date
from biwak.forwarding.support import IMAGE, sample


NOV_20 = dt.date(2026, 11, 20)


class ForwardFormatsTest(SimpleTestCase):
    def assertOriginal(self, parsed, *, subject, to, cc="", sent_on=NOV_20):
        self.assertEqual(parsed.subject, subject)
        self.assertEqual(parsed.sender_name, "Dora Example")
        self.assertEqual(parsed.sender_email, "dora@example.com")
        self.assertEqual(parsed.sent_on, sent_on)
        self.assertEqual(parsed.to, to)
        self.assertEqual(parsed.cc, cc)
        # The header block isn't in the text
        self.assertNotIn("dora@example.com", parsed.text)
        self.assertNotIn("Subject:", parsed.text)

    def test_outlook_html_with_inline_image_and_attachment(self):
        parsed = forward(sample("outlook_en.eml"))
        self.assertOriginal(
            parsed,
            subject="Revised quote for the landing page",
            to="Ada Example <ada@example.org>, Bea Example <bea@example.org>",
            cc="Finn Example <finn@example.com>",
        )
        # The forwarder's lines first, the original's HTML as Markdown
        self.assertTrue(parsed.text.startswith("For the website project.\n\nAda\n"))
        self.assertIn("Attached is the **revised quote**.", parsed.text)
        self.assertIn("- the contact form moves to the footer", parsed.text)
        self.assertIn("Kind regards\nDora", parsed.text)
        self.assertNotIn("---", parsed.text)
        image, pdf = parsed.files
        self.assertEqual(image.name, "image001.png")
        self.assertEqual(image.content, IMAGE)
        # Where the image was
        self.assertIn(f"below:\n\n{image.placeholder}\n\nTwo changes", parsed.text)
        self.assertEqual(pdf.name, "Quote 2026-117.pdf")
        self.assertEqual(pdf.content_type, "application/pdf")
        self.assertNotIn(pdf.placeholder, parsed.text)

    def test_outlook_german_signature_logo_left_out(self):
        parsed = forward(sample("outlook_de.eml"))
        self.assertOriginal(
            parsed,
            subject="Termin für den Workshop",
            to="Ada Example <ada@example.org>",
            cc="Finn Example <finn@example.com>",
        )
        # Signatures aren't stripped, small logos aren't files
        self.assertIn("Zur Info\n\nAda Example\nExample Agency", parsed.text)
        self.assertIn("Passt dir der Workshop am *Donnerstag um 14 Uhr*?", parsed.text)
        self.assertEqual(parsed.files, [])

    def test_gmail_quotes_kept_and_attachment(self):
        parsed = forward(sample("gmail_en.eml"))
        self.assertOriginal(
            parsed,
            subject="Analytics export",
            to="Ada Example <ada@example.org>",
            cc="finn@example.com",
        )
        self.assertIn("Can we file this under Website?", parsed.text)
        self.assertIn("Numbers are **up 12%** in November.", parsed.text)
        self.assertIn("> Could you send the numbers for November?", parsed.text)
        self.assertNotIn("Forwarded message", parsed.text)
        # Gmail's attachments have a Content-ID too: still an attachment
        [csv] = parsed.files
        self.assertEqual(csv.name, "analytics-2026-11.csv")

    def test_gmail_german_inline_image(self):
        parsed = forward(sample("gmail_de.eml"))
        self.assertOriginal(
            parsed, subject="Logo-Varianten", to="Ada Example <ada@example.org>"
        )
        [image] = parsed.files
        self.assertIn(f"Varianten:\n\n{image.placeholder}", parsed.text)

    def test_apple_mail_unquotes_the_forward(self):
        parsed = forward(sample("apple_mail_en.eml"))
        self.assertOriginal(
            parsed,
            subject="Broken link in the footer",
            to="Ada Example <ada@example.org>",
        )
        self.assertEqual(
            parsed.text,
            'Please file as a to-do.\n\nHi,\n\nthe "Imprint" link in the'
            " footer goes to a 404.\n\nDora",
        )

    def test_apple_mail_german_inline_image(self):
        parsed = forward(sample("apple_mail_de.eml"))
        self.assertOriginal(
            parsed,
            subject="Fotos vom Shooting",
            to="Ada Example <ada@example.org>, Bea Example <bea@example.org>",
        )
        [image] = parsed.files
        self.assertEqual(image.content_type, "image/jpeg")
        self.assertTrue(parsed.text.startswith("Hallo zusammen"))
        self.assertIn(image.placeholder, parsed.text)

    def test_html_only(self):
        parsed = forward(sample("html_only.eml"))
        self.assertEqual(parsed.subject, "Your hosting renews on 1 December")
        self.assertEqual(parsed.sender_name, "Hosting Example")
        self.assertEqual(parsed.sender_email, "billing@hosting.example.net")
        self.assertEqual(parsed.sent_on, dt.date(2026, 11, 19))
        self.assertEqual(
            parsed.text,
            "Renewal is due, see below.\n\nYour plan **Business** renews on 1"
            " December 2026.\n\nVisit [your account]"
            "(https://hosting.example.net/account) to change it.",
        )

    def test_forwarded_as_attachment(self):
        parsed = forward(sample("attached.eml"))
        self.assertOriginal(
            parsed,
            subject="Contract draft",
            to="Ada Example <ada@example.org>",
            cc="Finn Example <finn@example.com>",
            sent_on=dt.date(2026, 11, 18),
        )
        self.assertTrue(parsed.text.startswith("See the attached mail.\n\nDear Ada,"))
        [docx] = parsed.files
        self.assertEqual(docx.name, "Contract draft.docx")

    def test_not_a_forward_is_taken_as_it_is(self):
        parsed = forward(sample("not_forwarded.eml"))
        self.assertEqual(parsed.subject, "Call Dora about the quote")
        self.assertEqual(parsed.sender_name, "Ada Example")
        self.assertEqual(parsed.sender_email, "ada@example.org")
        self.assertEqual(parsed.sent_on, dt.date(2026, 11, 23))
        self.assertEqual(parsed.to, "")
        self.assertEqual(parsed.text, "Ask about the footer and the contact form.")

    def test_forward_prefixes_go_when_taken_as_it_is(self):
        parsed = forward(
            sample(
                "not_forwarded.eml",
                replace=[("Subject: Call", "Subject: Fwd: WG: Call")],
            )
        )
        self.assertEqual(parsed.subject, "Call Dora about the quote")


class HeaderTest(SimpleTestCase):
    def test_old_outlook(self):
        lines = [
            "See below",
            "",
            "-----Original Message-----",
            "From: Dora Example [mailto:dora@example.com]",
            "Sent: Friday, 20 November 2026 16:42",
            "To: Ada Example",
            "Subject: Quote",
            "",
            "Hi",
        ]
        start, end, fields = find_header(lines)
        self.assertEqual((start, end), (2, 7))
        self.assertEqual(fields["from"], "Dora Example [mailto:dora@example.com]")

    def test_a_from_line_alone_isnt_a_header(self):
        self.assertIsNone(find_header(["From: the start, we wanted", "", "more"]))

    def test_dates(self):
        for value in [
            "Fri, Nov 20, 2026 at 4:42 PM",
            "Fr., 20. Nov. 2026 um 16:42 Uhr",
            "Friday, November 20, 2026 16:42",
            "Freitag, 20. November 2026 16:42",
            "20 November 2026 at 16:42:11 CET",
            "20. November 2026 um 16:42:11 MEZ",
            "20.11.2026 16:42",
            "2026-11-20 16:42",
            "Fri, 20 Nov 2026 16:42:10 +0100",
        ]:
            with self.subTest(value):
                self.assertEqual(parse_date(value), NOV_20)
        for value in ["11/12/2026", "", "yesterday", "31. February 2026"]:
            with self.subTest(value):
                self.assertIsNone(parse_date(value))
