from django.test import SimpleTestCase

from biwak.inbound.strip import html_to_text, strip_text


class StripTest(SimpleTestCase):
    def test_reply_starting_like_a_quote_header(self):
        self.assertEqual(
            strip_text("On it, will do.\n\nAm Montag geht's los.\n"),
            "On it, will do.\n\nAm Montag geht's los.",
        )

    def test_signature_delimiter(self):
        self.assertEqual(
            strip_text("Fine by me.\n\n-- \nAda Example\nExample Ltd\n"), "Fine by me."
        )

    def test_quote_header_wrapped(self):
        self.assertEqual(
            strip_text(
                "Yes.\n\nOn Fri, Nov 20, 2026 at 10:02 AM Bea Example (Biwak)\n"
                "<biwak@example.org>\nwrote:\n\n> Hello\n"
            ),
            "Yes.",
        )

    def test_original_message(self):
        for separator in (
            "-----Original Message-----",
            "-----Ursprüngliche Nachricht-----",
            "---------- Forwarded message ---------",
            "Begin forwarded message:",
        ):
            with self.subTest(separator):
                self.assertEqual(
                    strip_text(f"Done.\n\n{separator}\nFrom: Biwak\nHello"), "Done."
                )

    def test_phone_signatures(self):
        for signature in (
            "Sent from my iPhone",
            "Sent from my Galaxy",
            "Von meinem iPhone gesendet",
            "Gesendet von meinem Android-Telefon",
            "Get Outlook for iOS",
        ):
            with self.subTest(signature):
                self.assertEqual(strip_text(f"Okay\n\n{signature}\n"), "Okay")

    def test_markdown_survives(self):
        text = "- one\n- two\n\n**bold** and `code`"
        self.assertEqual(strip_text(text), text)

    def test_html(self):
        self.assertEqual(
            html_to_text(
                "<html><head><style>p{}</style></head><body><p>One &amp; two</p>"
                "<div>Three<br>Four</div><blockquote>Quoted</blockquote></body></html>"
            ),
            "One & two\n\nThree\nFour",
        )
