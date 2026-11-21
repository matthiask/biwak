"""The lantern: the notifications in the app, reading them, and mails
leaving out what was read (specs/lantern.md)"""

import datetime as dt
import zoneinfo
from unittest import mock

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from biwak.accounts.models import MailDelivery, NotificationLevel
from biwak.activity import lantern, mentions
from biwak.activity.mails import send_mails
from biwak.activity.models import Event, Notification
from biwak.activity.operations import set_level_override, subscribe
from biwak.files import operations as file_ops
from biwak.items import operations as ops
from biwak.live import announce
from biwak.projects.models import Membership
from biwak.reactions.operations import add_reaction, remove_reaction
from biwak.test_utils import check_in_answers, person, project


ZURICH = zoneinfo.ZoneInfo("Europe/Zurich")


class LanternTestCase(TestCase):
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
            todolist=self.shared, title="Order the tent", creator=self.ada
        )
        self.secret = ops.create_todo(
            todolist=self.internal, title="Budget", creator=self.ada
        )
        for user in [self.bob, self.cleo]:
            subscribe(user, self.todo)
        subscribe(self.bob, self.secret)

    def act(self, run):
        with self.captureOnCommitCallbacks(execute=True):
            return run()

    def comment(self, item, content="Hi", author=None):
        return self.act(
            lambda: ops.add_comment(item, author=author or self.ada, content=content)
        )

    def items(self, user, **kwargs):
        return [
            item.title
            for item, _entries in lantern.by_item(
                lantern.wanted(list(lantern.notifications_for(user, **kwargs)), user)
            )
        ]


class ReadNotMailedTest(LanternTestCase):
    """Read in the lantern before its mail goes: left out of the mail"""

    def send(self, now):
        with self.captureOnCommitCallbacks(execute=True):
            return send_mails(now=now)

    def test_each_change_leaves_out_what_was_read(self):
        self.comment(self.todo, "One")
        self.comment(self.secret, "Two")
        lantern.read(self.bob, item=self.todo)
        self.assertEqual(self.send(timezone.now() + dt.timedelta(minutes=3)), 2)
        bobs = [m for m in mail.outbox if m.to == [self.bob.email]]
        self.assertEqual([m.subject for m in bobs], ["[Website] Budget"])
        # Kept for the lantern, read and not sent
        read = Notification.objects.get(user=self.bob, event__item=self.todo)
        self.assertIsNotNone(read.read_at)
        self.assertIsNone(read.sent_at)
        # Not picked up again
        mail.outbox.clear()
        self.assertEqual(self.send(timezone.now() + dt.timedelta(minutes=10)), 0)

    def test_a_mail_with_everything_read_isnt_sent(self):
        self.comment(self.todo, "One")
        self.comment(self.todo, "Two")
        lantern.read(self.bob)
        self.send(timezone.now() + dt.timedelta(minutes=3))
        self.assertFalse([m for m in mail.outbox if m.to == [self.bob.email]])
        self.assertEqual(
            Notification.objects.filter(user=self.bob, read_at__isnull=False).count(),
            2,
        )

    def test_read_between_listing_and_claiming(self):
        """``_claim()`` checks again: read meanwhile, not mailed"""
        self.comment(self.todo, "One")
        pks = list(
            Notification.objects.filter(user=self.bob).values_list("pk", flat=True)
        )
        lantern.read(self.bob)
        from biwak.activity.mails import _claim

        self.assertEqual(_claim(pks, timezone.now()), [])

    def test_digest_leaves_out_what_was_read(self):
        self.bob.mail_delivery = MailDelivery.DIGEST
        self.bob.save()
        self.comment(self.todo, "One")
        self.comment(self.secret, "Two")
        Notification.objects.update(
            created_at=dt.datetime(2026, 11, 19, 22, 0, tzinfo=ZURICH)
        )
        lantern.read(self.bob, item=self.secret)
        self.send(dt.datetime(2026, 11, 20, 7, 0, tzinfo=ZURICH))
        (message,) = [m for m in mail.outbox if m.to == [self.bob.email]]
        self.assertIn("Order the tent", message.body)
        self.assertNotIn("Budget", message.body)

    def test_a_digest_with_everything_read_isnt_sent(self):
        self.bob.mail_delivery = MailDelivery.DIGEST
        self.bob.save()
        self.comment(self.todo, "One")
        Notification.objects.update(
            created_at=dt.datetime(2026, 11, 19, 22, 0, tzinfo=ZURICH)
        )
        lantern.read(self.bob)
        self.send(dt.datetime(2026, 11, 20, 7, 0, tzinfo=ZURICH))
        self.assertFalse([m for m in mail.outbox if m.to == [self.bob.email]])

    def test_delivery_none_mails_nothing_and_the_lantern_has_it(self):
        self.bob.mail_delivery = MailDelivery.NONE
        self.bob.save()
        self.comment(self.todo, "One")
        Notification.objects.update(
            created_at=dt.datetime(2026, 11, 19, 22, 0, tzinfo=ZURICH)
        )
        self.send(dt.datetime(2026, 11, 20, 7, 0, tzinfo=ZURICH))
        self.assertFalse([m for m in mail.outbox if m.to == [self.bob.email]])
        self.assertEqual(self.items(self.bob, unread=True), ["Order the tent"])

    def test_a_change_after_reading_is_unread_again(self):
        """A merged edit moves the unsent notification forward: unread"""
        self.act(lambda: ops.update_todo(self.todo, actor=self.ada, title="One"))
        lantern.read(self.bob)
        self.act(lambda: ops.update_todo(self.todo, actor=self.ada, title="Two"))
        notification = Notification.objects.get(user=self.bob)
        self.assertIsNone(notification.read_at)


@override_settings(BASE_URL="https://biwak.example.org")
class ListingTest(LanternTestCase):
    def test_grouped_by_item_newest_first(self):
        self.comment(self.todo, "One")
        self.comment(self.secret, "Two")
        self.comment(self.todo, "Three")
        self.assertEqual(self.items(self.bob), ["Order the tent", "Budget"])
        _pinned, unread, read, more = lantern.menu(self.bob)
        self.assertEqual([len(entries) for _item, entries in unread], [2, 1])
        self.assertEqual((read, more), ([], False))
        lantern.read(self.bob, item=self.todo)
        _pinned, unread, read, _more = lantern.menu(self.bob)
        self.assertEqual([item.title for item, _e in unread], ["Budget"])
        self.assertEqual([item.title for item, _e in read], ["Order the tent"])

    def test_the_menu_has_the_latest_30_read(self):
        for index in range(lantern.MENU_READ + 5):
            self.comment(self.todo, f"Comment {index}")
        lantern.read(self.bob)
        _pinned, _unread, read, _more = lantern.menu(self.bob)
        self.assertEqual(sum(len(entries) for _item, entries in read), 30)

    def test_filters(self):
        self.comment(self.todo, "One")
        self.comment(self.secret, f"Two {mentions.syntax(self.bob)}")
        lantern.read(self.bob, item=self.secret)
        self.assertEqual(self.items(self.bob, unread=True), ["Order the tent"])
        self.assertEqual(self.items(self.bob, unread=False), ["Budget"])
        self.assertEqual(self.items(self.bob, mentions=True), ["Budget"])

    def test_a_client_never_sees_a_notification_about_something_internal(self):
        self.comment(self.todo, "Visible")
        self.assertEqual(self.items(self.cleo), ["Order the tent"])
        # The list hidden from clients: the notification stays, unseen
        self.act(lambda: ops.set_visibility(self.shared, visible=False, actor=self.ada))
        self.assertEqual(self.items(self.cleo), [])
        self.assertEqual(lantern.unread_count(self.cleo), 0)
        self.assertTrue(Notification.objects.filter(user=self.cleo).exists())
        # Even a notification nobody should have written: of an event of the
        # time the item was internal
        self.act(lambda: ops.set_visibility(self.shared, visible=True, actor=self.ada))
        event = Event.objects.create(
            project=self.project, item=self.todo, actor=self.ada, action="edited"
        )
        Notification.objects.create(user=self.cleo, event=event)
        self.assertEqual(
            [
                n.event_id
                for n in lantern.notifications_for(self.cleo)
                if n.event_id == event.pk
            ],
            [],
        )

    def test_lost_access_and_trash_hide_them(self):
        limited = project("Limited", members=[self.ada, self.bob], all_access=False)
        todolist = ops.create_list(project=limited, title="Plans", creator=self.ada)
        todo = ops.create_todo(todolist=todolist, title="Secret", creator=self.ada)
        subscribe(self.bob, todo)
        self.comment(todo, "Psst")
        self.assertIn("Secret", self.items(self.bob))
        Membership.objects.filter(project=limited, user=self.bob).delete()
        self.assertNotIn("Secret", self.items(self.bob))
        self.comment(self.secret, "Two")
        self.act(lambda: ops.trash(self.secret, actor=self.ada))
        self.assertNotIn("Budget", self.items(self.bob))

    def test_level_nothing_hides_them(self):
        self.comment(self.secret, "Two")
        set_level_override(self.bob, NotificationLevel.NOTHING, item=self.internal)
        self.assertEqual(self.items(self.bob), [])
        self.assertEqual(lantern.unread_count(self.bob), 0)

    def test_entries_say_what_happened(self):
        self.comment(self.todo, f"Look {mentions.syntax(self.bob)}")
        self.act(lambda: add_reaction(self.cleo, "👍", item=self.todo))
        self.act(lambda: ops.complete(self.todo, actor=self.cleo))
        (notification, *_rest) = lantern.prepare(
            list(lantern.notifications_for(self.ada)), self.ada
        )
        self.client.force_login(self.ada)
        page = self.client.get(reverse("lantern")).content.decode()
        self.assertIn("Cleo Example completed it.", page)
        self.assertIn("Cleo Example reacted 👍", page)
        self.client.force_login(self.bob)
        page = self.client.get(reverse("lantern")).content.decode()
        self.assertIn("Ada Example commented:", page)
        self.assertIn("You were mentioned.", page)
        # Through the lantern, to the comment
        commented = Notification.objects.get(user=self.bob, event__action="commented")
        self.assertIn(reverse("lantern_open", args=[commented.pk]), page)
        comment = self.todo.comments.get()
        self.assertEqual(
            lantern.anchor(commented), f"/todos/{self.todo.pk}/#comment-{comment.pk}"
        )
        self.assertTrue(notification)


class ReadingTest(LanternTestCase):
    def test_opening_an_item_reads_nothing(self):
        """Only the lantern reads (decided 2026-11-21): the item's pages
        opened some other way (the feed, a list, a mail's link, a live
        update) leave the notifications unread"""
        message = ops.create_message(
            project=self.project, title="News", content="", creator=self.ada
        )
        doc = ops.create_doc(project=self.project, title="Notes", creator=self.ada)
        (answer,) = check_in_answers(self.project, [self.ada])
        for item in [message, doc, answer, self.internal]:
            subscribe(self.bob, item)
        self.comment(self.todo, "One")
        self.act(
            lambda: file_ops.update_message(message, actor=self.ada, content="New")
        )
        self.act(lambda: file_ops.update_doc(doc, actor=self.ada, content="New"))
        self.comment(answer, "Nice")
        self.act(lambda: ops.update_list(self.internal, actor=self.ada, title="New"))
        unread = lantern.unread_count(self.bob)
        self.client.force_login(self.bob)
        for url in [
            self.todo.get_absolute_url(),
            message.get_absolute_url(),
            doc.get_absolute_url(),
            reverse("doc_edit", args=[doc.pk]),
            answer.get_absolute_url(),
            reverse("question", args=[answer.parent_id]),
            self.internal.get_absolute_url(),
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
                self.assertEqual(lantern.unread_count(self.bob), unread)

    def test_following_an_entry_reads_its_item(self):
        """The entry's link reads the item's notifications (its comments'
        too) and opens the item where it applies; without JavaScript"""
        comment = self.comment(self.todo, "One")
        self.act(lambda: ops.update_todo(self.todo, actor=self.ada, title="Two"))
        self.comment(self.secret, "Three")
        self.client.force_login(self.bob)
        self.assertEqual(lantern.unread_count(self.bob), 3)
        menu = self.client.get(reverse("lantern_menu")).content.decode()
        notification = Notification.objects.get(
            user=self.bob, event__data__comment=comment.pk
        )
        url = reverse("lantern_open", args=[notification.pk])
        self.assertIn(f'href="{url}"', menu)
        response = self.client.get(url)
        self.assertRedirects(
            response,
            f"{self.todo.get_absolute_url()}#comment-{comment.pk}",
            fetch_redirect_response=False,
        )
        self.assertEqual(lantern.unread_count(self.bob), 1)
        self.assertIn(
            f'href="{url}"', self.client.get(reverse("lantern")).content.decode()
        )

    def test_following_needs_the_notification_and_its_item(self):
        self.comment(self.todo, "One")
        notification = Notification.objects.get(user=self.cleo)
        url = reverse("lantern_open", args=[notification.pk])
        # Somebody else's
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(url).status_code, 404)
        # Of an item not seen anymore
        self.act(lambda: ops.set_visibility(self.shared, visible=False, actor=self.ada))
        self.client.force_login(self.cleo)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertIsNone(Notification.objects.get(user=self.cleo).read_at)

    def test_marking(self):
        self.comment(self.todo, "One")
        self.comment(self.secret, "Two")
        self.client.force_login(self.bob)
        response = self.client.post(reverse("lantern_read"), {"item": self.todo.pk})
        self.assertRedirects(response, reverse("lantern"))
        self.assertEqual(self.items(self.bob, unread=True), ["Budget"])
        self.client.post(reverse("lantern_unread"), {"item": self.todo.pk})
        self.assertEqual(
            self.items(self.bob, unread=True), ["Budget", "Order the tent"]
        )
        response = self.client.post(
            reverse("lantern_read"), {"all": "1"}, headers={"HX-Request": "true"}
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(lantern.unread_count(self.bob), 0)

    def test_marking_needs_to_see_the_item(self):
        self.comment(self.secret, "Two")
        self.client.force_login(self.cleo)
        for name in ["lantern_read", "lantern_unread"]:
            for value in [self.secret.pk, "x", ""]:
                with self.subTest(name=name, value=value):
                    response = self.client.post(reverse(name), {"item": value})
                    self.assertEqual(response.status_code, 404)

    def test_marking_touches_only_what_one_sees(self):
        """Reading all counts and reads only notifications one sees (the
        others stay unread, unseen); marking unread doesn't bring back an
        internal event's"""
        self.comment(self.todo, "Visible")
        self.act(lambda: ops.set_visibility(self.shared, visible=False, actor=self.ada))
        self.assertEqual(lantern.read(self.cleo), 0)
        self.assertIsNone(Notification.objects.get(user=self.cleo).read_at)
        # Visible again, and a notification of an internal event, read
        self.act(lambda: ops.set_visibility(self.shared, visible=True, actor=self.ada))
        self.assertEqual(lantern.read(self.cleo), 1)
        event = Event.objects.create(
            project=self.project, item=self.todo, actor=self.ada, action="edited"
        )
        internal = Notification.objects.create(
            user=self.cleo, event=event, read_at=timezone.now()
        )
        self.assertTrue(lantern.unread(self.cleo, item=self.todo))
        internal.refresh_from_db()
        self.assertIsNotNone(internal.read_at)
        self.assertEqual(lantern.unread_count(self.cleo), 1)


class PagesTest(LanternTestCase):
    def test_menu_count_and_page_as_staff_and_client(self):
        self.comment(self.todo, "Visible")
        self.comment(self.secret, "Internal")
        for user, count, sees, not_sees in [
            (self.bob, 2, ["Order the tent", "Budget"], []),
            (self.cleo, 1, ["Order the tent"], ["Budget", "Internal"]),
        ]:
            with self.subTest(user=user):
                self.client.force_login(user)
                self.assertEqual(
                    self.client.get(reverse("lantern_count")).json(),
                    {"unread": count},
                )
                for name in ["lantern", "lantern_menu"]:
                    page = self.client.get(reverse(name)).content.decode()
                    for title in sees:
                        self.assertIn(title, page)
                    for title in not_sees:
                        self.assertNotIn(title, page)

    def test_page_filters_and_pages(self):
        for index in range(3):
            self.comment(self.todo, f"Comment {index}")
        self.comment(self.secret, f"Hey {mentions.syntax(self.bob)}")
        self.client.force_login(self.bob)
        page = self.client.get(reverse("lantern"), {"mentions": "1"})
        self.assertContains(page, "Budget")
        self.assertNotContains(page, "Order the tent")
        groups, cursor = lantern.page(self.bob, size=2)
        self.assertEqual(
            [item.title for item, _e in groups], ["Budget", "Order the tent"]
        )
        groups, cursor = lantern.page(self.bob, size=2, before=cursor)
        self.assertEqual([len(e) for _i, e in groups], [2])
        self.assertIsNone(cursor)
        self.assertEqual(
            self.client.get(reverse("lantern"), {"before": "x"}).status_code, 400
        )

    def test_the_menu_is_in_the_navigation(self):
        self.client.force_login(self.cleo)
        page = self.client.get(reverse("projects"))
        self.assertContains(page, 'data-lantern="/lantern/menu/"')
        self.assertContains(page, 'data-live-socket="/ws/live/"')

    def test_mail_delivery_none_in_the_settings(self):
        self.client.force_login(self.bob)
        response = self.client.post(
            reverse("notification_settings"),
            {"notification_level": "everything", "mail_delivery": "none"},
        )
        self.assertEqual(response.status_code, 302)
        self.bob.refresh_from_db()
        self.assertEqual(self.bob.mail_delivery, MailDelivery.NONE)


class PinningTest(LanternTestCase):
    def test_pinning_bookmarks_and_unpinning_removes_the_bookmark(self):
        from biwak.bookmarks.models import Bookmark

        self.comment(self.todo, "One")
        self.comment(self.secret, "Two")
        lantern.read(self.bob, item=self.todo)
        self.client.force_login(self.bob)
        response = self.client.post(reverse("lantern_pin"), {"item": self.todo.pk})
        self.assertRedirects(response, reverse("lantern"))
        self.assertTrue(Bookmark.objects.filter(user=self.bob, item=self.todo).exists())
        pinned, unread, read, _more = lantern.menu(self.bob)
        # Read or not, with its latest notification, and only there
        self.assertEqual(
            [(i.title, len(e)) for i, e in pinned], [("Order the tent", 1)]
        )
        self.assertEqual([i.title for i, _e in unread], ["Budget"])
        self.assertEqual(read, [])
        page = self.client.get(reverse("lantern")).content.decode()
        self.assertIn("Pinned", page)
        self.assertIn("Unpin", page)
        # Bookmarked on the item's page: pinned too
        self.client.post(
            reverse("item_bookmark", args=[self.secret.pk]), {"bookmark": "1"}
        )
        self.assertEqual(
            {i.title for i, _e in lantern.pinned(self.bob)},
            {"Order the tent", "Budget"},
        )
        self.client.post(reverse("lantern_pin"), {"item": self.todo.pk, "unpin": "1"})
        self.assertFalse(
            Bookmark.objects.filter(user=self.bob, item=self.todo).exists()
        )
        self.assertEqual([i.title for i, _e in lantern.pinned(self.bob)], ["Budget"])

    def test_a_client_pins_only_what_she_sees(self):
        self.client.force_login(self.cleo)
        response = self.client.post(reverse("lantern_pin"), {"item": self.secret.pk})
        self.assertEqual(response.status_code, 404)

    def test_mark_as_unread_brings_the_latest_back(self):
        self.comment(self.todo, "One")
        self.comment(self.todo, "Two")
        lantern.read(self.bob)
        self.assertTrue(lantern.unread(self.bob, item=self.todo))
        self.assertEqual(lantern.unread_count(self.bob), 1)
        latest = Notification.objects.filter(user=self.bob).latest("created_at", "pk")
        self.assertIsNone(latest.read_at)
        self.client.force_login(self.bob)
        menu = self.client.get(reverse("lantern_menu")).content.decode()
        self.assertIn("Mark as read", menu)
        lantern.read(self.bob)
        menu = self.client.get(reverse("lantern_menu")).content.decode()
        self.assertIn("Mark as unread", menu)


class PingTest(LanternTestCase):
    """The ping telling a person's tabs that their lantern changed
    (``announce.lantern_changed()``) follows the rules of what they see"""

    def pinged(self, run):
        """The people whose tabs ``run`` pings"""
        sent = []

        def send(groups, message):
            if message["type"] == "lantern.changed":
                sent.extend(groups)

        with mock.patch.object(announce, "_send", send):
            self.act(run)
        return {int(group.removeprefix("live-person-")) for group in sent}

    def test_internal_event_doesnt_ping_a_client(self):
        """An internal comment whose notify() runs after another request
        made the item visible: the client's tabs aren't pinged (and
        ``notify()`` leaves them out on main, branch mail-race)"""
        subscribe(self.cleo, self.secret)  # e.g. from when it was visible
        with self.captureOnCommitCallbacks() as callbacks:
            ops.add_comment(self.secret, author=self.ada, content="Psst")
        self.act(
            lambda: ops.set_visibility(self.internal, visible=True, actor=self.bob)
        )

        def run():
            for callback in callbacks:
                callback()

        self.assertNotIn(self.cleo.pk, self.pinged(run))

    def test_removed_reaction_of_an_internal_event_doesnt_ping_a_client(self):
        """Reacted while the item was internal, removed once it's visible:
        a notification of the internal event (one nobody should have
        written) doesn't make the client's tabs hear of it"""
        comment = self.comment(self.todo, "Hello", author=self.cleo)
        self.act(lambda: ops.set_visibility(self.shared, visible=False, actor=self.ada))
        self.act(lambda: add_reaction(self.ada, "👍", comment=comment))
        self.act(lambda: ops.set_visibility(self.shared, visible=True, actor=self.ada))
        event = Event.objects.get(action="reacted")
        self.assertFalse(event.is_client_visible)
        Notification.objects.create(user=self.cleo, event=event)
        self.assertEqual(
            self.pinged(lambda: remove_reaction(self.ada, "👍", comment=comment)),
            set(),
        )


class FaviconTest(LanternTestCase):
    def test_the_setting(self):
        self.client.force_login(self.bob)
        page = self.client.get(reverse("projects"))
        self.assertNotContains(page, "data-lantern-favicon")
        self.client.post(
            reverse("notification_settings"),
            {
                "notification_level": "everything",
                "mail_delivery": "each",
                "lantern_in_favicon": "on",
            },
        )
        self.bob.refresh_from_db()
        self.assertTrue(self.bob.lantern_in_favicon)
        self.assertContains(
            self.client.get(reverse("projects")), "data-lantern-favicon"
        )


class APITest(LanternTestCase):
    def call(self, method, user, path, data=None):
        from biwak.accounts.models import APIToken

        _token, secret = APIToken.create_for(user=user, title="T", access="write")
        return getattr(self.client, method)(
            f"/api/v1/{path}",
            data,
            content_type="application/json",
            headers={"Authorization": f"Bearer {secret}"},
        )

    def test_list_as_staff_and_client(self):
        self.comment(self.todo, "Visible")
        self.comment(self.secret, f"Internal {mentions.syntax(self.bob)}")
        lantern.pin(self.bob, self.todo)
        data = self.call("get", self.bob, "lantern/").json()
        self.assertEqual(
            [
                (e["event"]["item"]["title"], e["read"], e["mentioned"], e["pinned"])
                for e in data["results"]
            ],
            [("Budget", False, True, False), ("Order the tent", False, False, True)],
        )
        data = self.call("get", self.bob, "lantern/?mentions=true").json()
        self.assertEqual(len(data["results"]), 1)
        data = self.call("get", self.cleo, "lantern/").json()
        self.assertEqual(
            [e["event"]["item"]["title"] for e in data["results"]], ["Order the tent"]
        )
        self.assertTrue(data["results"][0]["event"]["visible_to_clients"])

    def test_read(self):
        self.comment(self.todo, "Visible")
        self.comment(self.secret, "Internal")
        response = self.call(
            "post", self.bob, "lantern/read/", {"item_id": self.todo.pk}
        )
        self.assertEqual(response.json(), {"read": 1})
        data = self.call("get", self.bob, "lantern/?unread=true").json()
        self.assertEqual(
            [e["event"]["item"]["title"] for e in data["results"]], ["Budget"]
        )
        self.assertEqual(
            self.call("post", self.bob, "lantern/read/", {"all": True}).json(),
            {"read": 1},
        )
        for data in [{}, {"all": True, "item_id": self.todo.pk}]:
            self.assertEqual(
                self.call("post", self.bob, "lantern/read/", data).status_code, 400
            )
        # Clients: reading all counts only what they see
        self.act(lambda: ops.set_visibility(self.shared, visible=False, actor=self.ada))
        self.assertEqual(
            self.call("post", self.cleo, "lantern/read/", {"all": True}).json(),
            {"read": 0},
        )
        # Internal items don't exist
        response = self.call(
            "post", self.cleo, "lantern/read/", {"item_id": self.secret.pk}
        )
        self.assertEqual(response.status_code, 404)
