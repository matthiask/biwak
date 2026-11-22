from email.message import EmailMessage

from django.test import SimpleTestCase

from biwak.inbound import providers


def mail_with(*parts):
    message = EmailMessage()
    message["From"] = "Ada Example <ada@example.com>"
    message["To"] = "r-token@reply.example.org"
    message["Subject"] = "Re: Brief"
    message.set_content("See attached.")
    for name, content, disposition, cid in parts:
        message.add_attachment(
            content,
            maintype="application",
            subtype="pdf",
            filename=name,
            disposition=disposition,
            cid=cid,
        )
    return message.as_bytes()


class AttachmentsTest(SimpleTestCase):
    def test_a_small_attachment_with_a_content_id_is_kept(self):
        """Gmail gives ordinary attachments a Content-ID too: only inline
        parts are logos and signatures left out"""
        found = providers.parse(
            mail_with(("Note.pdf", b"%PDF small", "attachment", "<note@mail>"))
        )
        self.assertEqual([a.name for a in found.attachments], ["Note.pdf"])

    def test_a_small_inline_part_is_left_out(self):
        found = providers.parse(
            mail_with(("logo.pdf", b"%PDF small", "inline", "<logo@mail>"))
        )
        self.assertEqual(found.attachments, [])
