"""Assigning several to-dos at once (specs/handover.md): one operation per
to-do, all or nothing, a new assignee told once per "Assign…"; the modal,
the API"""

import datetime as dt

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from biwak.activity import lantern
from biwak.activity.mails import send_mails
from biwak.activity.models import Action, Event, Notification
from biwak.items import operations as ops
from biwak.test_utils import assert_modal, assert_modal_redirect, person, project


@override_settings(
    BASE_URL="https://biwak.example.org", DEFAULT_FROM_EMAIL="biwak@example.org"
)
class AssignTodosTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.dan = person("Dan")
        self.cleo = person("Cleo", client=True)
        self.website = project("Website", members=[self.ada, self.bob, self.cleo])
        self.shop = project("Shop", members=[self.ada, self.bob])
        self.launch = ops.create_list(
            project=self.website, title="Launch", creator=self.ada, visible=True
        )
        self.internal = ops.create_list(
            project=self.website, title="Internal", creator=self.ada
        )
        self.orders = ops.create_list(
            project=self.shop, title="Orders", creator=self.ada
        )
        self.copy = ops.create_todo(
            todolist=self.launch, title="Copy", creator=self.ada, assignees=[self.dan]
        )
        self.photos = ops.create_todo(
            todolist=self.launch, title="Photos", creator=self.ada
        )
        self.budget = ops.create_todo(
            todolist=self.internal, title="Budget", creator=self.ada
        )
        self.invoice = ops.create_todo(
            todolist=self.orders, title="Invoice", creator=self.ada
        )
        Notification.objects.all().delete()
        Event.objects.all().delete()
        mail.outbox = []

    def assignees(self, item):
        return set(item.todo.assignees.all())

    def assign(self, items, users, **kwargs):
        with self.captureOnCommitCallbacks(execute=True):
            return ops.assign_todos(items, users, actor=self.ada, **kwargs)

    def send(self):
        with self.captureOnCommitCallbacks(execute=True):
            return send_mails(now=timezone.now() + dt.timedelta(minutes=11))

    # The operation -------------------------------------------------------

    def test_adds_across_projects_an_event_each(self):
        done = self.assign([self.copy, self.photos, self.invoice], [self.bob])
        self.assertEqual(done[self.copy], [self.bob])
        self.assertEqual(self.assignees(self.copy), {self.dan, self.bob})
        self.assertEqual(self.assignees(self.invoice), {self.bob})
        events = Event.objects.filter(action=Action.ASSIGNED)
        self.assertEqual(events.count(), 3)
        self.assertEqual(len({e.data["batch"] for e in events}), 1)

    def test_replace(self):
        self.assign([self.copy, self.photos], [self.bob], replace=True)
        self.assertEqual(self.assignees(self.copy), {self.bob})
        unassigned = Event.objects.get(action=Action.UNASSIGNED)
        self.assertEqual(unassigned.data["assignees"], [self.dan.pk])
        # Those taken out aren't told (as subscribers they hear of Bob, as
        # with the to-do's form)
        self.assertFalse(
            Notification.objects.filter(
                user=self.dan, event__action=Action.UNASSIGNED
            ).exists()
        )

    def test_one_to_do_is_no_batch(self):
        self.assign([self.photos], [self.bob])
        event = Event.objects.get(action=Action.ASSIGNED, item=self.photos)
        self.assertNotIn("batch", event.data)

    def test_all_or_nothing(self):
        # Cleo can't be assigned to an internal to-do, nor in the shop
        with self.assertRaisesMessage(
            ops.AssignRefused, "Cleo Example can't be assigned to 2 of the to-dos."
        ):
            self.assign([self.photos, self.budget, self.invoice], [self.bob, self.cleo])
        self.assertEqual(self.assignees(self.photos), set())
        self.assertFalse(Event.objects.filter(action=Action.ASSIGNED).exists())

    def test_assignable_to_all(self):
        self.assertIn(self.cleo, ops.assignable_to_all([self.photos], self.ada))
        both = ops.assignable_to_all([self.photos, self.budget], self.ada)
        self.assertNotIn(self.cleo, both)
        self.assertIn(self.bob, both)
        # Clients only members
        self.assertEqual(
            set(ops.assignable_to_all([self.photos], self.cleo)),
            {self.ada, self.bob, self.cleo, self.dan},
        )

    # Told once ----------------------------------------------------------

    def test_one_lantern_entry_and_one_mail(self):
        todos = [self.copy, self.photos, self.invoice]
        self.assign(todos, [self.bob])
        self.assertEqual(lantern.unread_counts(self.bob), (3, 1))
        _marks, [(batch, _entries)], _read, _more = lantern.menu(self.bob)
        self.assertTrue(batch.is_batch)
        self.assertEqual(batch.line, "Ada Example assigned you 3 to-dos.")
        self.assertIsNone(batch.project)
        self.assertEqual({f.pk for f in batch.files}, {t.pk for t in todos})
        # Dan, assigned to one already, hears of it as a subscriber
        self.assertEqual(lantern.unread_counts(self.dan), (1, 1))

        self.client.force_login(self.bob)
        response = self.client.get(reverse("lantern_menu"))
        self.assertContains(response, "Ada Example assigned you 3 to-dos.")
        for item in todos:
            self.assertContains(response, item.get_absolute_url())
        # Read with its button, all of them
        self.client.post(reverse("lantern_read"), {"item": [t.pk for t in todos]})
        self.assertEqual(lantern.unread_count(self.bob), 0)

        Notification.objects.update(read_at=None)
        self.send()
        to_bob = [m for m in mail.outbox if m.to == [self.bob.email]]
        self.assertEqual(len(to_bob), 1)
        self.assertEqual(to_bob[0].subject, "[Biwak] Ada Example assigned you 3 to-dos")
        for item in todos:
            self.assertIn(item.get_absolute_url(), to_bob[0].body)

    def test_two_assigns_far_apart_are_two_mails(self):
        self.assign([self.copy, self.photos], [self.bob])
        Notification.objects.update(
            created_at=timezone.now() - dt.timedelta(minutes=11)
        )
        self.assign([self.invoice, self.budget], [self.bob])
        self.assertEqual(lantern.unread_count(self.bob), 2)
        self.send()
        self.assertEqual(len([m for m in mail.outbox if m.to == [self.bob.email]]), 2)

    def test_uploads_stay_apart(self):
        """An upload batch's key and an assignment's never mix"""
        self.assign([self.copy, self.photos], [self.bob])
        notification = Notification.objects.filter(user=self.bob).first()
        self.assertEqual(lantern.batch_key(notification), ("assigned", self.ada.pk))


class Selection(TestCase):
    """Two visible to-dos and an internal one; no tests of its own"""

    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.website = project("Website", members=[self.ada, self.bob, self.cleo])
        launch = ops.create_list(
            project=self.website, title="Launch", creator=self.ada, visible=True
        )
        internal = ops.create_list(
            project=self.website, title="Internal", creator=self.ada
        )
        self.copy = ops.create_todo(todolist=launch, title="Copy", creator=self.ada)
        self.photos = ops.create_todo(todolist=launch, title="Photos", creator=self.ada)
        self.budget = ops.create_todo(
            todolist=internal, title="Budget", creator=self.ada
        )


class AssignPageTest(Selection):
    def url(self, *items, next=""):
        query = "&".join(f"items={item.pk}" for item in items)
        return f"{reverse('todos_assign')}?{query}{next}"

    def test_the_lists_and_the_todos_page_have_the_bar(self):
        self.client.force_login(self.ada)
        for url in [self.copy.parent.get_absolute_url(), "/todos/?assignee=anybody"]:
            response = self.client.get(url)
            self.assertContains(response, "data-row-selection-bar")
            self.assertContains(response, f'data-select-row="{self.copy.pk}"')

    def test_modal_and_page(self):
        self.client.force_login(self.ada)
        url = self.url(self.copy, self.photos, self.budget)
        response = self.client.get(url, headers={"HX-Modal": "true"})
        assert_modal(self, response, title="Assign…")
        self.assertContains(response, "3 to-dos")
        self.assertContains(response, "Instead of the current assignees")
        # Only who can be assigned to every one: not Cleo (internal)
        self.assertContains(response, f'value="{self.bob.pk}"')
        self.assertNotContains(response, f'value="{self.cleo.pk}"')
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_assigning(self):
        self.client.force_login(self.ada)
        response = self.client.post(
            self.url(self.copy, self.photos, next="&next=/todos/?assignee=anybody"),
            {"people": [self.bob.pk]},
            headers={"HX-Modal": "true"},
        )
        assert_modal_redirect(self, response, "/todos/?assignee=anybody")
        self.assertEqual(set(self.copy.todo.assignees.all()), {self.bob})
        self.assertEqual(set(self.photos.todo.assignees.all()), {self.bob})

    def test_replace(self):
        ops.assign(self.copy, [self.ada], actor=self.ada)
        self.client.force_login(self.ada)
        self.client.post(
            self.url(self.copy, self.photos), {"people": [self.bob.pk], "replace": "on"}
        )
        self.assertEqual(set(self.copy.todo.assignees.all()), {self.bob})

    def test_a_todo_gone_changes_nothing(self):
        self.client.force_login(self.ada)
        url = self.url(self.copy, self.photos)
        ops.trash(self.photos, actor=self.bob)
        response = self.client.get(url)
        self.assertContains(response, "1 of the selected to-dos can&#x27;t be changed")
        response = self.client.post(url, {"people": [self.bob.pk]})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nothing was changed.")
        self.assertEqual(set(self.copy.todo.assignees.all()), set())

    def test_clients(self):
        """Clients assign to-dos they see (their fields are shared work,
        specs/access.md), members only; internal ones aren't there for them"""
        self.client.force_login(self.cleo)
        response = self.client.get(self.copy.parent.get_absolute_url())
        self.assertContains(response, "data-row-selection-bar")
        response = self.client.post(
            self.url(self.copy, self.photos), {"people": [self.cleo.pk]}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(set(self.copy.todo.assignees.all()), {self.cleo})
        response = self.client.get(self.url(self.budget))
        self.assertEqual(response.status_code, 404)
        response = self.client.get(self.url(self.copy, self.budget))
        self.assertContains(response, "1 of the selected to-dos")

    def test_bad_ids(self):
        self.client.force_login(self.ada)
        self.assertEqual(self.client.get(reverse("todos_assign")).status_code, 404)
        self.assertEqual(
            self.client.get(f"{reverse('todos_assign')}?items=x").status_code, 404
        )
        # Not a to-do
        url = f"{reverse('todos_assign')}?items={self.copy.parent.pk}"
        self.assertEqual(self.client.get(url).status_code, 404)


class AssignAPITest(Selection):
    def post(self, data):
        return self.client.post(
            "/api/v1/todos/assign/", data, content_type="application/json"
        )

    def test_api(self):
        self.client.force_login(self.ada)
        response = self.post({
            "ids": [self.copy.pk, self.budget.pk],
            "people": [self.bob.pk],
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [(t["id"], [a["id"] for a in t["assignees"]]) for t in response.json()],
            [(self.copy.pk, [self.bob.pk]), (self.budget.pk, [self.bob.pk])],
        )
        response = self.post({
            "ids": [self.copy.pk],
            "people": [self.ada.pk],
            "replace": True,
        })
        self.assertEqual(
            [a["id"] for a in response.json()[0]["assignees"]], [self.ada.pk]
        )

    def test_api_all_or_nothing(self):
        self.client.force_login(self.ada)
        response = self.post({
            "ids": [self.copy.pk, self.budget.pk],
            "people": [self.cleo.pk],
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("every one of the to-dos", response.json()["detail"])
        self.assertEqual(set(self.copy.todo.assignees.all()), set())
        ops.trash(self.photos, actor=self.ada)
        response = self.post({
            "ids": [self.copy.pk, self.photos.pk],
            "people": [self.bob.pk],
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("1 of the selected to-dos", response.json()["detail"])
        self.assertEqual(self.post({"ids": [], "people": [1]}).status_code, 400)

    def test_api_clients(self):
        self.client.force_login(self.cleo)
        response = self.post({
            "ids": [self.copy.pk, self.budget.pk],
            "people": [self.cleo.pk],
        })
        self.assertEqual(response.status_code, 400)
        response = self.post({"ids": [self.copy.pk], "people": [self.cleo.pk]})
        self.assertEqual(response.status_code, 200)
