import datetime as dt
import zoneinfo
from unittest.mock import patch

from django.core import mail
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from biwak.accounts.models import MailDelivery, NotificationLevel
from biwak.activity import lantern, mails as mails_module, mentions
from biwak.activity.mails import send_mails, unsubscribe_token
from biwak.activity.models import Action, Event, Notification, Subscription
from biwak.activity.operations import record, subscribe
from biwak.files import attachments
from biwak.items import operations as ops
from biwak.items.models import Item
from biwak.outbox import sending as outbox
from biwak.outbox.models import OutgoingMail
from biwak.reactions.operations import add_reaction
from biwak.test_utils import person, project


ZURICH = zoneinfo.ZoneInfo("Europe/Zurich")


@override_settings(
    BASE_URL="https://biwak.example.org", DEFAULT_FROM_EMAIL="biwak@example.org"
)
class MailsBase(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.bob, self.cleo])
        self.shared = ops.create_list(
            project=self.project, title="Shared", creator=self.ada, visible=True
        )
        self.internal = ops.create_list(
            project=self.project, title="Internal", creator=self.ada
        )
        self.todo = ops.create_todo(
            todolist=self.shared,
            title="Order the tent",
            creator=self.ada,
            notes="Two **poles**",
        )
        subscribe(self.bob, self.todo)

    def act(self, run):
        with self.captureOnCommitCallbacks(execute=True):
            run()

    def send(self, now):
        with self.captureOnCommitCallbacks(execute=True):
            return send_mails(now=now)


class MailsTest(MailsBase):
    def test_merged_after_ten_minutes(self):
        """Mails wait 10 minutes after the newest change (decided
        2026-11-21: urgent things get a call; the lantern is immediate)"""
        self.act(lambda: ops.add_comment(self.todo, author=self.ada, content="One"))
        self.act(
            lambda: ops.add_comment(
                self.todo,
                author=self.cleo,
                content=f"Two, {mentions.syntax(self.bob)}",
            )
        )
        now = timezone.now()
        self.assertEqual(self.send(now + dt.timedelta(minutes=9)), 0)
        self.assertEqual(lantern.unread_count(self.bob), 1)
        self.assertEqual(self.send(now + dt.timedelta(minutes=11)), 2)
        # Ada gets Cleo's comment, Bob both in one mail
        self.assertEqual(len(mail.outbox), 2)
        message = next(m for m in mail.outbox if m.to == [self.bob.email])
        self.assertEqual(message.subject, "[Website] Order the tent")
        self.assertEqual(
            message.from_email, '"Cleo Example (Biwak)" <biwak@example.org>'
        )
        self.assertTrue(message.body.startswith("Clients can see this."))
        self.assertIn("Ada Example commented:\n\nOne", message.body)
        self.assertIn("Two, @Bob", message.body)
        self.assertIn("Two **poles**", message.body)
        self.assertIn(f"https://biwak.example.org/todos/{self.todo.pk}/", message.body)
        html = message.alternatives[0].content
        self.assertIn("<strong>poles</strong>", html)
        self.assertIn('<span class="wb-mention" title="Bob Example">@Bob</span>', html)
        thread = f"<item-{self.todo.pk}@biwak.example.org>"
        self.assertEqual(message.extra_headers["In-Reply-To"], thread)
        self.assertEqual(message.extra_headers["References"], thread)
        self.assertIn("@biwak.example.org>", message.extra_headers["Message-ID"])
        self.assertEqual(
            message.extra_headers["List-Unsubscribe-Post"],
            "List-Unsubscribe=One-Click",
        )
        self.assertEqual(message.extra_headers["Auto-Submitted"], "auto-generated")
        self.assertFalse(Notification.objects.filter(sent_at__isnull=True).exists())
        # Nothing twice
        self.assertEqual(self.send(now + dt.timedelta(minutes=20)), 0)

    def test_newest_change_delays(self):
        self.act(lambda: ops.add_comment(self.todo, author=self.ada, content="One"))
        Notification.objects.update(created_at=timezone.now() - dt.timedelta(minutes=5))
        self.act(lambda: ops.add_comment(self.todo, author=self.ada, content="Two"))
        self.assertEqual(self.send(timezone.now()), 0)
        self.assertEqual(self.send(timezone.now() + dt.timedelta(minutes=11)), 1)
        self.assertIn("One", mail.outbox[0].body)
        self.assertIn("Two", mail.outbox[0].body)

    def test_internal_items_not_mailed_to_clients(self):
        """Access is checked again when sending"""
        subscribe(self.cleo, self.todo)
        self.act(lambda: ops.add_comment(self.todo, author=self.ada, content="Hi"))
        self.act(lambda: ops.set_visibility(self.shared, visible=False, actor=self.ada))
        self.send(timezone.now() + dt.timedelta(minutes=11))
        self.assertEqual([m.to for m in mail.outbox], [[self.bob.email]])
        self.assertFalse(Notification.objects.filter(user=self.cleo).exists())
        self.assertNotIn("Clients can see this", mail.outbox[0].body)

    def test_internal_event_not_mailed_to_clients_after_the_item_became_visible(self):
        """A comment written while the list was internal, notified after
        another request made it visible"""
        todo = ops.create_todo(
            todolist=self.internal, title="Raise the rate", creator=self.ada
        )
        subscribe(self.cleo, todo)
        with self.captureOnCommitCallbacks(execute=False) as pending:
            ops.add_comment(todo, author=self.ada, content="Secret")
        self.act(
            lambda: ops.set_visibility(self.internal, visible=True, actor=self.ada)
        )
        for callback in pending:
            callback()
        self.assertFalse(
            Notification.objects.filter(
                user=self.cleo, event__action=Action.COMMENTED
            ).exists()
        )
        self.send(timezone.now() + dt.timedelta(minutes=11))
        self.assertFalse([
            m for m in mail.outbox if "Secret" in m.body and self.cleo.email in m.to
        ])

    def test_existing_notification_of_an_internal_event_not_mailed(self):
        """The second guard: a notification which exists anyway, mailed
        each or in a digest"""
        todo = ops.create_todo(
            todolist=self.internal, title="Raise the rate", creator=self.ada
        )
        subscribe(self.cleo, todo)
        self.act(lambda: ops.add_comment(todo, author=self.ada, content="Secret"))
        self.act(
            lambda: ops.set_visibility(self.internal, visible=True, actor=self.ada)
        )
        event = Event.objects.get(item=todo, action=Action.COMMENTED)
        self.assertFalse(event.is_client_visible)
        for delivery in (MailDelivery.EACH, MailDelivery.DIGEST):
            self.cleo.mail_delivery = delivery
            self.cleo.save()
            Notification.objects.create(user=self.cleo, event=event)
            # After the next digest, whatever the time of day
            tomorrow = timezone.localtime() + dt.timedelta(days=1)
            self.send(tomorrow.replace(hour=7, minute=11))
            self.assertFalse([
                m for m in mail.outbox if "Secret" in m.body and self.cleo.email in m.to
            ])
            self.assertFalse(
                Notification.objects.filter(user=self.cleo, event=event).exists()
            )

    def test_level_changed_before_sending(self):
        """Subscribed means told (specs/notifications.md, "Subscriptions"): a level
        changed since doesn't hold the mail back"""
        self.act(lambda: ops.add_comment(self.todo, author=self.ada, content="Hi"))
        self.bob.notification_level = NotificationLevel.NOTHING
        self.bob.save()
        self.assertEqual(self.send(timezone.now() + dt.timedelta(minutes=11)), 1)

    def test_deactivated_before_sending(self):
        """Inactive people get nothing; their notifications are deleted"""
        self.act(lambda: ops.add_comment(self.todo, author=self.ada, content="Hi"))
        self.assertTrue(Notification.objects.filter(user=self.bob).exists())
        self.bob.is_active = False
        self.bob.save()
        self.assertEqual(self.send(timezone.now() + dt.timedelta(minutes=11)), 0)
        self.assertEqual(mail.outbox, [])
        self.assertFalse(Notification.objects.filter(user=self.bob).exists())

    def test_failed_sending_retries(self):
        """The outbox has the mail (specs/mail-sending.md): the notifications
        are sent, the mail goes out with a later try"""
        self.act(lambda: ops.add_comment(self.todo, author=self.ada, content="Hi"))
        later = timezone.now() + dt.timedelta(minutes=11)
        with (
            patch.object(
                mail.mailers.default.__class__, "send_messages", side_effect=OSError
            ),
            self.assertLogs("biwak.outbox.sending", "WARNING"),
        ):
            self.assertEqual(self.send(later), 1)
        self.assertEqual(mail.outbox, [])
        self.assertFalse(Notification.objects.filter(sent_at__isnull=True).exists())
        self.assertEqual(self.send(later), 0)
        with self.captureOnCommitCallbacks(execute=True):
            outbox.retry(now=timezone.now() + dt.timedelta(minutes=2))
        self.assertEqual([m.to for m in mail.outbox], [[self.bob.email]])

    def test_failed_building_retries(self):
        """A mail which can't be built leaves its notifications unsent"""
        self.act(lambda: ops.add_comment(self.todo, author=self.ada, content="Hi"))
        later = timezone.now() + dt.timedelta(minutes=11)
        with (
            patch.object(mails_module, "item_mail", side_effect=ValueError),
            self.assertLogs("biwak.activity.mails", "ERROR"),
        ):
            self.assertEqual(self.send(later), 0)
        self.assertFalse(OutgoingMail.objects.exists())
        self.assertTrue(Notification.objects.filter(sent_at__isnull=True).exists())
        self.assertEqual(self.send(later), 1)

    def test_in_the_outbox_with_the_notifications(self):
        """Queued in the transaction which marks the notifications sent:
        both or neither (no mail lost to a crash in between)"""
        self.act(lambda: ops.add_comment(self.todo, author=self.ada, content="Hi"))
        with self.captureOnCommitCallbacks() as callbacks:
            send_mails(now=timezone.now() + dt.timedelta(minutes=11))
        (row,) = OutgoingMail.objects.all()
        self.assertEqual(row.kind, "notification")
        self.assertEqual(row.recipients, [self.bob.email])
        self.assertFalse(Notification.objects.filter(sent_at=None).exists())
        self.assertEqual(mail.outbox, [])
        for callback in callbacks:
            callback()
        self.assertEqual(len(mail.outbox), 1)
        row.refresh_from_db()
        self.assertIsNotNone(row.sent_at)
        self.assertIsNone(row.message)

    def test_digest(self):
        self.bob.mail_delivery = MailDelivery.DIGEST
        self.bob.save()
        other = ops.create_todo(todolist=self.internal, title="Pack", creator=self.ada)
        subscribe(self.bob, other)
        self.act(lambda: ops.add_comment(self.todo, author=self.ada, content="One"))
        self.act(lambda: ops.add_comment(other, author=self.ada, content="Two"))
        evening = dt.datetime(2026, 11, 19, 22, 0, tzinfo=ZURICH)
        Notification.objects.update(created_at=evening)
        # Not before 07:00, not with each change
        self.assertEqual(self.send(dt.datetime(2026, 11, 20, 6, 59, tzinfo=ZURICH)), 0)
        # Today's wait for tomorrow
        self.act(lambda: ops.add_comment(other, author=self.ada, content="Today"))
        Notification.objects.filter(created_at__gt=evening).update(
            created_at=dt.datetime(2026, 11, 20, 6, 30, tzinfo=ZURICH)
        )
        self.assertEqual(self.send(dt.datetime(2026, 11, 20, 7, 0, tzinfo=ZURICH)), 1)
        message = mail.outbox[0]
        self.assertEqual(message.subject, "[Biwak] What happened on 19. November 2026")
        self.assertEqual(message.from_email, "Biwak <biwak@example.org>")
        self.assertIn("== Website ==", message.body)
        self.assertIn("One", message.body)
        self.assertIn("Two", message.body)
        self.assertNotIn("Today", message.body)
        self.assertEqual(message.body.count("Clients can see this."), 1)
        self.assertNotIn("List-Unsubscribe-Post", message.extra_headers)
        self.assertEqual(
            message.extra_headers["List-Unsubscribe"],
            "<https://biwak.example.org/accounts/settings/>",
        )
        self.assertEqual(message.extra_headers["Auto-Submitted"], "auto-generated")
        self.assertEqual(Notification.objects.filter(sent_at=None).count(), 1)
        self.assertEqual(self.send(dt.datetime(2026, 11, 20, 7, 1, tzinfo=ZURICH)), 0)

    def test_digest_of_several_days(self):
        """After a downtime, or switching to digests: the subject names the
        days it covers"""
        self.bob.mail_delivery = MailDelivery.DIGEST
        self.bob.save()
        self.act(lambda: ops.add_comment(self.todo, author=self.ada, content="One"))
        Notification.objects.update(
            created_at=dt.datetime(2026, 11, 17, 22, 0, tzinfo=ZURICH)
        )
        self.act(lambda: ops.add_comment(self.todo, author=self.ada, content="Two"))
        Notification.objects.filter(
            sent_at=None, created_at__gt=dt.datetime(2026, 11, 18, tzinfo=ZURICH)
        ).update(created_at=dt.datetime(2026, 11, 19, 9, 0, tzinfo=ZURICH))
        self.assertEqual(self.send(dt.datetime(2026, 11, 20, 7, 0, tzinfo=ZURICH)), 1)
        message = mail.outbox[0]
        self.assertEqual(
            message.subject,
            "[Biwak] What happened from 17. November 2026 to 19. November 2026",
        )
        self.assertIn(
            "What happened from 17. November 2026 to 19. November 2026", message.body
        )

    def test_sent_after_the_commit(self):
        self.act(lambda: ops.add_comment(self.todo, author=self.ada, content="Hi"))
        with self.captureOnCommitCallbacks() as callbacks:
            send_mails(now=timezone.now() + dt.timedelta(minutes=11))
            self.assertEqual(mail.outbox, [])
        self.assertEqual(len(callbacks), 1)
        callbacks[0]()
        self.assertEqual(len(mail.outbox), 1)

    def test_checklists_in_both_parts(self):
        self.act(
            lambda: ops.add_comment(
                self.todo, author=self.ada, content="- [x] Poles\n- [ ] Pegs"
            )
        )
        self.send(timezone.now() + dt.timedelta(minutes=11))
        message = next(m for m in mail.outbox if m.to == [self.bob.email])
        self.assertIn("- \u2611 Poles", message.body)
        self.assertIn("- \u2610 Pegs", message.body)
        html = message.alternatives[0].content
        self.assertIn("\u2611", html)
        self.assertNotIn("<input", html)

    def test_references_to_other_items_attachments(self):
        """Their names stay out of mails (specs/files.md)"""
        subscribe(self.cleo, self.todo)
        secret = ops.create_todo(todolist=self.internal, title="Pay", creator=self.ada)
        salaries = attachments.upload(
            project=self.project,
            file=ContentFile(b"%PDF-", name="Salaries 2027.pdf"),
            uploaded_by=self.ada,
        )
        ops.update_todo(secret, actor=self.ada, notes=salaries.markdown)
        self.act(
            lambda: ops.add_comment(
                self.todo,
                author=self.ada,
                content=f"See [the table](attachment:{salaries.key})",
            )
        )
        self.send(timezone.now() + dt.timedelta(minutes=11))
        cleo = next(m for m in mail.outbox if m.to == [self.cleo.email])
        for text in [cleo.body, cleo.alternatives[0].content]:
            self.assertIn("See attachment", text)
            self.assertNotIn("Salaries", text)
            self.assertNotIn(salaries.key, text)

    def test_moves_and_attachments(self):
        """Clients don't learn where it moved (the name may be internal);
        attachments are links with BASE_URL"""
        subscribe(self.cleo, self.todo)
        attachment = attachments.upload(
            project=self.project,
            file=ContentFile(b"%PDF-", name="plan.pdf"),
            uploaded_by=self.ada,
        )
        self.act(
            lambda: record(
                actor=self.ada,
                action=Action.MOVED,
                project=self.project,
                item=self.todo,
                to="Internal plans",
            )
        )
        self.act(
            lambda: ops.add_comment(
                self.todo,
                author=self.ada,
                content=f"The [plan](attachment:{attachment.key})",
            )
        )
        self.send(timezone.now() + dt.timedelta(minutes=11))
        by = {m.to[0]: m for m in mail.outbox}
        url = f"https://biwak.example.org{attachment.get_absolute_url()}"
        bob, cleo = by[self.bob.email], by[self.cleo.email]
        self.assertIn("moved it to Internal plans.", bob.body)
        self.assertIn("Ada Example moved it.", cleo.body)
        self.assertNotIn("Internal plans", cleo.body + cleo.alternatives[0].content)
        self.assertIn(f"The [plan]({url})", bob.body)
        self.assertIn(f'href="{url}"', bob.alternatives[0].content)

    def test_clients_get_the_target_list_if_it_is_visible_to_them(self):
        """Checked when the mail is made, not when the move happened"""
        subscribe(self.cleo, self.todo)
        plans = ops.create_list(
            project=self.project, title="Plans", creator=self.ada, visible=True
        )
        self.act(lambda: ops.move_todo(self.todo, todolist=plans, actor=self.ada))
        self.send(timezone.now() + dt.timedelta(minutes=11))
        by = {m.to[0]: m for m in mail.outbox}
        for user in [self.bob, self.cleo]:
            self.assertIn("Ada Example moved it to Plans.", by[user.email].body)

    def test_a_list_made_internal_since_is_left_out_for_clients(self):
        subscribe(self.cleo, self.todo)
        plans = ops.create_list(
            project=self.project, title="Plans", creator=self.ada, visible=True
        )
        self.act(lambda: ops.move_todo(self.todo, todolist=plans, actor=self.ada))
        ops.set_visibility(plans, visible=False, actor=self.ada)
        Item.objects.filter(pk=self.todo.pk).update(is_client_visible=True)
        self.send(timezone.now() + dt.timedelta(minutes=11))
        by = {m.to[0]: m for m in mail.outbox}
        self.assertIn("moved it to Plans.", by[self.bob.email].body)
        self.assertIn("Ada Example moved it.", by[self.cleo.email].body)
        self.assertNotIn("moved it to", by[self.cleo.email].body)

    def test_moving_out_of_its_group(self):
        subscribe(self.cleo, self.todo)
        group = ops.create_group(todolist=self.shared.todolist, title="Done")
        ops.move_todo(self.todo, todolist=self.shared, group=group, actor=self.ada)
        Event.objects.all().delete()
        self.act(
            lambda: ops.move_todo(
                self.todo, todolist=self.shared, group=None, actor=self.ada
            )
        )
        self.send(timezone.now() + dt.timedelta(minutes=11))
        for message in mail.outbox:
            self.assertIn("Ada Example moved it out of its group.", message.body)

    def test_mentions_in_the_lists_title(self):
        ops.update_list(
            self.shared, actor=self.ada, title=f"For {mentions.syntax(self.bob)}"
        )
        self.act(lambda: ops.add_comment(self.todo, author=self.ada, content="Hi"))
        self.send(timezone.now() + dt.timedelta(minutes=11))
        message = mail.outbox[0]
        self.assertIn("List: For @Bob", message.body)
        self.assertIn("For @Bob", message.alternatives[0].content)
        self.assertNotIn("person:", message.body + message.alternatives[0].content)

    def test_command(self):
        self.act(lambda: ops.add_comment(self.todo, author=self.ada, content="Hi"))
        Notification.objects.update(
            created_at=timezone.now() - dt.timedelta(minutes=11)
        )
        with self.captureOnCommitCallbacks(execute=True):
            call_command("send_mails", verbosity=0)
        self.assertEqual(len(mail.outbox), 1)

    def test_one_failing_mail_stops_nobody_else(self):
        """Logged, its notifications stay unsent for the next run"""
        carl = person("Carl")
        other = ops.create_todo(todolist=self.shared, title="Pack", creator=self.ada)
        subscribe(carl, other)
        self.act(lambda: ops.add_comment(self.todo, author=self.ada, content="One"))
        self.act(lambda: ops.add_comment(other, author=self.ada, content="Two"))
        real = mails_module.item_mail

        def failing(user, item, notifications):
            if user == self.bob:
                raise RuntimeError("Broken")
            return real(user, item, notifications)

        later = timezone.now() + dt.timedelta(minutes=11)
        with (
            patch.object(mails_module, "item_mail", failing),
            self.assertLogs("biwak.activity.mails", "ERROR"),
        ):
            self.assertEqual(self.send(later), 1)
        self.assertEqual([m.to for m in mail.outbox], [[carl.email]])
        self.assertTrue(
            Notification.objects.filter(user=self.bob, sent_at=None).exists()
        )
        self.assertEqual(self.send(later), 1)
        self.assertEqual(mail.outbox[1].to, [self.bob.email])

    def test_nothing_left_to_say(self):
        """Reactions to a comment deleted since: no mail, nothing breaks"""
        comment = ops.add_comment(self.todo, author=self.bob, content="Hi")
        self.act(lambda: add_reaction(self.ada, "👍", comment=comment))
        comment.delete()
        self.assertEqual(self.send(timezone.now() + dt.timedelta(minutes=11)), 0)
        self.assertEqual(mail.outbox, [])
        self.assertFalse(Notification.objects.filter(user=self.bob).exists())

    def test_command_runs_check_ins_when_mails_fail(self):
        with (
            patch(
                "biwak.activity.management.commands.send_mails.send_mails",
                side_effect=RuntimeError,
            ),
            patch("biwak.checkins.operations.run") as run,
            self.assertLogs("biwak.activity.management.commands.send_mails", "ERROR"),
        ):
            call_command("send_mails", verbosity=0)
        run.assert_called_once()

    def test_unsubscribe(self):
        url = f"/unsubscribe/{unsubscribe_token(self.bob, self.todo)}/"
        # Asking only, without logging in
        response = self.client.get(url)
        self.assertContains(response, "Order the tent")
        self.assertTrue(Subscription.objects.filter(user=self.bob).exists())
        # One click (RFC 8058), no CSRF token
        client = self.client_class(enforce_csrf_checks=True)
        response = client.post(url, {"List-Unsubscribe": "One-Click"})
        self.assertContains(response, "Unsubscribed")
        self.assertFalse(
            Subscription.objects.filter(user=self.bob, item=self.todo).exists()
        )
        # Tampered tokens don't work
        self.assertEqual(self.client.post(url.replace(":", ":x", 1)).status_code, 404)
        # Who can't see the item any more doesn't learn its title
        secret = ops.create_todo(
            todolist=self.internal, title="Secret plan", creator=self.ada
        )
        url = f"/unsubscribe/{unsubscribe_token(self.cleo, secret)}/"
        self.assertNotContains(self.client.get(url), "Secret plan")

    def test_unsubscribe_link_of_new_items(self):
        """Subscribed to the list: the link unsubscribes from the list"""
        subscribe(self.bob, self.shared)
        self.act(
            lambda: ops.create_todo(todolist=self.shared, title="New", creator=self.ada)
        )
        self.send(timezone.now() + dt.timedelta(minutes=11))
        message = mail.outbox[0]
        self.assertIn("Ada Example added it.", message.body)
        url = message.extra_headers["List-Unsubscribe"].strip("<>")
        self.client.post(url.removeprefix("https://biwak.example.org"))
        self.assertFalse(
            Subscription.objects.filter(user=self.bob, item=self.shared).exists()
        )


class BackAndForthTest(MailsBase):
    """Completing and reopening back and forth (decided 2026-11-21): what
    cancels out among the unsent notifications isn't mailed; once the
    completion went out, the reopening does too"""

    def test_what_cancels_out_isnt_mailed(self):
        self.act(lambda: ops.complete(self.todo, actor=self.ada))
        self.act(lambda: ops.reopen(self.todo, actor=self.ada))
        mail.outbox.clear()
        self.assertEqual(self.send(timezone.now() + dt.timedelta(minutes=11)), 0)
        self.assertEqual(mail.outbox, [])
        self.assertFalse(Notification.objects.filter(user=self.bob).exists())

    def test_the_net_change_is_mailed_once(self):
        for run in [ops.complete, ops.reopen, ops.complete]:
            self.act(lambda run=run: run(self.todo, actor=self.ada))
        mail.outbox.clear()
        self.assertEqual(self.send(timezone.now() + dt.timedelta(minutes=11)), 1)
        (message,) = mail.outbox
        self.assertEqual(message.body.count("completed"), 1)
        self.assertNotIn("reopened", message.body)

    def test_a_mailed_completion_is_followed_by_the_reopening(self):
        self.act(lambda: ops.complete(self.todo, actor=self.ada))
        mail.outbox.clear()
        now = timezone.now()
        self.assertEqual(self.send(now + dt.timedelta(minutes=11)), 1)
        self.act(lambda: ops.reopen(self.todo, actor=self.ada))
        self.assertEqual(self.send(now + dt.timedelta(minutes=22)), 1)
        self.assertIn("completed", mail.outbox[0].body)
        self.assertIn("reopened", mail.outbox[1].body)

    def test_a_digest_tells_the_net_change_over_midnight(self):
        # Completed in the evening, reopened before the digest at 07:00:
        # nothing to tell, today or tomorrow
        self.bob.mail_delivery = MailDelivery.DIGEST
        self.bob.save()
        self.act(lambda: ops.complete(self.todo, actor=self.ada))
        Notification.objects.update(
            created_at=dt.datetime(2026, 11, 19, 23, 0, tzinfo=ZURICH)
        )
        self.act(lambda: ops.reopen(self.todo, actor=self.ada))
        Notification.objects.filter(event__action=Action.REOPENED).update(
            created_at=dt.datetime(2026, 11, 20, 6, 0, tzinfo=ZURICH)
        )
        mail.outbox.clear()
        self.assertEqual(self.send(dt.datetime(2026, 11, 20, 7, 0, tzinfo=ZURICH)), 0)
        self.assertEqual(self.send(dt.datetime(2026, 11, 21, 7, 0, tzinfo=ZURICH)), 0)
        self.assertEqual(mail.outbox, [])
        self.assertFalse(Notification.objects.filter(user=self.bob).exists())

    def test_digests_too(self):
        self.bob.mail_delivery = MailDelivery.DIGEST
        self.bob.save()
        self.act(lambda: ops.complete(self.todo, actor=self.ada))
        self.act(lambda: ops.add_comment(self.todo, author=self.ada, content="Oops"))
        self.act(lambda: ops.reopen(self.todo, actor=self.ada))
        mail.outbox.clear()
        tomorrow = timezone.localtime() + dt.timedelta(days=1)
        self.assertEqual(self.send(tomorrow.replace(hour=8)), 1)
        (message,) = mail.outbox
        self.assertIn("Oops", message.body)
        self.assertNotIn("completed", message.body)
        self.assertNotIn("reopened", message.body)
