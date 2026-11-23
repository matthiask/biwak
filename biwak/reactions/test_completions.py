"""Reactions to a to-do getting completed: on its ``completed`` event, the
line "Ada completed this" on the timeline (specs/reactions.md, decided
2026-11-23)"""

import datetime as dt
import json
from unittest import mock

from django.core import mail
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone

from biwak.activity.mails import send_mails
from biwak.activity.models import Action, Event, Notification
from biwak.activity.operations import subscribe
from biwak.items import operations as ops
from biwak.live import announce
from biwak.reactions import operations
from biwak.reactions.models import Reaction
from biwak.test_utils import person, project


class Base(TestCase):
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
            todolist=self.internal, title="Secret plan", creator=self.ada
        )

    def complete(self, todo=None, actor=None):
        """Completes the to-do; returns its ``completed`` event"""
        todo = todo or self.todo
        ops.complete(todo, actor=actor or self.bob)
        return Event.objects.filter(item=todo, action=Action.COMPLETED).latest("pk")

    def age(self, events, minutes):
        events.update(created_at=timezone.now() - dt.timedelta(minutes=minutes))


class OperationsTest(Base):
    def test_added_and_toggled(self):
        event = self.complete()
        self.assertTrue(operations.add_reaction(self.ada, "🎉", event=event))
        self.assertFalse(operations.add_reaction(self.ada, "🎉", event=event))
        reaction = Reaction.objects.get()
        self.assertEqual(
            (reaction.item, reaction.comment, reaction.event),
            (self.todo, None, event),
        )
        reacted = Event.objects.get(action=Action.REACTED)
        self.assertEqual(reacted.data["event"], event.pk)
        self.assertEqual(reacted.item, self.todo)
        self.assertFalse(operations.toggle_reaction(self.ada, "🎉", event=event))
        self.assertFalse(Reaction.objects.exists())
        self.assertFalse(Event.objects.filter(action=Action.REACTED).exists())

    def test_apart_from_the_todos_own(self):
        """A critical reaction to the to-do and a happy one to it getting
        done: the same content on both, removed one at a time"""
        event = self.complete()
        operations.add_reaction(self.ada, "👎", item=self.todo)
        operations.add_reaction(self.ada, "👎", event=event)
        self.assertEqual(Reaction.objects.count(), 2)
        self.assertEqual(
            [e["content"] for e in operations.summary(self.todo, None, self.ada)],
            ["👎"],
        )
        self.assertEqual(
            operations.summary(self.todo, None, self.ada, event)[0]["count"], 1
        )
        operations.remove_reaction(self.ada, "👎", item=self.todo)
        self.assertEqual(Reaction.objects.get().event, event)
        reacted = Event.objects.get(action=Action.REACTED)
        self.assertEqual(reacted.data["event"], event.pk)

    def test_only_completing_todos(self):
        self.complete()
        ops.reopen(self.todo, actor=self.bob)
        reopened = Event.objects.get(action=Action.REOPENED)
        with self.assertRaises(ValidationError):
            operations.add_reaction(self.ada, "🎉", event=reopened)
        with self.assertRaises(ValueError):
            operations.add_reaction(
                self.ada, "🎉", item=self.todo, event=self.complete()
            )

    def test_never_on_a_comment_and_an_event(self):
        event = self.complete()
        comment = ops.add_comment(self.todo, author=self.ada, content="Hi")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Reaction.objects.bulk_create([
                Reaction(
                    user=self.ada,
                    item=self.todo,
                    comment=comment,
                    event=event,
                    content="🎉",
                )
            ])

    def test_internal_completing_internal_reaction(self):
        """Completed while clients didn't see the to-do: the reaction is
        internal too, even though they see the to-do now"""
        event = self.complete(self.secret)
        ops.set_visibility(self.internal, visible=True, actor=self.ada)
        operations.add_reaction(self.ada, "🎉", event=event)
        reacted = Event.objects.get(action=Action.REACTED)
        self.assertFalse(reacted.is_client_visible)
        self.assertFalse(Reaction.objects.visible_to(self.cleo).exists())
        self.assertTrue(Reaction.objects.visible_to(self.bob).exists())

    def test_deleting_the_item_takes_them(self):
        event = self.complete()
        operations.add_reaction(self.ada, "🎉", event=event)
        self.todo.delete()
        self.assertFalse(Reaction.objects.exists())


class TimelineTest(Base):
    def page(self, user=None, todo=None):
        self.client.force_login(user or self.ada)
        response = self.client.get((todo or self.todo).get_absolute_url())
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_offered_on_the_completion_line(self):
        event = self.complete()
        operations.add_reaction(self.ada, "🎉", event=event)
        html = self.page()
        self.assertIn(f'id="reactions-event-{event.pk}"', html)
        self.assertIn(f'action="/events/{event.pk}/reactions/"', html)
        # On the to-do itself: not counted
        item_block = html[html.index(f'id="reactions-item-{self.todo.pk}"') :]
        item_block = item_block[: item_block.index("</details>")]
        self.assertNotIn("🎉 <span", item_block)

    def test_not_on_other_lines(self):
        ops.update_todo(
            self.todo,
            actor=self.bob,
            due_on=dt.date(2026, 12, 1),
        )
        self.assertNotIn("reactions-event-", self.page())

    def test_merged_line_latest_completion(self):
        """Completed, reopened and completed in one line: the reactions are
        the latest completing's; moved in the same line still offers them"""
        first = self.complete()
        ops.reopen(self.todo, actor=self.bob)
        second = self.complete()
        html = self.page()
        self.assertIn(f"reactions-event-{second.pk}", html)
        self.assertNotIn(f"reactions-event-{first.pk}", html)

    def test_cancelled_out_offers_none(self):
        event = self.complete()
        operations.add_reaction(self.ada, "🎉", event=event)
        ops.reopen(self.todo, actor=self.bob)
        self.assertNotIn("reactions-event-", self.page())
        # Kept, unshown
        self.assertTrue(Reaction.objects.exists())

    def test_reopened_later_stays_on_its_line(self):
        event = self.complete()
        operations.add_reaction(self.ada, "🎉", event=event)
        self.age(Event.objects.filter(pk=event.pk), 60)
        ops.reopen(self.todo, actor=self.bob)
        html = self.page()
        self.assertIn(f"reactions-event-{event.pk}", html)
        self.assertIn("reopened this", html)

    def test_client_sees_and_reacts(self):
        event = self.complete()
        self.assertIn(f"reactions-event-{event.pk}", self.page(self.cleo))
        response = self.client.post(
            f"/events/{event.pk}/reactions/", {"content": "🎉", "action": "add"}
        )
        self.assertRedirects(
            response,
            f"{self.todo.get_absolute_url()}#reactions-event-{event.pk}",
            fetch_redirect_response=False,
        )
        self.assertEqual(Reaction.objects.get().user, self.cleo)

    def test_client_404_for_internal(self):
        event = self.complete(self.secret)
        self.client.force_login(self.cleo)
        for url in [
            f"/events/{event.pk}/reactions/",
            f"/events/{event.pk}/reactions/remove/?content=x",
        ]:
            self.assertEqual(self.client.post(url, {"content": "🎉"}).status_code, 404)
        # From when it was internal, though it's visible now
        ops.set_visibility(self.internal, visible=True, actor=self.ada)
        self.assertNotIn(
            f"reactions-event-{event.pk}", self.page(self.cleo, self.secret)
        )
        response = self.client.post(f"/events/{event.pk}/reactions/", {"content": "🎉"})
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Reaction.objects.exists())
        # Staff can
        self.assertIn(f"reactions-event-{event.pk}", self.page(self.ada, self.secret))

    def test_not_for_other_events(self):
        self.complete()
        ops.reopen(self.todo, actor=self.bob)
        reopened = Event.objects.get(action=Action.REOPENED)
        self.client.force_login(self.ada)
        response = self.client.post(
            f"/events/{reopened.pk}/reactions/", {"content": "🎉"}
        )
        self.assertEqual(response.status_code, 404)

    def test_htmx_swaps_the_block_and_removing_asks(self):
        event = self.complete()
        self.client.force_login(self.ada)
        response = self.client.post(
            f"/events/{event.pk}/reactions/",
            {"content": "🎉", "action": "add"},
            headers={"HX-Request": "true"},
        )
        self.assertContains(response, f'id="reactions-event-{event.pk}"')
        self.assertContains(response, "is-mine")
        self.assertContains(
            response, f"/events/{event.pk}/reactions/remove/?content=%F0%9F%8E%89"
        )
        response = self.client.get(
            f"/events/{event.pk}/reactions/remove/", {"content": "🎉"}
        )
        self.assertContains(response, f'action="/events/{event.pk}/reactions/"')
        self.client.post(
            f"/events/{event.pk}/reactions/", {"content": "🎉", "action": "remove"}
        )
        self.assertFalse(Reaction.objects.exists())


class APITest(Base):
    def setUp(self):
        super().setUp()
        self.event = self.complete()

    def api(self, method, path, user, data=None):
        self.client.force_login(user)
        return getattr(self.client, method)(
            f"/api/v1/{path}",
            json.dumps(data) if data is not None else None,
            content_type="application/json",
        )

    def test_add_list_remove(self):
        path = f"events/{self.event.pk}/reactions/"
        response = self.api("post", path, self.cleo, {"content": "🎉"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()[0]["content"], "🎉")
        self.assertTrue(response.json()[0]["mine"])
        listed = self.api("get", path, self.ada).json()
        self.assertEqual((listed[0]["count"], listed[0]["mine"]), (1, False))
        # Not the to-do's own
        todo = self.api("get", f"todos/{self.todo.pk}/", self.ada).json()
        self.assertEqual(todo["reactions"], [])
        response = self.api("delete", path, self.cleo, {"content": "🎉"})
        self.assertEqual(response.json(), [])

    def test_404(self):
        secret = self.complete(self.secret)
        path = f"events/{secret.pk}/reactions/"
        self.assertEqual(self.api("get", path, self.cleo).status_code, 404)
        response = self.api("post", path, self.cleo, {"content": "🎉"})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.api("get", path, self.ada).status_code, 200)
        created = Event.objects.get(action=Action.CREATED, item=self.todo)
        path = f"events/{created.pk}/reactions/"
        self.assertEqual(self.api("get", path, self.ada).status_code, 404)


@override_settings(
    BASE_URL="https://biwak.example.org", DEFAULT_FROM_EMAIL="biwak@example.org"
)
class NotifyingTest(Base):
    def setUp(self):
        super().setUp()
        # Ada created it and Carl follows along: neither hears of it
        subscribe(self.carl, self.todo)
        self.event = self.complete()
        Notification.objects.all().delete()

    def react(self, user, content):
        with self.captureOnCommitCallbacks(execute=True):
            operations.toggle_reaction(user, content, event=self.event)

    def told(self):
        return {n.user for n in Notification.objects.select_related("user")}

    def test_the_person_who_completed_it(self):
        self.react(self.ada, "🎉")
        self.assertEqual(self.told(), {self.bob})

    def test_nobody_for_yourself(self):
        self.react(self.bob, "🎉")
        self.assertEqual(self.told(), set())

    def test_a_client_who_completed_it(self):
        todo = ops.create_todo(todolist=self.shared, title="Theirs", creator=self.ada)
        self.event = self.complete(todo, self.cleo)
        Notification.objects.all().delete()
        self.react(self.ada, "🎉")
        self.assertEqual(self.told(), {self.cleo})

    def test_mail(self):
        self.react(self.ada, "🎉")
        self.react(self.carl, "Well done!")
        operations.add_reaction(self.carl, "👍", item=self.todo)
        with self.captureOnCommitCallbacks(execute=True):
            send_mails(now=timezone.now() + dt.timedelta(minutes=11))
        self.assertEqual([m.to for m in mail.outbox], [[self.bob.email]])
        body = mail.outbox[0].body
        self.assertIn(
            "Reactions to you completing it:\nAda Example: 🎉, Carl Example: Well done!",
            body,
        )
        # The to-do's own reaction is Ada's to hear of
        self.assertNotIn("👍", body)

    def test_lantern(self):
        self.react(self.ada, "🎉")
        self.client.force_login(self.bob)
        response = self.client.get("/lantern/")
        self.assertContains(
            response, f"{self.todo.get_absolute_url()}#reactions-event-{self.event.pk}"
        )
        self.assertContains(response, "reacted 🎉")

    def test_feed(self):
        self.react(self.ada, "🎉")
        self.client.force_login(self.carl)
        response = self.client.get("/feed/")
        self.assertContains(response, "being completed")


class LiveTest(Base):
    def announced(self, op, *args, **kwargs):
        sent = []
        with (
            mock.patch.object(
                announce, "_send", lambda groups, message: sent.extend(groups)
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            op(*args, **kwargs)
        return set(sent)

    def test_added_and_removed(self):
        event = self.complete()
        group = announce.item_group(self.todo.pk, clients=True)
        for op in [operations.add_reaction, operations.remove_reaction]:
            self.assertIn(group, self.announced(op, self.ada, "🎉", event=event))

    def test_clients_pages_not_told_of_an_internal_completing(self):
        event = self.complete(self.secret)
        ops.set_visibility(self.internal, visible=True, actor=self.ada)
        clients = announce.item_group(self.secret.pk, clients=True)
        staff = announce.item_group(self.secret.pk, clients=False)
        for op in [operations.add_reaction, operations.remove_reaction]:
            groups = self.announced(op, self.ada, "🎉", event=event)
            self.assertIn(staff, groups)
            self.assertNotIn(clients, groups)
