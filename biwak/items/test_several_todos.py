"""Moving and dating several to-dos at once (specs/handover.md): the
selection's "Move…" and "Due date…", all or nothing; the operation, the
modals, the API"""

import datetime as dt

from django.test import TestCase
from django.urls import reverse

from biwak.activity.models import Action, Event
from biwak.items import operations as ops
from biwak.items.models import Group
from biwak.items.test_assign_several import Selection
from biwak.test_utils import assert_modal, assert_modal_redirect, person, project


D = dt.date


def url(name, *items, next=""):
    query = "&".join(f"items={item.pk}" for item in items)
    return f"{reverse(name)}?{query}{next}"


def dates(item):
    item.todo.refresh_from_db()
    return (item.todo.starts_on, item.todo.due_on)


class DateTodosTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        website = project("Website", members=[self.ada])
        launch = ops.create_list(project=website, title="Launch", creator=self.ada)
        self.copy = ops.create_todo(
            todolist=launch,
            title="Copy",
            creator=self.ada,
            due_on=D(2026, 12, 10),
            starts_on=D(2026, 12, 7),
        )
        self.photos = ops.create_todo(
            todolist=launch, title="Photos", creator=self.ada, due_on=D(2026, 12, 4)
        )
        self.budget = ops.create_todo(todolist=launch, title="Budget", creator=self.ada)
        self.all = [self.copy, self.photos, self.budget]
        Event.objects.all().delete()

    def test_set_a_date(self):
        ops.date_todos(
            self.all, actor=self.ada, dates=ops.Dates.KEEP, due_on=D(2026, 12, 20)
        )
        self.assertEqual(dates(self.copy), (D(2026, 12, 7), D(2026, 12, 20)))
        self.assertEqual(dates(self.photos), (None, D(2026, 12, 20)))
        self.assertEqual(dates(self.budget), (None, D(2026, 12, 20)))
        self.assertEqual(Event.objects.filter(action=Action.EDITED).count(), 3)

    def test_a_start_after_the_date_changes_nothing(self):
        with self.assertRaisesMessage(
            ops.InvalidDates, "The start date can't be after the due date."
        ):
            ops.date_todos(
                [self.photos, self.copy],
                actor=self.ada,
                dates=ops.Dates.KEEP,
                due_on=D(2026, 12, 5),
            )
        self.assertEqual(dates(self.photos), (None, D(2026, 12, 4)))

    def test_move_by(self):
        self.copy.todo.recurrence = "FREQ=WEEKLY"
        self.copy.todo.recurrence_ends_on = D(2027, 1, 31)
        self.copy.todo.save()
        ops.date_todos(self.all, actor=self.ada, dates=ops.Dates.SHIFT, days=-3)
        self.assertEqual(dates(self.copy), (D(2026, 12, 4), D(2026, 12, 7)))
        self.assertEqual(self.copy.todo.recurrence_ends_on, D(2027, 1, 28))
        self.assertEqual(dates(self.photos), (None, D(2026, 12, 1)))
        # Without a due date, nothing to move
        self.assertEqual(dates(self.budget), (None, None))
        self.assertEqual(Event.objects.filter(action=Action.EDITED).count(), 2)

    def test_remove(self):
        ops.date_todos(self.all, actor=self.ada, dates=ops.Dates.REMOVE)
        for item in self.all:
            self.assertEqual(dates(item), (None, None))
        self.assertEqual(Event.objects.filter(action=Action.EDITED).count(), 2)


class DatesPageTest(Selection):
    def test_the_bar_has_the_buttons(self):
        self.client.force_login(self.ada)
        response = self.client.get(self.copy.parent.get_absolute_url())
        self.assertContains(response, reverse("todos_move_selected"))
        self.assertContains(response, reverse("todos_dates"))

    def test_modal_and_page(self):
        self.client.force_login(self.ada)
        target = url("todos_dates", self.copy, self.photos)
        response = self.client.get(target, headers={"HX-Modal": "true"})
        assert_modal(self, response, title="Due date…")
        self.assertContains(response, "2 to-dos")
        self.assertContains(response, "Set a date")
        self.assertContains(response, "Move by")
        self.assertEqual(self.client.get(target).status_code, 200)

    def test_setting_moving_removing(self):
        self.client.force_login(self.ada)
        target = url("todos_dates", self.copy, self.photos, next="&next=/todos/")
        response = self.client.post(
            target,
            {"dates": "keep", "due_on": "2026-12-20"},
            headers={"HX-Modal": "true"},
        )
        assert_modal_redirect(self, response, "/todos/")
        self.assertEqual(dates(self.copy), (None, D(2026, 12, 20)))
        self.client.post(target, {"dates": "shift", "days": "2"})
        self.assertEqual(dates(self.photos), (None, D(2026, 12, 22)))
        self.client.post(target, {"dates": "remove"})
        self.assertEqual(dates(self.copy), (None, None))

    def test_errors(self):
        self.client.force_login(self.ada)
        target = url("todos_dates", self.copy)
        response = self.client.post(target, {"dates": "keep"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This field is required.")
        response = self.client.post(target, {"dates": "shift", "days": "0"})
        self.assertContains(response, "By how many days?")
        ops.update_todo(
            self.copy,
            actor=self.ada,
            due_on=D(2026, 12, 10),
            starts_on=D(2026, 12, 7),
        )
        response = self.client.post(target, {"dates": "keep", "due_on": "2026-12-01"})
        self.assertContains(response, "The start date can&#x27;t be after")
        self.assertEqual(dates(self.copy), (D(2026, 12, 7), D(2026, 12, 10)))

    def test_a_todo_gone_changes_nothing(self):
        self.client.force_login(self.ada)
        target = url("todos_dates", self.copy, self.photos)
        ops.trash(self.photos, actor=self.bob)
        response = self.client.post(target, {"dates": "keep", "due_on": "2026-12-20"})
        self.assertContains(response, "Nothing was changed.")
        self.assertEqual(dates(self.copy), (None, None))

    def test_clients(self):
        """Clients date to-dos they see (their fields are shared work,
        specs/access.md); internal ones aren't there for them"""
        self.client.force_login(self.cleo)
        response = self.client.post(
            url("todos_dates", self.copy), {"dates": "keep", "due_on": "2026-12-20"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(dates(self.copy), (None, D(2026, 12, 20)))
        self.assertEqual(
            self.client.get(url("todos_dates", self.budget)).status_code, 404
        )
        response = self.client.get(url("todos_dates", self.copy, self.budget))
        self.assertContains(response, "1 of the selected to-dos")


class MovePageTest(Selection):
    def setUp(self):
        super().setUp()
        self.launch = self.copy.parent
        self.internal = self.budget.parent
        self.soon = Group.objects.create(
            todolist=self.internal.todolist, title="Soon", position=1
        )

    def test_modal_and_page(self):
        self.client.force_login(self.ada)
        target = url("todos_move_selected", self.copy, self.photos)
        response = self.client.get(target, headers={"HX-Modal": "true"})
        assert_modal(self, response, title="Move…")
        self.assertContains(response, "2 to-dos")
        self.assertContains(response, f'value="{self.internal.pk}:{self.soon.pk}"')
        self.assertEqual(self.client.get(target).status_code, 200)

    def test_moving(self):
        self.client.force_login(self.ada)
        response = self.client.post(
            url("todos_move_selected", self.photos, self.copy, next="&next=/todos/"),
            {"target": f"{self.internal.pk}:{self.soon.pk}", "index": "end"},
            headers={"HX-Modal": "true"},
        )
        assert_modal_redirect(self, response, "/todos/")
        for item in [self.copy, self.photos]:
            item.refresh_from_db()
            self.assertEqual(item.parent_id, self.internal.pk)
            self.assertEqual(item.todo.group, self.soon)
            # Internal now
            self.assertFalse(item.is_client_visible)
        # Next to each other in the order selected
        self.assertLess(self.photos.position, self.copy.position)
        self.assertEqual(Event.objects.filter(action=Action.MOVED).count(), 2)

    def test_several_projects(self):
        shop = project("Shop", members=[self.ada])
        orders = ops.create_list(project=shop, title="Orders", creator=self.ada)
        invoice = ops.create_todo(todolist=orders, title="Invoice", creator=self.ada)
        self.client.force_login(self.ada)
        target = url("todos_move_selected", self.copy, invoice)
        self.assertContains(self.client.get(target), "in several projects")
        response = self.client.post(target, {"target": str(orders.pk), "index": "end"})
        self.assertContains(response, "in several projects")
        self.copy.refresh_from_db()
        self.assertEqual(self.copy.parent_id, self.launch.pk)

    def test_a_todo_gone_changes_nothing(self):
        self.client.force_login(self.ada)
        target = url("todos_move_selected", self.copy, self.photos)
        ops.trash(self.photos, actor=self.bob)
        response = self.client.post(
            target, {"target": str(self.internal.pk), "index": "end"}
        )
        self.assertContains(response, "Nothing was changed.")
        self.copy.refresh_from_db()
        self.assertEqual(self.copy.parent_id, self.launch.pk)

    def test_clients(self):
        """Clients move to-dos they see to lists they see, as a to-do's
        "Move to…"; the internal list isn't offered"""
        other = ops.create_list(
            project=self.website, title="Later", creator=self.ada, visible=True
        )
        self.client.force_login(self.cleo)
        target = url("todos_move_selected", self.copy)
        response = self.client.get(target)
        self.assertContains(response, f'value="{other.pk}"')
        self.assertNotContains(response, f'value="{self.internal.pk}"')
        response = self.client.post(target, {"target": str(self.internal.pk)})
        self.assertEqual(response.status_code, 200)
        response = self.client.post(target, {"target": str(other.pk), "index": "0"})
        self.assertEqual(response.status_code, 302)
        self.copy.refresh_from_db()
        self.assertEqual(self.copy.parent_id, other.pk)
        self.assertEqual(
            self.client.get(url("todos_move_selected", self.budget)).status_code, 404
        )


class DatesAPITest(Selection):
    def post(self, data):
        return self.client.post(
            "/api/v1/todos/dates/", data, content_type="application/json"
        )

    def test_api(self):
        self.client.force_login(self.ada)
        ids = [self.copy.pk, self.budget.pk]
        response = self.post({"ids": ids, "dates": "set", "due_on": "2026-12-20"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [(t["id"], t["due_on"]) for t in response.json()],
            [(self.copy.pk, "2026-12-20"), (self.budget.pk, "2026-12-20")],
        )
        response = self.post({"ids": ids, "dates": "shift", "days": -1})
        self.assertEqual(response.json()[0]["due_on"], "2026-12-19")
        response = self.post({"ids": ids, "dates": "remove"})
        self.assertIsNone(response.json()[1]["due_on"])

    def test_api_all_or_nothing(self):
        self.client.force_login(self.ada)
        for data in [
            {"ids": [], "dates": "remove"},
            {"ids": [self.copy.pk], "dates": "set"},
            {"ids": [self.copy.pk], "dates": "shift"},
        ]:
            with self.subTest(data=data):
                self.assertEqual(self.post(data).status_code, 400)
        response = self.post({"ids": [self.copy.pk], "dates": "keep"})
        self.assertEqual(response.status_code, 422)
        ops.update_todo(
            self.photos,
            actor=self.ada,
            due_on=D(2026, 12, 10),
            starts_on=D(2026, 12, 7),
        )
        response = self.post({
            "ids": [self.copy.pk, self.photos.pk],
            "dates": "set",
            "due_on": "2026-12-01",
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("can't be after", response.json()["detail"])
        self.assertEqual(dates(self.copy), (None, None))

    def test_api_clients(self):
        self.client.force_login(self.cleo)
        response = self.post({
            "ids": [self.copy.pk, self.budget.pk],
            "dates": "remove",
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("1 of the selected to-dos", response.json()["detail"])
        response = self.post({"ids": [self.copy.pk], "dates": "remove"})
        self.assertEqual(response.status_code, 200)
