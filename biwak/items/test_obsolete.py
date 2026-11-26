"""Marking a to-do obsolete: completed, but not done (specs/stale-todos.md)"""

import datetime as dt
import json

from django.core import mail
from django.test import TestCase
from django.utils import timezone

from biwak.accounts.models import APIToken
from biwak.activity import timeline
from biwak.activity.mails import send_mails
from biwak.activity.models import Action, Event
from biwak.activity.operations import subscribe
from biwak.items import operations as ops
from biwak.items.models import Item, Todo
from biwak.palette.test_actions import palette_data
from biwak.test_utils import person, project


class ObsoleteBase(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.bob, self.cleo])
        self.list = ops.create_list(
            project=self.project, title="Shared", creator=self.ada, visible=True
        )
        self.internal = ops.create_list(
            project=self.project, title="Internal", creator=self.ada
        )
        self.todo = ops.create_todo(
            todolist=self.list, title="Order the tent", creator=self.ada
        )

    def reload(self, item):
        return Todo.objects.get(item=item)


class OperationsTest(ObsoleteBase):
    def test_marking_and_reopening(self):
        for user in [self.bob, self.cleo]:
            with self.subTest(user=user):
                ops.mark_obsolete(self.todo, actor=user)
                todo = self.reload(self.todo)
                self.assertTrue(todo.obsolete)
                self.assertTrue(todo.is_completed)
                self.assertEqual(todo.completed_by, user)
                event = Event.objects.filter(item=self.todo).first()
                self.assertEqual(
                    (event.action, event.actor), (Action.MARKED_OBSOLETE, user)
                )
                self.assertTrue(event.is_client_visible)
                # Already completed: nothing happens
                ops.mark_obsolete(self.todo, actor=self.ada)
                self.assertEqual(
                    Event.objects.filter(
                        item=self.todo, action=Action.MARKED_OBSOLETE
                    ).count(),
                    1 if user == self.bob else 2,
                )
                ops.reopen(self.todo, actor=user)
                todo = self.reload(self.todo)
                self.assertFalse(todo.obsolete)
                self.assertIsNone(todo.completed_at)

    def test_completing_is_not_obsolete(self):
        ops.complete(self.todo, actor=self.ada)
        self.assertFalse(self.reload(self.todo).obsolete)

    def test_by_biwak_is_internal(self):
        """Clients see the to-do as obsolete but aren't told"""
        ops.mark_obsolete(self.todo, actor=None)
        todo = self.reload(self.todo)
        self.assertTrue(todo.obsolete)
        self.assertIsNone(todo.completed_by)
        event = Event.objects.filter(item=self.todo).first()
        self.assertIsNone(event.actor)
        self.assertFalse(event.is_client_visible)

    def test_net_change(self):
        """Completed, reopened and marked obsolete: obsolete is what's left;
        marked obsolete and reopened: nothing"""
        ops.complete(self.todo, actor=self.ada)
        ops.reopen(self.todo, actor=self.ada)
        ops.mark_obsolete(self.todo, actor=self.ada)
        events = list(Event.objects.filter(item=self.todo).order_by("pk"))
        self.assertEqual(timeline.cancelled(events), {e.pk for e in events[1:3]})
        ops.reopen(self.todo, actor=self.ada)
        events = list(Event.objects.filter(item=self.todo).order_by("pk"))
        self.assertEqual(timeline.cancelled(events), {e.pk for e in events[1:]})

    def test_recurring_ends_the_series(self):
        todo = ops.create_todo(
            todolist=self.list,
            title="Water the plants",
            creator=self.ada,
            due_on=self.todo.created_at.date(),
            recurrence="FREQ=WEEKLY",
        )
        ops.mark_obsolete(todo, actor=self.ada)
        self.assertFalse(Item.objects.filter(todo__previous=todo).exists())
        # Completing a recurring one still makes the next
        other = ops.create_todo(
            todolist=self.list,
            title="Feed the cat",
            creator=self.ada,
            due_on=self.todo.created_at.date(),
            recurrence="FREQ=WEEKLY",
        )
        ops.complete(other, actor=self.ada)
        self.assertTrue(Item.objects.filter(todo__previous=other).exists())


class PagesTest(ObsoleteBase):
    def test_more_menu_and_palette(self):
        url = f"/todos/{self.todo.pk}/obsolete/"
        for user in [self.ada, self.cleo]:
            with self.subTest(user=user):
                self.client.force_login(user)
                response = self.client.get(self.todo.get_absolute_url())
                self.assertContains(response, f'action="{url}')
                self.assertContains(response, "Mark as obsolete")
                actions = {a["label"]: a for a in palette_data(response)["actions"]}
                self.assertEqual(actions["Mark as obsolete"]["url"], url)
                self.assertEqual(actions["Mark as obsolete"]["type"], "post")

    def test_marking_from_the_page(self):
        self.client.force_login(self.cleo)
        response = self.client.post(f"/todos/{self.todo.pk}/obsolete/")
        self.assertRedirects(
            response, self.todo.get_absolute_url(), fetch_redirect_response=False
        )
        self.assertTrue(self.reload(self.todo).obsolete)
        response = self.client.get(self.todo.get_absolute_url())
        # Not offered once completed
        self.assertNotContains(response, "Mark as obsolete")
        self.assertContains(response, "Marked as obsolete by")
        self.assertContains(
            response, '<span class="badge wb-tone-neutral">Obsolete</span>'
        )
        self.assertContains(response, "marked this as obsolete")
        # The list's completed rows
        response = self.client.get(self.list.get_absolute_url())
        self.assertContains(response, "Completed (1)")
        self.assertContains(
            response, '<span class="badge wb-tone-neutral">Obsolete</span>'
        )
        # The feed
        self.client.force_login(self.ada)
        response = self.client.get("/feed/")
        self.assertContains(response, "marked")
        self.assertContains(response, "as obsolete")

    def test_by_biwak_on_the_page(self):
        ops.mark_obsolete(self.todo, actor=None)
        self.client.force_login(self.ada)
        response = self.client.get(self.todo.get_absolute_url())
        self.assertContains(
            response, "Marked as obsolete after 90 days without activity"
        )

    def test_client_gets_404_for_internal(self):
        todo = ops.create_todo(todolist=self.internal, title="Secret", creator=self.ada)
        self.client.force_login(self.cleo)
        response = self.client.post(f"/todos/{todo.pk}/obsolete/")
        self.assertEqual(response.status_code, 404)
        self.assertFalse(self.reload(todo).obsolete)

    def test_mail_says_obsolete(self):
        subscribe(self.bob, self.todo)
        with self.captureOnCommitCallbacks(execute=True):
            ops.mark_obsolete(self.todo, actor=self.ada)
        with self.captureOnCommitCallbacks(execute=True):
            send_mails(now=timezone.now() + dt.timedelta(minutes=11))
        message = next(m for m in mail.outbox if m.to == [self.bob.email])
        self.assertIn("Ada Example marked it as obsolete.", message.body)
        self.assertIn("Obsolete.", message.body)


class APITest(ObsoleteBase):
    def call(self, user, path, method="post"):
        _token, secret = APIToken.create_for(user=user, title="T", access="write")
        return getattr(self.client, method)(
            f"/api/v1/{path}", headers={"authorization": f"Bearer {secret}"}
        )

    def test_obsolete(self):
        response = self.call(self.cleo, f"todos/{self.todo.pk}/obsolete/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["obsolete"])
        self.assertIsNotNone(data["completed_at"])
        response = self.call(self.ada, f"lists/{self.list.pk}/todos/completed/", "get")
        self.assertTrue(response.json()["results"][0]["obsolete"])
        response = self.call(self.ada, f"todos/{self.todo.pk}/reopen/")
        self.assertFalse(response.json()["obsolete"])

    def test_client_gets_404_for_internal(self):
        todo = ops.create_todo(todolist=self.internal, title="Secret", creator=self.ada)
        response = self.call(self.cleo, f"todos/{todo.pk}/obsolete/")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(json.loads(response.content).get("obsolete"), None)
