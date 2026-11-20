import datetime as dt

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from biwak.accounts.models import MailDelivery, NotificationLevel
from biwak.activity.mails import send_mails
from biwak.activity.models import Notification
from biwak.activity.operations import set_level_override, subscribe
from biwak.items import operations as ops
from biwak.reactions import operations
from biwak.test_utils import person, project


@override_settings(
    BASE_URL="https://biwak.example.org", DEFAULT_FROM_EMAIL="biwak@example.org"
)
class NotifyingTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.carl = person("Carl")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.bob, self.carl, self.cleo])
        self.shared = ops.create_list(
            project=self.project, title="Shared", creator=self.ada, visible=True
        )
        self.internal = ops.create_list(
            project=self.project, title="Internal", creator=self.ada
        )
        self.todo = ops.create_todo(
            todolist=self.shared, title="Order the tent", creator=self.ada
        )
        self.secret = ops.create_todo(
            todolist=self.internal, title="Secret", creator=self.ada
        )
        # Bob follows along: reactions never reach subscribers
        subscribe(self.bob, self.todo)
        subscribe(self.bob, self.secret)
        Notification.objects.all().delete()

    def react(self, user, content, **target):
        with self.captureOnCommitCallbacks(execute=True):
            operations.toggle_reaction(user, content, **target)

    def send(self, minutes=3):
        with self.captureOnCommitCallbacks(execute=True):
            return send_mails(now=timezone.now() + dt.timedelta(minutes=minutes))

    def told(self):
        return {n.user for n in Notification.objects.select_related("user")}

    def test_only_the_author(self):
        self.react(self.bob, "👍", item=self.todo)
        self.assertEqual(self.told(), {self.ada})

    def test_comment_author(self):
        comment = ops.add_comment(self.todo, author=self.carl, content="Hi")
        Notification.objects.all().delete()
        self.react(self.bob, "👍", comment=comment)
        self.assertEqual(self.told(), {self.carl})

    def test_nobody_for_yourself(self):
        self.react(self.ada, "👍", item=self.todo)
        self.assertEqual(self.told(), set())

    def test_levels(self):
        self.ada.notification_level = NotificationLevel.CONCERNS_ME
        self.ada.save()
        self.react(self.bob, "👍", item=self.todo)
        self.assertEqual(self.told(), {self.ada})
        Notification.objects.all().delete()
        self.ada.notification_level = NotificationLevel.NOTHING
        self.ada.save()
        self.react(self.bob, "🎉", item=self.todo)
        self.assertEqual(self.told(), set())
        # An override for the item wins
        self.ada.notification_level = NotificationLevel.EVERYTHING
        self.ada.save()
        set_level_override(self.ada, NotificationLevel.NOTHING, item=self.todo)
        self.react(self.bob, "🔥", item=self.todo)
        self.assertEqual(self.told(), set())

    def test_client_author_not_told_about_hidden_item(self):
        todo = ops.create_todo(todolist=self.shared, title="Theirs", creator=self.cleo)
        Notification.objects.all().delete()
        ops.set_visibility(self.shared, visible=False, actor=self.ada)
        self.react(self.bob, "👍", item=todo)
        self.assertEqual(self.told(), set())

    def test_one_mail_for_several_reactions(self):
        self.react(self.bob, "👍", item=self.todo)
        self.react(self.bob, "🎉", item=self.todo)
        self.react(self.carl, "Thanks!", item=self.todo)
        comment = ops.add_comment(self.todo, author=self.ada, content="Mine")
        Notification.objects.exclude(event__action="reacted").delete()
        self.react(self.carl, "💯", comment=comment)
        self.assertEqual(self.send(minutes=1), 0)
        self.assertEqual(self.send(), 1)
        self.assertEqual([m.to for m in mail.outbox], [[self.ada.email]])
        body = mail.outbox[0].body
        self.assertIn("Bob Example: 👍 🎉, Carl Example: Thanks!", body)
        self.assertIn("Reactions to your comment:", body)
        self.assertIn("Carl Example: 💯", body)
        self.assertIn("Mine", body)
        self.assertIn("Order the tent", mail.outbox[0].subject)
        self.assertIn("Bob Example: 👍 🎉", mail.outbox[0].alternatives[0][0])

    def test_removed_before_sending(self):
        self.react(self.bob, "👍", item=self.todo)
        self.react(self.bob, "🎉", item=self.todo)
        self.react(self.bob, "👍", item=self.todo)  # removed again
        self.assertEqual(self.send(), 1)
        body = mail.outbox[0].body
        self.assertIn("Bob Example: 🎉", body)
        self.assertNotIn("👍", body)

    def test_all_removed_nothing_sent(self):
        self.react(self.bob, "👍", item=self.todo)
        self.react(self.bob, "👍", item=self.todo)
        self.assertFalse(Notification.objects.exists())
        self.assertEqual(self.send(), 0)

    def test_removed_after_sending_stays_sent(self):
        self.react(self.bob, "👍", item=self.todo)
        self.send()
        self.react(self.bob, "👍", item=self.todo)
        self.assertEqual(self.send(minutes=10), 0)
        self.assertEqual(len(mail.outbox), 1)

    def test_digest(self):
        self.ada.mail_delivery = MailDelivery.DIGEST
        self.ada.save()
        self.react(self.bob, "👍", item=self.todo)
        self.react(self.carl, "Thanks!", item=self.todo)
        self.assertEqual(self.send(minutes=60 * 48), 1)
        body = mail.outbox[0].body
        self.assertIn("Order the tent", body)
        self.assertIn("Bob Example: 👍", body)
        self.assertIn("Carl Example: Thanks!", body)

    def test_client_isnt_mailed_about_internal(self):
        """A client who created something that became internal is told
        nothing"""
        todo = ops.create_todo(todolist=self.shared, title="Theirs", creator=self.cleo)
        Notification.objects.all().delete()
        self.react(self.bob, "👍", item=todo)
        self.assertEqual(self.told(), {self.cleo})
        ops.set_visibility(self.shared, visible=False, actor=self.ada)
        self.assertEqual(self.send(), 0)
        self.assertEqual(mail.outbox, [])
