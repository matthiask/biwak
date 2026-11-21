"""Assigned means subscribed, and adding others to an item's subscribers
with "Tell them now" (specs/subscribers.md)"""

import datetime as dt

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from biwak.accounts.models import APIToken, MailDelivery, NotificationLevel
from biwak.activity import lantern
from biwak.activity.mails import describe, send_mails, unsubscribe_token
from biwak.activity.models import Action, Event, Notification, Subscription
from biwak.activity.operations import (
    StillAssigned,
    share,
    subscribable_people,
    subscribe,
    unsubscribe,
)
from biwak.items import operations as ops
from biwak.palette.test_actions import palette_data
from biwak.test_utils import MODAL, assert_modal, assert_page, partner, person, project


class SubscribersTestCase(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.dan = person("Dan")  # staff, not a member
        self.cleo = person("Cleo", client=True)
        self.eli = person("Eli", client=True)
        self.pia = partner("Pia")
        self.project = project(
            members=[self.ada, self.bob, self.cleo, self.eli, self.pia]
        )
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

    def url(self, item):
        return f"/items/{item.pk}/subscribers/"

    def act(self, run):
        with self.captureOnCommitCallbacks(execute=True):
            return run()


class AssignedMeansSubscribedTest(SubscribersTestCase):
    def setUp(self):
        super().setUp()
        ops.assign(self.todo, [self.bob], actor=self.ada)

    def test_the_check(self):
        with self.assertRaises(StillAssigned):
            unsubscribe(self.bob, self.todo)
        self.assertTrue(Subscription.objects.filter(user=self.bob, item=self.todo))
        # Unassigned again: it works as before
        ops.unassign(self.todo, [self.bob], actor=self.ada)
        unsubscribe(self.bob, self.todo)
        self.assertFalse(Subscription.objects.filter(user=self.bob, item=self.todo))

    def test_page_offers_unassigning(self):
        self.client.force_login(self.bob)
        response = self.client.get(self.todo.get_absolute_url())
        self.assertContains(response, "You're assigned, so you hear about it.")
        self.assertContains(response, "Unassign me")
        self.assertNotContains(response, ">Unsubscribe<")
        # Others still unsubscribe
        self.client.force_login(self.ada)
        response = self.client.get(self.todo.get_absolute_url())
        self.assertContains(response, ">Unsubscribe<")

    def test_page_unsubscribing_does_nothing(self):
        self.client.force_login(self.bob)
        response = self.client.post(f"/items/{self.todo.pk}/subscription/")
        self.assertEqual(response.status_code, 400)
        self.assertTrue(Subscription.objects.filter(user=self.bob, item=self.todo))

    def test_unassign_me(self):
        self.client.force_login(self.bob)
        response = self.client.post(
            f"/items/{self.todo.pk}/subscription/", {"unassign": "1"}
        )
        self.assertRedirects(response, self.todo.get_absolute_url())
        self.assertFalse(self.todo.todo.assignees.exists())
        # Still subscribed until they unsubscribe
        self.assertTrue(Subscription.objects.filter(user=self.bob, item=self.todo))
        self.client.post(f"/items/{self.todo.pk}/subscription/")
        self.assertFalse(Subscription.objects.filter(user=self.bob, item=self.todo))

    def test_mail_link_does_nothing_and_explains(self):
        url = f"/unsubscribe/{unsubscribe_token(self.bob, self.todo)}/"
        response = self.client.get(url)
        self.assertContains(response, "You're assigned")
        self.assertContains(response, "Order the tent")
        self.assertNotContains(response, "Unsubscribe?")
        response = self.client.post(url, {"List-Unsubscribe": "One-Click"})
        self.assertContains(response, "You're assigned")
        self.assertNotContains(response, "Unsubscribed")
        self.assertTrue(Subscription.objects.filter(user=self.bob, item=self.todo))

    def test_api_answers_400(self):
        _token, secret = APIToken.create_for(user=self.bob, title="T", access="write")
        response = self.client.delete(
            f"/api/v1/items/{self.todo.pk}/subscription/",
            headers={"authorization": f"Bearer {secret}"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("assigned", response.json()["detail"])

    def test_palette(self):
        self.client.force_login(self.bob)
        response = self.client.get(self.todo.get_absolute_url())
        actions = {a["label"]: a for a in palette_data(response)["actions"]}
        self.assertEqual(actions["Unassign me"]["data"], {"unassign": "1"})
        self.assertNotIn("Unsubscribe", actions)


class OperationTest(SubscribersTestCase):
    def test_subscribable_people(self):
        for viewer, expected in [
            # Staff of the own organization: everybody who sees it
            (self.ada, {self.bob, self.dan, self.cleo, self.eli, self.pia}),
            # Clients: the members
            (self.cleo, {self.ada, self.bob, self.eli, self.pia}),
            # Partners: the project's people, staff with access too (decided
            # 2026-11-21)
            (self.pia, {self.ada, self.bob, self.cleo, self.dan, self.eli}),
        ]:
            with self.subTest(viewer=viewer):
                self.assertEqual(set(subscribable_people(self.todo, viewer)), expected)
        # Internal: no clients
        self.assertEqual(
            set(subscribable_people(self.secret, self.ada)),
            {self.bob, self.dan, self.pia},
        )

    def test_quiet(self):
        told = self.act(lambda: share(self.todo, [self.bob, self.cleo], actor=self.ada))
        self.assertEqual(told, [self.bob, self.cleo])
        self.assertEqual(
            Subscription.objects.get(user=self.bob, item=self.todo).added_by, self.ada
        )
        self.assertFalse(Event.objects.filter(action=Action.SHARED))
        self.assertFalse(Notification.objects.exists())

    def test_overrides_an_unsubscription(self):
        subscribe(self.bob, self.todo)
        unsubscribe(self.bob, self.todo)
        share(self.todo, [self.bob], actor=self.ada)
        self.assertTrue(Subscription.objects.filter(user=self.bob, item=self.todo))

    def test_refuses_people_who_cannot_see_it(self):
        with self.assertRaises(ValueError):
            share(self.secret, [self.cleo], actor=self.ada)
        with self.assertRaises(ValueError):
            share(self.todo, [self.bob], actor=self.bob)  # oneself
        with self.assertRaises(ValueError):
            share(self.todo, [self.dan], actor=self.cleo)  # not known to them
        self.assertFalse(Subscription.objects.filter(user=self.cleo, item=self.secret))

    def test_note_is_one_line_of_at_most_200_characters(self):
        share(self.todo, [self.bob], actor=self.ada, notify=True, note=" a\n  b ")
        self.assertEqual(Event.objects.get(action=Action.SHARED).data["note"], "a b")
        with self.assertRaises(ValueError):
            share(self.todo, [self.bob], actor=self.ada, notify=True, note="x" * 201)

    def test_tell_them_now(self):
        subscribe(self.pia, self.todo)  # an old subscriber isn't told
        told = self.act(
            lambda: share(
                self.todo,
                [self.bob, self.cleo],
                actor=self.ada,
                notify=True,
                note="Soon",
            )
        )
        self.assertEqual(told, [self.bob, self.cleo])
        event = Event.objects.get(action=Action.SHARED)
        self.assertEqual(event.item, self.todo)
        self.assertEqual(event.data["people"], [self.bob.pk, self.cleo.pk])
        self.assertTrue(event.is_client_visible)
        self.assertEqual(
            {n.user for n in Notification.objects.filter(event=event)},
            {self.bob, self.cleo},
        )


class ToldTest(SubscribersTestCase):
    """The notification: the lantern's line, the mail, the levels"""

    def share(self, *people, note="Soon"):
        return self.act(
            lambda: share(
                self.todo, list(people), actor=self.ada, notify=True, note=note
            )
        )

    def test_lantern_line(self):
        self.share(self.bob)
        [notification] = lantern.prepare(
            list(lantern.notifications_for(self.bob)), self.bob
        )
        self.assertEqual(notification.line, "Ada Example wants you to see this: Soon")
        self.assertFalse(notification.mentioned)

    def test_without_a_note(self):
        self.share(self.bob, note="")
        event = Event.objects.get(action=Action.SHARED)
        self.assertEqual(
            describe(event, self.bob), "Ada Example wants you to see this."
        )

    def test_levels(self):
        """It concerns them: "only what concerns me" lets it through,
        "nothing" doesn't"""
        self.bob.notification_level = NotificationLevel.CONCERNS_ME
        self.bob.save()
        self.pia.notification_level = NotificationLevel.NOTHING
        self.pia.save()
        self.share(self.bob, self.pia, self.cleo)
        self.assertEqual(
            set(Notification.objects.values_list("user__email", flat=True)),
            {self.bob.email, self.cleo.email},
        )

    @override_settings(
        BASE_URL="https://biwak.example.org", DEFAULT_FROM_EMAIL="biwak@example.org"
    )
    def test_mail(self):
        self.share(self.bob, self.cleo)
        with self.captureOnCommitCallbacks(execute=True):
            send_mails(now=timezone.now() + dt.timedelta(minutes=11))
        self.assertEqual(
            {m.to[0] for m in mail.outbox}, {self.bob.email, self.cleo.email}
        )
        message = next(m for m in mail.outbox if m.to == [self.bob.email])
        self.assertEqual(message.subject, "[Website] Order the tent")
        self.assertIn("Ada Example wants you to see this: Soon", message.body)

    def test_not_the_other_subscribers(self):
        subscribe(self.pia, self.todo)
        self.share(self.bob)
        self.assertEqual({n.user for n in Notification.objects.all()}, {self.bob})

    def test_mail_setting_decides_about_mail(self):
        self.bob.mail_delivery = MailDelivery.DIGEST
        self.bob.save()
        self.share(self.bob)
        with self.captureOnCommitCallbacks(execute=True):
            send_mails(now=timezone.now() + dt.timedelta(minutes=11))
        self.assertEqual(mail.outbox, [])
        # The lantern has it anyway
        self.assertEqual(Notification.objects.filter(user=self.bob).count(), 1)


class FeedTest(SubscribersTestCase):
    def test_feed_names_the_people(self):
        self.act(
            lambda: share(self.todo, [self.bob, self.cleo], actor=self.ada, notify=True)
        )
        self.client.force_login(self.ada)
        response = self.client.get("/feed/")
        self.assertRegex(
            response.content.decode(),
            r"shared\s+<a[^>]*>Order the tent</a>\s+with\s+Bob,\s+Cleo",
        )

    def test_clients_follow_the_event_rules(self):
        self.act(
            lambda: share(self.todo, [self.bob, self.cleo], actor=self.ada, notify=True)
        )
        self.act(lambda: share(self.secret, [self.dan], actor=self.ada, notify=True))
        self.client.force_login(self.cleo)
        response = self.client.get("/feed/")
        self.assertRegex(response.content.decode(), r"with\s+Bob,\s+Cleo")
        # Internal events never
        self.assertNotContains(response, "Budget")
        self.assertNotContains(response, "Dan")
        # Not known to a client
        self.act(lambda: share(self.todo, [self.dan], actor=self.ada, notify=True))
        response = self.client.get("/feed/")
        self.assertNotContains(response, "Dan")

    def test_event_while_internal_stays_hidden_from_clients(self):
        self.act(lambda: share(self.secret, [self.bob], actor=self.ada, notify=True))
        ops.set_visibility(self.internal, visible=True, actor=self.ada)
        self.client.force_login(self.cleo)
        self.assertNotContains(self.client.get("/feed/"), "Budget")


class ModalTest(SubscribersTestCase):
    def options(self, response):
        return {p.pk for p in response.context["form"].fields["people"].queryset}

    def test_modal_and_page(self):
        subscribe(self.cleo, self.todo, added_by=self.ada)
        self.client.force_login(self.ada)
        response = self.client.get(self.url(self.todo), headers=MODAL)
        assert_modal(self, response, title="Subscribers")
        self.assertContains(response, "data-people-picker")
        self.assertContains(response, "Tell them now")
        self.assertContains(response, "added by Ada")
        self.assertContains(response, f'href="/people/{self.cleo.pk}/"')
        # Offered: who sees it and isn't subscribed; not oneself
        self.assertEqual(
            self.options(response), {self.bob.pk, self.dan.pk, self.eli.pk, self.pia.pk}
        )
        assert_page(self, self.client.get(self.url(self.todo)), title="Subscribers")

    def test_saving_quietly(self):
        self.client.force_login(self.ada)
        response = self.client.post(
            self.url(self.todo), {"people": [self.bob.pk, self.dan.pk]}, headers=MODAL
        )
        self.assertEqual(response.headers["HX-Redirect"], self.todo.get_absolute_url())
        subscriptions = Subscription.objects.filter(item=self.todo, added_by=self.ada)
        self.assertEqual({s.user for s in subscriptions}, {self.bob, self.dan})
        self.assertFalse(Event.objects.filter(action=Action.SHARED))

    def test_saving_with_tell_them_now(self):
        self.client.force_login(self.ada)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                self.url(self.todo),
                {"people": [self.bob.pk], "notify": "on", "note": "Have a look"},
            )
        event = Event.objects.get(action=Action.SHARED)
        self.assertEqual(event.data["people"], [self.bob.pk])
        self.assertEqual(event.data["note"], "Have a look")
        self.assertEqual(Notification.objects.get().user, self.bob)

    def test_errors_render_the_form_again(self):
        self.client.force_login(self.ada)
        response = self.client.post(self.url(self.todo), {"note": "x"}, headers=MODAL)
        self.assertContains(response, "Pick at least one person.")
        response = self.client.post(
            self.url(self.todo),
            {"people": [self.bob.pk], "notify": "on", "note": "x" * 201},
            headers=MODAL,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "at most 200")
        self.assertFalse(Subscription.objects.filter(user=self.bob, item=self.todo))

    def test_nobody_who_cannot_see_it(self):
        self.client.force_login(self.ada)
        response = self.client.post(
            self.url(self.secret), {"people": [self.cleo.pk]}, headers=MODAL
        )
        self.assertContains(response, "Select a valid choice")
        self.assertFalse(Subscription.objects.filter(user=self.cleo, item=self.secret))

    def test_partner_offered_the_project_s_people(self):
        outsider = person("Olga")  # staff, in another limited project only
        project("Elsewhere", members=[outsider], all_access=False)
        self.project.is_all_access = False
        self.project.save()
        self.project.memberships.create(user=self.dan)
        self.client.force_login(self.pia)
        response = self.client.get(self.url(self.todo), headers=MODAL)
        self.assertIn(self.dan.pk, self.options(response))
        self.assertNotIn(outsider.pk, self.options(response))
        response = self.client.post(
            self.url(self.todo), {"people": [outsider.pk]}, headers=MODAL
        )
        self.assertContains(response, "Select a valid choice")

    def test_partner_offered_staff_with_access(self):
        self.client.force_login(self.pia)
        response = self.client.get(self.url(self.todo), headers=MODAL)
        self.assertIn(self.dan.pk, self.options(response))

    def test_client_offered_only_who_they_may_know(self):
        for viewer in [self.cleo]:
            with self.subTest(viewer=viewer):
                self.client.force_login(viewer)
                response = self.client.get(self.url(self.todo), headers=MODAL)
                assert_modal(self, response, title="Subscribers")
                self.assertNotIn(self.dan.pk, self.options(response))
                self.assertIn(self.bob.pk, self.options(response))
                self.assertNotContains(response, "Dan")
                response = self.client.post(
                    self.url(self.todo), {"people": [self.dan.pk]}, headers=MODAL
                )
                self.assertContains(response, "Select a valid choice")

    def test_client_adds_people_they_know(self):
        self.client.force_login(self.cleo)
        self.client.post(self.url(self.todo), {"people": [self.bob.pk]})
        self.assertEqual(
            Subscription.objects.get(user=self.bob, item=self.todo).added_by, self.cleo
        )

    def test_client_does_not_learn_of_subscribers_they_do_not_know(self):
        subscribe(self.dan, self.todo, added_by=self.ada)
        subscribe(self.bob, self.todo, added_by=self.dan)
        self.client.force_login(self.cleo)
        response = self.client.get(self.url(self.todo), headers=MODAL)
        self.assertNotContains(response, "Dan")
        self.assertContains(response, "Bob")
        self.assertNotContains(response, "added by")

    def test_internal_items_are_404_for_clients(self):
        self.client.force_login(self.cleo)
        self.assertEqual(self.client.get(self.url(self.secret)).status_code, 404)
        response = self.client.post(self.url(self.secret), {"people": [self.bob.pk]})
        self.assertEqual(response.status_code, 404)

    def test_palette_offers_it(self):
        self.client.force_login(self.ada)
        for item in [self.todo, self.shared]:
            response = self.client.get(item.get_absolute_url())
            actions = {a["label"]: a for a in palette_data(response)["actions"]}
            self.assertEqual(actions["Subscribers…"]["type"], "modal")
            self.assertEqual(actions["Subscribers…"]["url"], self.url(item))

    def test_the_box_links_it(self):
        self.client.force_login(self.ada)
        response = self.client.get(self.todo.get_absolute_url())
        self.assertContains(response, f'href="{self.url(self.todo)}"')
        self.assertContains(response, "Manage…")

    def test_every_kind(self):
        self.client.force_login(self.ada)
        for item in [self.todo, self.shared, self.internal]:
            with self.subTest(item=item):
                response = self.client.get(self.url(item), headers=MODAL)
                assert_modal(self, response, title="Subscribers")


class APITest(SubscribersTestCase):
    def headers(self, user, access="write"):
        _token, secret = APIToken.create_for(user=user, title="T", access=access)
        return {"authorization": f"Bearer {secret}"}

    def path(self, item):
        return f"/api/v1/items/{item.pk}/subscribers/"

    def post(self, item, user, data, access="write"):
        return self.client.post(
            self.path(item),
            data,
            content_type="application/json",
            headers=self.headers(user, access),
        )

    def test_list(self):
        subscribe(self.bob, self.todo, added_by=self.ada)
        response = self.client.get(
            self.path(self.todo), headers=self.headers(self.ada, "read")
        )
        rows = {
            row["person"]["short_name"]: row for row in response.json()["subscribers"]
        }
        self.assertEqual(set(rows), {"Ada", "Bob"})
        self.assertTrue(response.json()["visible_to_clients"])
        self.assertEqual(rows["Bob"]["added_by"]["short_name"], "Ada")
        self.assertIsNone(rows["Ada"]["added_by"])

    def test_add_quietly_and_tell_them_now(self):
        response = self.post(self.todo, self.ada, {"people": [self.bob.pk]})
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "Bob", {r["person"]["short_name"] for r in response.json()["subscribers"]}
        )
        self.assertFalse(Event.objects.filter(action=Action.SHARED))
        with self.captureOnCommitCallbacks(execute=True):
            response = self.post(
                self.todo,
                self.ada,
                {"people": [self.cleo.pk], "notify": True, "note": "Soon"},
            )
        self.assertEqual(response.status_code, 200)
        event = Event.objects.get(action=Action.SHARED)
        self.assertEqual(event.data["note"], "Soon")
        self.assertEqual(Notification.objects.get().user, self.cleo)

    def test_errors(self):
        self.assertEqual(
            self.post(self.todo, self.ada, {"people": []}).status_code, 400
        )
        # Not visible to them, unknown to the client, the note too long
        response = self.post(self.secret, self.ada, {"people": [self.cleo.pk]})
        self.assertEqual(response.status_code, 400)
        response = self.post(self.todo, self.cleo, {"people": [self.dan.pk]})
        self.assertEqual(response.status_code, 400)
        response = self.post(
            self.todo, self.ada, {"people": [self.bob.pk], "note": "x" * 201}
        )
        self.assertEqual(response.status_code, 422)
        self.assertFalse(
            Subscription.objects.filter(
                user=self.bob, item=self.todo, added_by=self.ada
            )
        )

    def test_read_only_tokens_cannot_add(self):
        response = self.post(self.todo, self.ada, {"people": [self.bob.pk]}, "read")
        self.assertEqual(response.status_code, 403)

    def test_internal_items_are_404_for_clients(self):
        headers = self.headers(self.cleo)
        response = self.client.get(self.path(self.secret), headers=headers)
        self.assertEqual(response.status_code, 404)
        response = self.post(self.secret, self.cleo, {"people": [self.ada.pk]})
        self.assertEqual(response.status_code, 404)

    def test_clients_see_only_the_people_they_may_know(self):
        subscribe(self.dan, self.todo, added_by=self.ada)
        response = self.client.get(
            self.path(self.todo), headers=self.headers(self.cleo)
        )
        self.assertEqual(
            {r["person"]["short_name"] for r in response.json()["subscribers"]}, {"Ada"}
        )
