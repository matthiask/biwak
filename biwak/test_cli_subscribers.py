"""``biwak subscriptions``; the CLI test case is the
one of test_cli.py"""

import json

from biwak import test_cli
from biwak.activity.models import Action, Event, Subscription
from biwak.items import operations as ops
from biwak.test_utils import person


class SubscribersCLITest(test_cli.CLITest):
    def make(self):
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.project.memberships.create(user=self.bob)
        self.project.memberships.create(user=self.cleo)
        self.todo = ops.create_todo(
            todolist=self.list, title="Order the tent", creator=self.ada
        )

    def test_subscribers(self):
        self.make()
        output = self.biwak("subscriptions", "--item", self.todo.pk).output
        self.assertIn(f"Subscribers of #{self.todo.pk} [clients]", output)
        self.assertIn("Ada Example", output)
        data = json.loads(
            self.biwak("subscriptions", "--item", self.todo.pk, "--json").stdout
        )
        self.assertTrue(data["visible_to_clients"])
        self.assertEqual(data["subscribers"][0]["person"]["name"], "Ada Example")

    def test_subscribe_quietly(self):
        self.make()
        result = self.biwak(
            "subscriptions", "add", self.todo.pk, "--people", f"{self.bob.pk}"
        )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Subscribed 1", result.output)
        self.assertIn("Clients can see this", result.output)
        self.assertEqual(
            Subscription.objects.get(user=self.bob, item=self.todo).added_by, self.ada
        )
        self.assertFalse(Event.objects.filter(action=Action.SHARED))

    def test_subscribe_and_tell_them_now(self):
        self.make()
        result = self.biwak(
            "subscriptions",
            "add",
            self.todo.pk,
            "--people",
            f"{self.bob.pk},{self.cleo.pk}",
            "--notify",
            "--note",
            "Soon",
            "--json",
        )
        self.assertEqual(result.exit_code, 0, result.output)
        event = Event.objects.get(action=Action.SHARED)
        self.assertEqual(event.data["note"], "Soon")
        self.assertEqual(event.data["people"], [self.bob.pk, self.cleo.pk])
        names = {r["person"]["name"] for r in json.loads(result.stdout)["subscribers"]}
        self.assertIn("Bob Example", names)

    def test_errors(self):
        self.make()
        result = self.biwak("subscriptions", "add", self.todo.pk, "--people", "x")
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("IDs separated by commas", result.output)
        result = self.biwak("subscriptions", "add", self.todo.pk, "--people", "999999")
        self.assertNotEqual(result.exit_code, 0)
        result = self.biwak(
            "subscriptions", "add", self.todo.pk, "--people", self.bob.pk, access="read"
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertFalse(Subscription.objects.filter(user=self.bob))

    def test_subscribing_and_unsubscribing_oneself(self):
        """Subscribing is the switch (specs/notifications.md, "Subscriptions")"""
        self.make()
        Subscription.objects.filter(user=self.ada).delete()
        output = self.biwak("subscriptions", "add", self.todo.pk).output
        self.assertIn(f"Subscribed to #{self.todo.pk}.", output)
        self.assertTrue(Subscription.objects.filter(user=self.ada).exists())
        output = self.biwak("subscriptions", "remove", self.todo.pk).output
        self.assertIn(f"Unsubscribed from #{self.todo.pk}.", output)
        self.assertFalse(Subscription.objects.filter(user=self.ada).exists())
        # Not while assigned
        ops.assign(self.todo, [self.ada], actor=self.bob)
        result = self.biwak("subscriptions", "remove", self.todo.pk)
        self.assertEqual(result.exit_code, 1)
        self.assertIn("400", result.output)
        # No level for a to-do, only for lists
        result = self.biwak("notifications", "--item", self.todo.pk)
        self.assertIn("Only lists have a level", result.output)
