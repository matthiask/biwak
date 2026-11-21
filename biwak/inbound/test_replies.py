import datetime as dt
from unittest.mock import patch

from django.core import mail
from django.utils import timezone

from biwak.activity import mentions
from biwak.activity.mails import send_mails
from biwak.activity.models import Mention, Notification
from biwak.files.models import Attachment
from biwak.inbound import receive as receive_module
from biwak.inbound.models import InboundMessage, InboundStatus
from biwak.inbound.support import ReplyTestCase
from biwak.inbound.support_mails import ReceiveMixin, sample
from biwak.items import operations as ops
from biwak.items.models import Comment
from biwak.projects import operations as project_ops
from biwak.test_utils import organization, person


class EndToEndTest(ReceiveMixin, ReplyTestCase):
    def notify(self):
        """Bea comments, the mails go out"""
        with self.captureOnCommitCallbacks(execute=True):
            ops.add_comment(
                self.todo, author=self.bea, content="The headline is too long."
            )
        with self.captureOnCommitCallbacks(execute=True):
            send_mails(now=timezone.now() + dt.timedelta(minutes=3))
        return {message.to[0]: message for message in mail.outbox}

    def test_replying_to_the_notification_posts_a_comment(self):
        """The whole way: the mail's Reply-To, the reply, the comment"""
        messages = self.notify()
        address = messages[self.ada.email].extra_headers["Reply-To"]
        token = address.removeprefix("r-").split("@")[0]
        message = self.receive(sample("gmail_en.eml", token))
        self.assertEqual(message.status, InboundStatus.POSTED)
        comment = self.comments()[-1]
        self.assertEqual(comment.author, self.ada)
        self.assertEqual(message.comment, comment)
        self.assertTrue(comment.content.startswith("Thanks, I'll update the copy"))

    def test_the_reply_reads_the_repliers_notifications_of_the_item(self):
        """Reading by acting (specs/lantern.md): the mail reply goes through
        ``add_comment()``; Cleo's notifications stay unread"""
        from biwak.activity import lantern

        messages = self.notify()
        token = (
            messages[self.ada.email]
            .extra_headers["Reply-To"]
            .removeprefix("r-")
            .split("@")[0]
        )
        self.assertEqual(lantern.unread_count(self.ada), 1)
        self.assertEqual(lantern.unread_count(self.cleo), 1)
        self.receive(sample("gmail_en.eml", token))
        self.assertEqual(lantern.unread_count(self.ada), 0)
        self.assertEqual(lantern.unread_count(self.cleo), 1)


class MailClientsTest(ReceiveMixin, ReplyTestCase):
    """What people wrote, without quotes and signatures, from the mail
    clients they use"""

    def test_staff(self):
        expected = {
            "gmail_en.eml": "Thanks, I'll update the copy tomorrow.\n\n"
            f"{mentions.syntax(self.bea)} can you check the images?",
            "gmail_de.eml": "Danke, ich kümmere mich morgen darum.\n\nGrüße\nAda",
            "outlook_en.eml": "Looks good to me, go ahead.\n\nBest regards\nAda",
            "outlook_de.eml": "Passt so, danke! Die Bilder schicke ich später."
            "\n\nFreundliche Grüße\nAda Example",
            "apple_mail_de.eml": "Ich kürze die Überschrift.",
            "outlook_android_en.eml": "Ok, thanks!",
        }
        for name, content in expected.items():
            with self.subTest(name):
                message = self.receive(sample(name, self.token()))
                self.assertEqual(message.status, InboundStatus.POSTED)
                self.assertEqual(message.comment.content, content)
                self.assertEqual(message.comment.author, self.ada)

    def test_clients_phones(self):
        expected = {
            "iphone_de.eml": "Für uns ist die kürzere Variante gut.",
            "outlook_ios_de.eml": "Gerne, bis Montag & schönes Wochenende!",
        }
        for name, content in expected.items():
            with self.subTest(name):
                message = self.receive(sample(name, self.token(self.cleo)))
                self.assertEqual(message.status, InboundStatus.POSTED)
                self.assertEqual(message.comment.content, content)
                self.assertEqual(message.comment.author, self.cleo)

    def test_mentions_resolved_and_notified(self):
        with self.captureOnCommitCallbacks(execute=True):
            message = self.receive(sample("gmail_en.eml", self.token()))
        self.assertTrue(
            Mention.objects.filter(
                user=self.bea, comment=message.comment, item=self.todo
            ).exists()
        )
        self.assertTrue(Notification.objects.filter(user=self.bea).exists())

    def test_clients_mention_members_only(self):
        """Not staff who see the project because it's all-access
        (specs/access.md)"""
        dora = person("Dora")
        mail = sample(
            "iphone_de.eml",
            self.token(self.cleo),
            replace=[("F=C3=BCr uns", "@Dora @dora@example.org @Ada: f=C3=BCr uns")],
        )
        with self.captureOnCommitCallbacks(execute=True):
            message = self.receive(mail)
        self.assertTrue(
            message.comment.content.startswith("@Dora @dora@example.org [@Ada"),
            message.comment.content,
        )
        self.assertFalse(Mention.objects.filter(user=dora).exists())
        self.assertFalse(Notification.objects.filter(user=dora).exists())
        self.assertTrue(Mention.objects.filter(user=self.ada).exists())

    def test_attachments(self):
        message = self.receive(sample("apple_mail_en.eml", self.token()))
        attachment = Attachment.objects.get()
        self.assertEqual(
            (attachment.name, attachment.item, attachment.uploaded_by),
            ("Brief v2.pdf", self.todo, self.ada),
        )
        self.assertEqual(attachment.content_type, "application/pdf")
        self.assertTrue(attachment.file.read().startswith(b"%PDF-1.4"))
        self.assertEqual(
            message.comment.content,
            "Here’s the brief with the new copy.\n\n"
            f"[Brief v2.pdf](attachment:{attachment.key})",
        )

    def test_inline_image_from_a_phone(self):
        message = self.receive(sample("iphone_en.eml", self.token()))
        attachment = Attachment.objects.get()
        self.assertEqual(attachment.name, "IMG_0042.png")
        self.assertEqual(attachment.item, self.todo)
        self.assertEqual(
            message.comment.content,
            "Will do, screenshot attached\n\n"
            f"![IMG_0042.png](attachment:{attachment.key})",
        )

    def test_attachments_too_large_are_left_out(self):
        with patch.object(receive_module, "MAX_ATTACHMENT_SIZE", 50):
            message = self.receive(sample("apple_mail_en.eml", self.token()))
        self.assertEqual(message.status, InboundStatus.POSTED)
        self.assertFalse(Attachment.objects.exists())
        # The comment says so; no mail goes back
        self.assertEqual(
            message.comment.content,
            "Here’s the brief with the new copy.\n\n"
            "An attachment was too large and is not included: Brief v2.pdf",
        )
        self.assertEqual(mail.outbox, [])
        self.assertIn("Brief v2.pdf", message.error)

    def test_small_inline_images_are_left_out(self):
        message = self.receive(sample("outlook_logo.eml", self.token()))
        self.assertEqual(
            sorted(a.name for a in Attachment.objects.all()),
            ["Note.pdf", "Screenshot.png"],
        )
        self.assertEqual(message.status, InboundStatus.POSTED)
        self.assertNotIn("](attachment:", message.comment.content.split("[cid:")[0])
        self.assertEqual(message.comment.content.count("](attachment:"), 2)
        self.assertIn("Screenshot.png", message.comment.content)

    def test_only_quotes_posts_nothing(self):
        message = self.receive(
            sample(
                "gmail_de.eml",
                self.token(),
                replace=[
                    ("Danke, ich k=C3=BCmmere mich morgen darum.", ""),
                    ("Gr=C3=BC=C3=9Fe\nAda", ""),
                ],
            )
        )
        self.assertEqual(message.status, InboundStatus.EMPTY)
        self.assertEqual(self.comments(), [])
        self.assertEqual(mail.outbox, [])


class SenderTest(ReceiveMixin, ReplyTestCase):
    """The token alone isn't enough: the From address must be the token's
    person's, and the receiving server must confirm it"""

    def test_forwarded_and_answered_by_somebody_else(self):
        message = self.receive(sample("forwarded_en.eml", self.token()))
        self.assertEqual(message.status, InboundStatus.WRONG_SENDER)
        self.assertEqual(self.comments(), [])
        # Dan's server confirmed his address: he's told, without anything
        # about the item
        [answer] = mail.outbox
        self.assertEqual(answer.to, ["dan@example.net"])
        self.assertEqual(answer.subject, "Your reply couldn't be posted")
        self.assertIn("only posted when they come from the address", answer.body)
        self.assertNotIn("headline is too long", answer.body)
        self.assertEqual(answer.extra_headers["Auto-Submitted"], "auto-replied")
        self.assertEqual(
            answer.extra_headers["In-Reply-To"], "<CAF1x+forwarded-1@mail.example.com>"
        )
        self.assertNotIn("Reply-To", answer.extra_headers)

    def test_unconfirmed_wrong_sender_is_answered_to_the_token_person(self):
        """Never to an address nobody confirmed: it may be impersonated"""
        failed = {"spf": "fail", "dkim": "fail", "dmarc": "fail"}
        message = self.receive(sample("forwarded_en.eml", self.token(), auth=failed))
        self.assertEqual(message.status, InboundStatus.WRONG_SENDER)
        self.assertEqual([m.to for m in mail.outbox], [[self.ada.email]])

    def test_spoofed_from_with_failed_dmarc(self):
        """The mail's own Authentication-Results header says "pass": only
        the receiving server counts"""
        failed = {"spf": "pass", "dkim": "fail", "dmarc": "fail"}
        message = self.receive(sample("spoofed.eml", self.token(), auth=failed))
        self.assertEqual(message.status, InboundStatus.UNAUTHENTICATED)
        self.assertEqual(self.comments(), [])
        [answer] = mail.outbox
        self.assertEqual(answer.to, [self.ada.email])
        self.assertIn("couldn't confirm", answer.body)

    def test_which_results_count(self):
        cases = [
            ({"spf": "pass", "dkim": "pass", "dmarc": "pass"}, True),
            # No DMARC policy, but DKIM of the From domain
            ({"spf": "gray", "dkim": "pass", "dmarc": "gray"}, True),
            ({"spf": "fail", "dkim": "fail", "dmarc": "pass"}, True),
            # SPF alone: about the envelope sender, not the From address
            ({"spf": "pass", "dkim": "gray", "dmarc": "gray"}, False),
            ({"spf": "pass", "dkim": "fail", "dmarc": "fail"}, False),
            ({"spf": "unknown", "dkim": "unknown", "dmarc": "unknown"}, False),
            ({"spf": "pass", "dkim": "processing_failed", "dmarc": "gray"}, False),
        ]
        for auth, posted in cases:
            with self.subTest(auth):
                message = self.receive(sample("spoofed.eml", self.token(), auth=auth))
                self.assertEqual(message.status == InboundStatus.POSTED, posted)

    def test_address_in_the_display_name(self):
        message = self.receive(sample("display_name.eml", self.token()))
        self.assertEqual(message.status, InboundStatus.WRONG_SENDER)
        self.assertEqual(message.sender, "mallory@example.net")
        self.assertEqual([m.to for m in mail.outbox], [["mallory@example.net"]])

    def test_two_from_headers(self):
        message = self.receive(
            sample(
                "spoofed.eml",
                self.token(),
                replace=[("From: ", "From: <ada@example.org>\nFrom: ")],
            )
        )
        self.assertEqual(message.status, InboundStatus.WRONG_SENDER)

    def test_two_addresses_in_from(self):
        message = self.receive(
            sample(
                "spoofed.eml",
                self.token(),
                replace=[("<ada@example.org>", "<ada@example.org>, <bea@example.org>")],
            )
        )
        self.assertEqual(message.status, InboundStatus.WRONG_SENDER)

    def test_from_address_case_doesnt_matter(self):
        message = self.receive(sample("outlook_de.eml", self.token()))
        self.assertEqual(message.status, InboundStatus.POSTED)

    def test_another_persons_token(self):
        """Cleo's own address, but Ada's token"""
        message = self.receive(sample("iphone_de.eml", self.token(self.ada)))
        self.assertEqual(message.status, InboundStatus.WRONG_SENDER)
        self.assertEqual(self.comments(), [])

    def test_unconfirmed_and_deactivated_not_answered(self):
        self.ada.is_active = False
        self.ada.save()
        failed = {"spf": "fail", "dkim": "fail", "dmarc": "fail"}
        message = self.receive(sample("spoofed.eml", self.token(), auth=failed))
        self.assertEqual(message.status, InboundStatus.UNAUTHENTICATED)
        self.assertEqual(mail.outbox, [])

    def test_unknown_charset(self):
        message = self.receive(
            sample(
                "spoofed.eml",
                self.token(),
                replace=[('charset="UTF-8"', 'charset="x-made-up"')],
            )
        )
        self.assertEqual(message.status, InboundStatus.POSTED)
        self.assertEqual(
            message.comment.content, "Please send the invoice to the new address."
        )

    def test_answered_once_per_token(self):
        token = self.token()
        self.receive(sample("forwarded_en.eml", token))
        self.receive(sample("display_name.eml", token))
        self.assertEqual(len(mail.outbox), 1)
        token.refresh_from_db()
        self.assertIsNotNone(token.error_sent_at)
        # Another token: answered again
        self.receive(sample("forwarded_en.eml", self.token()))
        self.assertEqual(len(mail.outbox), 2)


class VisibilityTest(ReceiveMixin, ReplyTestCase):
    """A person replies only to what they can see now, not when the mail
    was sent"""

    def assert_no_access(self, token, name="iphone_de.eml"):
        message = self.receive(sample(name, token))
        self.assertEqual(message.status, InboundStatus.NO_ACCESS)
        self.assertEqual(self.comments(), [])
        [answer] = mail.outbox
        self.assertEqual(answer.to, [token.user.email])
        self.assertIn("can't see or answer", answer.body)
        # Nothing about the item but the subject they wrote
        self.assertNotIn("too long", answer.body)
        self.assertNotIn("/todos/", answer.body)
        return message

    def test_client_replying_to_a_visible_item(self):
        message = self.receive(sample("iphone_de.eml", self.token(self.cleo)))
        self.assertEqual(message.status, InboundStatus.POSTED)
        self.assertTrue(message.comment.item.is_client_visible)

    def test_list_made_internal_after_the_mail(self):
        token = self.token(self.cleo)
        ops.set_visibility(self.shared, visible=False, actor=self.bea)
        self.assert_no_access(token)

    def test_to_do_moved_to_an_internal_list(self):
        token = self.token(self.cleo)
        internal = ops.create_list(
            project=self.project, title="Internal", creator=self.bea
        )
        ops.move_todo(self.todo, todolist=internal, actor=self.bea)
        self.assert_no_access(token)

    def test_removed_from_the_project(self):
        token = self.token(self.cleo)
        project_ops.remove_member(self.project, self.cleo, actor=self.bea)
        self.assert_no_access(token)

    def test_staff_now_a_partner_and_not_a_member(self):
        """Ada saw the all-access project as own staff;
        as a partner she sees only the projects she's a member of"""
        token = self.token()
        project_ops.remove_member(self.project, self.ada, actor=self.bea)
        self.ada.organization = organization("Example Partner Agency")
        self.ada.save()
        self.assert_no_access(token, "gmail_en.eml")

    def test_staff_removed_from_a_limited_project(self):
        self.project.is_all_access = False
        self.project.save()
        token = self.token(self.ada)
        project_ops.remove_member(self.project, self.ada, actor=self.bea)
        self.assert_no_access(token, "gmail_en.eml")

    def test_trashed(self):
        token = self.token(self.ada)
        ops.trash(self.todo, actor=self.bea)
        self.assert_no_access(token, "gmail_en.eml")

    def test_deactivated(self):
        token = self.token(self.cleo)
        self.cleo.is_active = False
        self.cleo.save()
        self.assert_no_access(token)

    def test_not_commentable(self):
        """Lists have no comments"""
        token = self.token(self.ada, self.shared)
        self.assert_no_access(token, "gmail_en.eml")
        self.assertFalse(Comment.objects.exists())


class TokenTest(ReceiveMixin, ReplyTestCase):
    def test_expired(self):
        token = self.token(expires_at=timezone.now() - dt.timedelta(minutes=1))
        message = self.receive(sample("gmail_en.eml", token))
        self.assertEqual(message.status, InboundStatus.EXPIRED)
        self.assertEqual(self.comments(), [])
        [answer] = mail.outbox
        self.assertEqual(answer.to, [self.ada.email])
        self.assertIn("isn't valid any more", answer.body)

    def test_valid_for_six_months(self):
        token = self.token()
        later = token.created_at + dt.timedelta(days=180)
        message = self.receive(sample("gmail_en.eml", token), now=later)
        self.assertEqual(message.status, InboundStatus.POSTED)
        message = self.receive(
            sample("gmail_de.eml", token), now=later + dt.timedelta(days=5)
        )
        self.assertEqual(message.status, InboundStatus.EXPIRED)

    def test_revoked(self):
        token = self.token(revoked_at=timezone.now())
        message = self.receive(sample("gmail_en.eml", token))
        self.assertEqual(message.status, InboundStatus.EXPIRED)

    def test_unknown_token(self):
        message = self.receive(sample("gmail_en.eml", "zzzzzzzzzzzzzzzzzzzz"))
        self.assertEqual(message.status, InboundStatus.UNKNOWN_TOKEN)
        self.assertEqual(mail.outbox, [])

    def test_other_domain(self):
        message = self.receive(
            sample(
                "gmail_en.eml",
                self.token(),
                replace=[("@reply.example.org", "@reply.example.net")],
            )
        )
        self.assertEqual(message.status, InboundStatus.UNKNOWN_TOKEN)

    def test_uppercased_by_a_server(self):
        token = self.token()
        message = self.receive(
            sample(
                "gmail_en.eml",
                token,
                replace=[(f"r-{token.token}", f"R-{token.token.upper()}")],
            )
        )
        self.assertEqual(message.status, InboundStatus.POSTED)

    def test_token_in_cc(self):
        token = self.token()
        message = self.receive(
            sample(
                "gmail_en.eml",
                token,
                replace=[
                    (
                        f'To: "Bea Example (Biwak)" <r-{token.token}',
                        f"To: bea@example.org\nCc: <r-{token.token}",
                    )
                ],
            )
        )
        self.assertEqual(message.status, InboundStatus.POSTED)


class LoopTest(ReceiveMixin, ReplyTestCase):
    """Auto-replies and bounces are dropped, never answered"""

    def test_samples(self):
        for name in ("out_of_office_en.eml", "out_of_office_de.eml", "bounce.eml"):
            with self.subTest(name):
                token = self.token()
                message = self.receive(sample(name, token))
                self.assertEqual(message.status, InboundStatus.LOOP)
                token.refresh_from_db()
                self.assertIsNone(token.error_sent_at)
        self.assertEqual(self.comments(), [])
        self.assertEqual(mail.outbox, [])

    def test_headers(self):
        cases = [
            ("Auto-Submitted: auto-generated", True),
            ("Auto-Submitted: auto-replied", True),
            ("Auto-Submitted: no", False),
            ("Precedence: bulk", True),
            ("Precedence: junk", True),
            ("Precedence: list", True),
            ("Precedence: first-class", False),
            ("X-Autoreply: yes", True),
            ("X-Autorespond: Out of office", True),
        ]
        for header, loop in cases:
            with self.subTest(header):
                message = self.receive(
                    sample(
                        "gmail_en.eml",
                        self.token(),
                        replace=[
                            ("MIME-Version: 1.0\n", f"MIME-Version: 1.0\n{header}\n")
                        ],
                    )
                )
                self.assertEqual(message.status == InboundStatus.LOOP, loop)

    def test_empty_envelope_sender(self):
        message = self.receive(
            sample(
                "gmail_en.eml",
                self.token(),
                replace=[("Return-Path: <ada@example.org>", "Return-Path: <>")],
            )
        )
        self.assertEqual(message.status, InboundStatus.LOOP)

    def test_the_receiving_servers_return_path_counts(self):
        """The topmost; one further down was written by the sender"""
        message = self.receive(
            sample(
                "gmail_en.eml",
                self.token(),
                replace=[
                    ("MIME-Version: 1.0\n", "MIME-Version: 1.0\nReturn-Path: <>\n")
                ],
            )
        )
        self.assertEqual(message.status, InboundStatus.POSTED)

    def test_wrong_sender_auto_reply_not_answered(self):
        message = self.receive(
            sample(
                "out_of_office_en.eml",
                self.token(),
                replace=[("ada@example.org", "dan@example.net")],
            )
        )
        self.assertEqual(message.status, InboundStatus.LOOP)
        self.assertEqual(mail.outbox, [])


class RateLimitTest(ReceiveMixin, ReplyTestCase):
    def test_twenty_per_token_and_hour(self):
        token = self.token()
        now = timezone.now()
        for minute in range(20):
            message = self.receive(
                sample("gmail_en.eml", token), now=now + dt.timedelta(minutes=minute)
            )
            self.assertEqual(message.status, InboundStatus.POSTED)
        message = self.receive(
            sample("gmail_en.eml", token), now=now + dt.timedelta(minutes=30)
        )
        self.assertEqual(message.status, InboundStatus.RATE_LIMITED)
        self.assertEqual(len(self.comments()), 20)
        self.assertEqual(mail.outbox, [])
        # Another token isn't limited
        message = self.receive(
            sample("gmail_en.eml", self.token()), now=now + dt.timedelta(minutes=30)
        )
        self.assertEqual(message.status, InboundStatus.POSTED)
        # An hour after the first ones
        message = self.receive(
            sample("gmail_en.eml", token), now=now + dt.timedelta(minutes=61)
        )
        self.assertEqual(message.status, InboundStatus.POSTED)

    def test_rejected_mails_count_too(self):
        token = self.token()
        for _i in range(20):
            self.receive(sample("forwarded_en.eml", token))
        message = self.receive(sample("gmail_en.eml", token))
        self.assertEqual(message.status, InboundStatus.RATE_LIMITED)


class IdempotencyTest(ReceiveMixin, ReplyTestCase):
    def test_received_twice(self):
        token = self.token()
        first = self.receive(sample("gmail_en.eml", token), provider_id="abc")
        self.assertEqual(first.status, InboundStatus.POSTED)
        self.assertIsNone(
            self.receive(sample("gmail_en.eml", token), provider_id="abc")
        )
        self.assertEqual(len(self.comments()), 1)
        self.assertEqual(InboundMessage.objects.count(), 1)

    def test_rejection_not_repeated(self):
        token = self.token()
        self.receive(sample("forwarded_en.eml", token), provider_id="abc")
        token.error_sent_at = None
        token.save()
        self.assertIsNone(
            self.receive(sample("forwarded_en.eml", token), provider_id="abc")
        )
        self.assertEqual(len(mail.outbox), 1)
