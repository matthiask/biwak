"""Push notifications (specs/web-push.md): mentions and assignments only,
after the mails' merge window, not when read, not in quiet hours or while
away, only what the person may see; the browsers' push services stubbed"""

import base64
import datetime as dt
import json
from io import StringIO
from unittest.mock import Mock, patch

import time_machine
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.core.management import call_command
from django.db import connection
from django.test import override_settings
from django.utils import timezone
from pywebpush import WebPushException

from biwak.accounts.models import PushSubscription
from biwak.activity import lantern, mentions, push
from biwak.activity.models import Notification
from biwak.activity.test_mails import MailsBase
from biwak.activity.test_quiet_hours import at
from biwak.items import operations as ops


def _keys():
    """A VAPID key pair: the private key as PEM, the public one as the
    browsers take it (base64url of the uncompressed point)"""
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    point = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return pem, base64.urlsafe_b64encode(point).decode().rstrip("=")


_PRIVATE, _PUBLIC = _keys()
KEYS = {
    "WEBPUSH_VAPID_PUBLIC_KEY": _PUBLIC,
    "WEBPUSH_VAPID_PRIVATE_KEY": _PRIVATE,
    "WEBPUSH_SUBJECT": "mailto:biwak@example.org",
}


def subscribe_device(user, name="phone", **kwargs):
    return PushSubscription.objects.create(
        user=user,
        endpoint=f"https://push.example.org/{user.pk}/{name}",
        p256dh="BKeyOfTheDevice",
        auth="secret",
        user_agent="Mozilla/5.0 (iPhone) Safari",
        **kwargs,
    )


@override_settings(**KEYS)
class PushBase(MailsBase):
    def setUp(self):
        super().setUp()
        self.start = timezone.now()
        self.phone = subscribe_device(self.bob, created_at=self.start)
        self.webpush = patch("pywebpush.webpush").start()
        self.addCleanup(patch.stopall)

    def later(self, minutes=11):
        return timezone.now() + dt.timedelta(minutes=minutes)

    def mention(self, who, item=None, author=None):
        self.act(
            lambda: ops.add_comment(
                item or self.todo,
                author=author or self.ada,
                content=f"Can you check the poles, {mentions.syntax(who)}?",
            )
        )

    def pushed(self):
        """The payloads pushed, per endpoint"""
        pushes = [
            (call.args[0]["endpoint"], json.loads(call.kwargs["data"]))
            for call in self.webpush.call_args_list
        ]
        self.webpush.reset_mock()
        return pushes


class WhatPushesTest(PushBase):
    def test_a_mention_after_the_merge_window(self):
        self.mention(self.bob)
        self.assertEqual(push.send_due(self.later(9)), 0)
        self.assertEqual(self.pushed(), [])
        self.assertEqual(push.send_due(self.later()), 1)
        ((endpoint, payload),) = self.pushed()
        self.assertEqual(endpoint, self.phone.endpoint)
        self.assertEqual(payload["title"], "Order the tent")
        self.assertEqual(
            payload["body"],
            # The lantern's line
            "Ada Example commented: You were mentioned.\n"
            "Can you check the poles, @Bob?\nWebsite",
        )
        self.assertEqual(payload["tag"], f"biwak-item-{self.todo.pk}")
        # Turning it off without signing in (a browser signed out)
        self.assertEqual(
            payload["actions"],
            [{"action": "off", "title": "Turn off on this device"}],
        )
        comment = self.todo.comments.get()
        self.assertEqual(
            payload["url"],
            f"https://biwak.example.org/todos/{self.todo.pk}/#comment-{comment.pk}",
        )
        # Once
        self.assertEqual(push.send_due(self.later(20)), 0)
        self.phone.refresh_from_db()
        self.assertIsNotNone(self.phone.last_success_at)

    def test_the_request(self):
        self.mention(self.bob)
        push.send_due(self.later())
        (call,) = self.webpush.call_args_list
        self.assertEqual(
            call.args[0],
            {
                "endpoint": self.phone.endpoint,
                "keys": {"p256dh": "BKeyOfTheDevice", "auth": "secret"},
            },
        )
        self.assertEqual(call.kwargs["ttl"], 12 * 3600)
        self.assertEqual(
            call.kwargs["vapid_claims"], {"sub": "mailto:biwak@example.org"}
        )

    def test_in_the_persons_language(self):
        self.bob.language = "de"
        self.bob.save()
        self.mention(self.bob)
        push.send_due(self.later())
        ((_endpoint, payload),) = self.pushed()
        self.assertTrue(
            payload["body"].startswith("Ada Example hat kommentiert: Du wurdest"),
            payload["body"],
        )

    def test_a_mention_in_a_todo_says_so(self):
        self.act(
            lambda: ops.create_todo(
                todolist=self.shared,
                title=f"Fold the tent with {mentions.syntax(self.bob)}",
                creator=self.ada,
            )
        )
        push.send_due(self.later())
        ((_endpoint, payload),) = self.pushed()
        self.assertEqual(payload["title"], "Fold the tent with @Bob")
        self.assertEqual(
            payload["body"], "Ada Example added it. You were mentioned.\nWebsite"
        )

    def test_an_assignment(self):
        self.act(lambda: ops.assign(self.todo, [self.bob], actor=self.ada))
        push.send_due(self.later())
        ((_endpoint, payload),) = self.pushed()
        self.assertEqual(payload["title"], "Order the tent")
        self.assertEqual(payload["body"], "Ada Example assigned you.\nWebsite")

    def test_the_todos_of_one_assign_are_one_push(self):
        other = ops.create_todo(todolist=self.shared, title="Pegs", creator=self.ada)
        self.act(
            lambda: ops.assign_todos([self.todo, other], [self.bob], actor=self.ada)
        )
        push.send_due(self.later())
        ((_endpoint, payload),) = self.pushed()
        self.assertEqual(payload["title"], "To-dos")
        self.assertEqual(payload["body"], "Ada Example assigned you 2 to-dos.\nWebsite")
        self.assertEqual(payload["url"], "https://biwak.example.org/todos/")

    def test_not_other_changes(self):
        """Bob follows the to-do: comments and others' assignments reach him
        by mail and in the lantern, not as pushes"""
        self.act(lambda: ops.add_comment(self.todo, author=self.ada, content="Hi"))
        self.act(lambda: ops.assign(self.todo, [self.cleo], actor=self.ada))
        self.assertEqual(lantern.unread_count(self.bob), 1)
        self.assertEqual(push.send_due(self.later()), 0)
        self.assertEqual(self.pushed(), [])

    def test_not_own_actions(self):
        subscribe_device(self.ada, created_at=self.start)
        self.act(lambda: ops.assign(self.todo, [self.ada], actor=self.ada))
        self.mention(self.ada, author=self.ada)
        self.assertEqual(push.send_due(self.later()), 0)

    def test_one_push_per_item_with_the_latest_line(self):
        self.mention(self.bob)
        self.act(lambda: ops.assign(self.todo, [self.bob], actor=self.cleo))
        push.send_due(self.later())
        ((_endpoint, payload),) = self.pushed()
        self.assertEqual(payload["body"], "Cleo Example assigned you.\nWebsite")

    def test_waits_for_the_newest(self):
        self.mention(self.bob)
        with time_machine.travel(self.later(8)):
            self.mention(self.bob)
        self.assertEqual(push.send_due(self.later(12)), 0)
        self.assertEqual(push.send_due(self.later(19)), 1)

    def test_not_when_read_in_the_lantern(self):
        self.mention(self.bob)
        lantern.read(self.bob, item=self.todo)
        self.assertEqual(push.send_due(self.later()), 0)
        self.assertEqual(self.pushed(), [])

    def test_wanted(self):
        self.mention(self.bob)
        self.act(lambda: ops.add_comment(self.todo, author=self.ada, content="Hi"))
        notifications = Notification.objects.filter(user=self.bob)
        self.assertEqual(
            [push.wanted(n) for n in notifications.order_by("pk")], [True, False]
        )
        self.assertEqual(
            list(push.pending().filter(user=self.bob)), [notifications.first()]
        )

    def test_every_device_independent_of_mail(self):
        self.bob.mail_delivery = "none"
        self.bob.save()
        laptop = subscribe_device(self.bob, "laptop", created_at=self.start)
        desktop = subscribe_device(self.bob, "desktop", created_at=self.start)
        self.mention(self.bob)
        self.assertEqual(push.send_due(self.later()), 1)
        pushes = self.pushed()
        # The same push on each of his devices, once
        self.assertEqual(
            sorted(endpoint for endpoint, _payload in pushes),
            sorted([self.phone.endpoint, laptop.endpoint, desktop.endpoint]),
        )
        self.assertEqual(len({json.dumps(payload) for _e, payload in pushes}), 1)
        self.assertEqual(
            PushSubscription.objects.filter(last_success_at__isnull=False).count(), 3
        )

    def test_one_device_failing_doesnt_keep_the_others(self):
        laptop = subscribe_device(self.bob, "laptop", created_at=self.start)

        def webpush(info, **kwargs):
            if info["endpoint"] == self.phone.endpoint:
                raise ConnectionError("unreachable")

        self.webpush.side_effect = webpush
        self.mention(self.bob)
        with self.assertLogs("biwak.activity.push", "ERROR"):
            self.assertEqual(push.send_due(self.later()), 1)
        laptop.refresh_from_db()
        self.assertIsNotNone(laptop.last_success_at)
        # Pushed: not again to the laptop next time
        self.assertIsNotNone(Notification.objects.get(user=self.bob).pushed_at)

    def test_not_what_was_before_subscribing(self):
        self.mention(self.bob)
        self.phone.created_at = self.later(1)
        self.phone.save()
        self.assertEqual(push.send_due(self.later()), 0)

    def test_nothing_without_keys(self):
        self.mention(self.bob)
        with override_settings(WEBPUSH_VAPID_PRIVATE_KEY=""):
            self.assertFalse(push.enabled())
            self.assertEqual(push.send_due(self.later()), 0)
        self.assertEqual(self.pushed(), [])

    def test_the_private_key_on_one_line(self):
        """For an environment variable: the PEM's lines between the markers
        joined"""
        pem = KEYS["WEBPUSH_VAPID_PRIVATE_KEY"]
        line = "".join(pem.strip().splitlines()[1:-1])
        for key in [pem, line]:
            with override_settings(WEBPUSH_VAPID_PRIVATE_KEY=key):
                self.assertEqual(
                    push._vapid_key().public_key.public_numbers(),
                    serialization
                    .load_pem_private_key(pem.encode(), None)
                    .public_key()
                    .public_numbers(),
                )

    def test_the_command(self):
        self.mention(self.bob)
        with time_machine.travel(self.later()):
            out = StringIO()
            call_command("send_mails", verbosity=2, stdout=out)
        self.assertIn("1 pushes sent.", out.getvalue())
        self.assertEqual(len(self.pushed()), 1)


class VisibilityTest(PushBase):
    def test_clients_only_what_they_may_see(self):
        """Mentioned while the list was visible, hidden before the push:
        nothing, like the mail"""
        subscribe_device(self.cleo, created_at=self.start)
        self.mention(self.cleo)
        self.act(lambda: ops.set_visibility(self.shared, visible=False, actor=self.ada))
        self.assertEqual(push.send_due(self.later()), 0)
        self.assertEqual(self.pushed(), [])
        self.assertIsNotNone(Notification.objects.get(user=self.cleo).pushed_at)

    def test_a_client_mentioned_where_they_see(self):
        subscribe_device(self.cleo, created_at=self.start)
        self.mention(self.cleo)
        self.assertEqual(push.send_due(self.later()), 1)

    def test_not_after_leaving_the_project(self):
        self.mention(self.bob)
        self.project.memberships.filter(user=self.bob).delete()
        self.project.is_all_access = False
        self.project.save()
        self.assertEqual(push.send_due(self.later()), 0)


class QuietTest(PushBase):
    def test_quiet_hours_nothing_later(self):
        self.bob.quiet_hours = True
        self.bob.save()
        with time_machine.travel(at("2026-11-20 18:30"), tick=False):
            self.mention(self.bob)
            self.phone.created_at = timezone.now() - dt.timedelta(days=1)
            self.phone.save()
        self.assertEqual(push.send_due(at("2026-11-20 18:45")), 0)
        notification = Notification.objects.get(user=self.bob)
        self.assertEqual(notification.pushed_at, at("2026-11-20 18:45"))
        self.assertEqual(push.send_due(at("2026-11-23 08:00")), 0)
        self.assertEqual(self.pushed(), [])
        # The lantern has it
        self.assertEqual(lantern.unread_count(self.bob), 1)

    def test_in_working_time(self):
        self.bob.quiet_hours = True
        self.bob.save()
        with time_machine.travel(at("2026-11-20 10:00"), tick=False):
            self.mention(self.bob)
            self.phone.created_at = timezone.now() - dt.timedelta(days=1)
            self.phone.save()
        self.assertEqual(push.send_due(at("2026-11-20 10:15")), 1)

    def test_away(self):
        self.bob.away_until = timezone.localdate() + dt.timedelta(days=2)
        self.bob.save()
        self.mention(self.bob)
        self.assertEqual(push.send_due(self.later()), 0)
        self.assertEqual(self.pushed(), [])
        self.assertIsNotNone(Notification.objects.get(user=self.bob).pushed_at)


class FailuresTest(PushBase):
    def failing(self, status):
        return WebPushException("failed", response=Mock(status_code=status))

    def test_gone_deletes_the_subscription(self):
        laptop = subscribe_device(self.bob, "laptop", created_at=self.start)

        def webpush(info, **kwargs):
            if info["endpoint"] == self.phone.endpoint:
                raise self.failing(410)

        self.webpush.side_effect = webpush
        self.mention(self.bob)
        self.assertEqual(push.send_due(self.later()), 1)
        self.assertEqual(list(self.bob.push_subscriptions.all()), [laptop])

    def test_not_found_too(self):
        self.webpush.side_effect = self.failing(404)
        self.mention(self.bob)
        self.assertEqual(push.send_due(self.later()), 0)
        self.assertFalse(self.bob.push_subscriptions.exists())
        self.assertIsNotNone(Notification.objects.get(user=self.bob).pushed_at)

    def test_other_errors_try_again_next_run(self):
        self.webpush.side_effect = self.failing(500)
        self.mention(self.bob)
        with self.assertLogs("biwak.activity.push", "WARNING"):
            self.assertEqual(push.send_due(self.later()), 0)
        self.assertTrue(self.bob.push_subscriptions.exists())
        self.assertIsNone(Notification.objects.get(user=self.bob).pushed_at)
        self.webpush.side_effect = None
        self.assertEqual(push.send_due(self.later(12)), 1)

    def test_sent_outside_a_transaction(self):
        """The notifications are claimed in a short transaction and pushed
        outside it, so marking them read in the lantern doesn't wait for
        the push services (review 2026-11-23); claimed, a second run
        doesn't push them again"""
        depth = len(connection.atomic_blocks)
        during = []

        def webpush(info, **kwargs):
            during.append((len(connection.atomic_blocks), push.pending().count()))

        self.webpush.side_effect = webpush
        self.mention(self.bob)
        self.assertEqual(push.send_due(self.later()), 1)
        self.assertEqual(during, [(depth, 0)])
        self.assertIsNotNone(Notification.objects.get(user=self.bob).pushed_at)

    def test_given_up_after_the_ttl(self):
        self.webpush.side_effect = ConnectionError("unreachable")
        self.mention(self.bob)
        with self.assertLogs("biwak.activity.push", "ERROR"):
            self.assertEqual(push.send_due(self.later(13 * 60)), 0)
        self.assertIsNotNone(Notification.objects.get(user=self.bob).pushed_at)
