"""Moving and dating several to-dos at once (specs/handover.md): the
selection's "Move…" and "Due date…", all or nothing; the operation, the
modals, the API"""

import datetime as dt

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from biwak.activity import lantern
from biwak.activity.mails import send_mails
from biwak.activity.models import Action, Event, Notification
from biwak.activity.operations import subscribe
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


@override_settings(
    BASE_URL="https://biwak.example.org", DEFAULT_FROM_EMAIL="biwak@example.org"
)
class DatedOnceTest(TestCase):
    """Subscribers of the to-dos of one "Due date…" are told once
    (decided 2026-11-22)"""

    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        website = project("Website", members=[self.ada, self.bob])
        shop = project("Shop", members=[self.ada, self.bob])
        self.todos = [
            ops.create_todo(
                todolist=ops.create_list(project=p, title="Plan", creator=self.ada),
                title=title,
                creator=self.ada,
            )
            for p, title in [(website, "Copy"), (website, "Photos"), (shop, "Invoice")]
        ]
        for item in self.todos:
            subscribe(self.bob, item)
        Notification.objects.all().delete()
        mail.outbox = []

    def date(self, items):
        with self.captureOnCommitCallbacks(execute=True):
            ops.date_todos(
                items, actor=self.ada, dates=ops.Dates.KEEP, due_on=D(2026, 12, 20)
            )

    def test_one_lantern_entry_and_one_mail(self):
        self.date(self.todos)
        events = Event.objects.filter(action=Action.EDITED)
        self.assertEqual(len({e.data["batch"] for e in events}), 1)
        self.assertEqual(lantern.unread_counts(self.bob), (3, 1))
        _marks, [(batch, _entries)], _read, _more = lantern.menu(self.bob)
        self.assertEqual(batch.line, "Ada Example changed the dates of 3 to-dos.")
        self.assertEqual({f.pk for f in batch.files}, {t.pk for t in self.todos})
        with self.captureOnCommitCallbacks(execute=True):
            send_mails(now=timezone.now() + dt.timedelta(minutes=11))
        to_bob = [m for m in mail.outbox if m.to == [self.bob.email]]
        self.assertEqual(len(to_bob), 1)
        self.assertEqual(
            to_bob[0].subject, "[Biwak] Ada Example changed the dates of 3 to-dos"
        )
        for item in self.todos:
            self.assertIn(item.get_absolute_url(), to_bob[0].body)

    def test_one_to_do_is_no_batch(self):
        self.date(self.todos[:1])
        self.assertNotIn("batch", Event.objects.get(action=Action.EDITED).data)
        self.assertEqual(lantern.unread_counts(self.bob), (1, 1))


class MoveAcrossTest(TestCase):
    """Moving to-dos to a list of another project (decided 2026-11-22)"""

    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.pitch = project(
            "Pitch", members=[self.ada, self.bob, self.cleo], all_access=False
        )
        self.website = project("Website", members=[self.ada], all_access=False)
        launch = ops.create_list(
            project=self.pitch, title="Launch", creator=self.ada, visible=True
        )
        self.plans = ops.create_list(
            project=self.website, title="Plans", creator=self.ada
        )
        self.tent = ops.create_todo(
            todolist=launch,
            title="Tent",
            creator=self.ada,
            assignees=[self.bob, self.cleo],
        )
        self.stove = ops.create_todo(todolist=launch, title="Stove", creator=self.ada)
        ops.add_comment(self.stove, author=self.cleo, content="Gas?")
        ops.complete(self.stove, actor=self.ada)
        self.here = ops.create_todo(todolist=self.plans, title="Here", creator=self.ada)
        Event.objects.all().delete()

    def move(self, items):
        with self.captureOnCommitCallbacks(execute=True):
            ops.move_todos_to(items, todolist=self.plans, actor=self.ada)

    def test_people_plan(self):
        added, dropped = ops.todos_move_people(
            [self.tent, self.stove, self.here], self.website, visible=False
        )
        self.assertEqual(list(added), [self.bob])
        self.assertEqual(list(dropped), [self.cleo])

    def test_moving(self):
        self.move([self.tent, self.stove, self.here])
        for item in [self.tent, self.stove]:
            item.refresh_from_db()
            self.assertEqual(item.project, self.website)
            self.assertEqual(item.parent, self.plans)
            self.assertFalse(item.is_client_visible)
        # Completed ones too, with their comments and events
        self.assertTrue(self.stove.todo.is_completed)
        self.assertEqual(
            set(
                Event.objects.filter(item=self.stove).values_list("project", flat=True)
            ),
            {self.website.pk},
        )
        # Bob added, Cleo dropped
        self.assertTrue(self.website.is_member(self.bob))
        self.assertFalse(self.website.is_member(self.cleo))
        self.assertEqual(list(self.tent.todo.assignees.all()), [self.bob])
        self.assertFalse(self.stove.subscriptions.filter(user=self.cleo).exists())
        # An event each in the target, naming both projects, one batch
        moved = Event.objects.filter(action=Action.MOVED, item__isnull=False)
        self.assertEqual(moved.count(), 2)
        self.assertEqual(len({e.data["batch"] for e in moved}), 1)
        event = moved.get(item=self.tent)
        self.assertEqual(event.project, self.website)
        self.assertEqual(event.data["from_project_id"], self.pitch.pk)
        self.assertEqual(event.data["to_id"], self.plans.pk)
        # One line for all in the project they left, for its staff
        trace = Event.objects.get(action=Action.MOVED, item=None)
        self.assertEqual(trace.project, self.pitch)
        self.assertFalse(trace.is_client_visible)
        self.assertEqual(trace.data["todos"], 2)
        self.assertEqual(trace.data["to_id"], self.plans.pk)
        # Nobody told
        self.assertFalse(
            Notification.objects.filter(event__action=Action.MOVED).exists()
        )

    def test_the_trace_in_the_feed(self):
        self.move([self.tent, self.stove])
        self.client.force_login(self.ada)
        response = self.client.get(reverse("project_feed", args=[self.pitch.pk]))
        self.assertContains(response, "moved 2 to-dos to")
        self.assertContains(response, f'href="{self.plans.get_absolute_url()}"')
        self.assertContains(response, "in Website")
        # Bob can't open Website: no names
        self.website.memberships.filter(user=self.bob).delete()
        self.client.force_login(self.bob)
        response = self.client.get(reverse("project_feed", args=[self.pitch.pk]))
        self.assertContains(response, "moved 2 to-dos to another project")
        self.assertNotContains(response, "Plans")

    def test_archived_and_templates_are_refused(self):
        self.website.archived_at = timezone.now()
        self.website.save()
        with self.assertRaisesMessage(ValueError, "archived project"):
            self.move([self.tent])
        self.tent.refresh_from_db()
        self.assertEqual(self.tent.project, self.pitch)

    def test_within_a_project_as_before(self):
        other = ops.create_list(project=self.website, title="Other", creator=self.ada)
        ops.move_todos_to([self.here], todolist=other, actor=self.ada)
        self.here.refresh_from_db()
        self.assertEqual(self.here.parent, other)
        self.assertFalse(Event.objects.filter(item=None).exists())


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
        self.shop = project("Shop", members=[self.ada, self.cleo], all_access=False)
        self.orders = ops.create_list(
            project=self.shop, title="Orders", creator=self.ada, visible=True
        )

    def post(self, *items, data, next="", modal=False):
        return self.client.post(
            url("todos_move_selected", *items, next=next),
            data,
            headers={"HX-Modal": "true"} if modal else {},
        )

    def assertIn_(self, items, todolist):
        for item in items:
            item.refresh_from_db()
            self.assertEqual(item.parent_id, todolist.pk)

    def test_modal_and_page(self):
        self.client.force_login(self.ada)
        target = url("todos_move_selected", self.copy, self.photos)
        response = self.client.get(target, headers={"HX-Modal": "true"})
        assert_modal(self, response, title="Move…")
        self.assertContains(response, "2 to-dos")
        self.assertContains(response, f'value="{self.internal.pk}:{self.soon.pk}"')
        self.assertContains(response, 'value="new"')
        # The projects, another one showing its lists at once
        self.assertContains(response, f'<option value="{self.shop.pk}"')
        self.assertContains(response, 'hx-trigger="change"')
        response = self.client.get(target)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'hx-trigger="change"')

    def test_moving(self):
        self.client.force_login(self.ada)
        response = self.post(
            self.photos,
            self.copy,
            data={
                "project": self.website.pk,
                "shown": self.website.pk,
                "target": f"{self.internal.pk}:{self.soon.pk}",
                "index": "end",
            },
            next="&next=/todos/",
            modal=True,
        )
        assert_modal_redirect(self, response, "/todos/")
        self.assertIn_([self.copy, self.photos], self.internal)
        self.assertEqual(self.copy.todo.group, self.soon)
        # Internal now
        self.assertFalse(self.copy.is_client_visible)
        # Next to each other in the order selected
        self.assertLess(self.photos.position, self.copy.position)
        self.assertEqual(Event.objects.filter(action=Action.MOVED).count(), 2)

    def test_another_project_shows_its_lists_first(self):
        self.client.force_login(self.ada)
        response = self.post(
            self.copy,
            data={
                "project": self.shop.pk,
                "shown": self.website.pk,
                "target": str(self.internal.pk),
            },
        )
        self.assertContains(response, f'value="{self.orders.pk}"')
        self.assertNotContains(response, f'value="{self.internal.pk}"')
        self.assertIn_([self.copy], self.launch)

    def test_across_projects_asks_first(self):
        ops.assign(self.copy, [self.bob], actor=self.ada)
        self.client.force_login(self.ada)
        data = {
            "project": self.shop.pk,
            "shown": self.shop.pk,
            "target": str(self.orders.pk),
            "index": "end",
        }
        response = self.post(self.copy, self.photos, data=data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bob Example will be added to Shop.")
        self.assertIn_([self.copy], self.launch)
        response = self.post(
            self.copy,
            self.photos,
            data=data | {"confirmed": f"{self.shop.pk}:{self.orders.pk}"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn_([self.copy, self.photos], self.orders)
        self.assertEqual(self.copy.project, self.shop)
        self.assertTrue(self.shop.is_member(self.bob))
        trace = Event.objects.get(action=Action.MOVED, item=None)
        self.assertEqual(trace.project, self.website)

    def test_a_new_list(self):
        self.client.force_login(self.ada)
        response = self.post(
            self.copy,
            self.photos,
            data={
                "project": self.shop.pk,
                "shown": self.shop.pk,
                "target": "new",
                "index": "end",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.copy.refresh_from_db()
        new = self.copy.parent
        self.assertEqual((new.project, new.title), (self.shop, "Launch"))
        self.assertFalse(new.is_client_visible)
        self.assertIn_([self.photos], new)
        # From several lists: "Moved to-dos"
        self.post(
            self.copy,
            self.budget,
            data={
                "project": self.website.pk,
                "shown": self.website.pk,
                "target": "new",
                "index": "end",
            },
        )
        self.budget.refresh_from_db()
        self.assertEqual(self.budget.parent.title, "Moved to-dos")
        self.assertEqual(self.budget.project, self.website)

    def test_a_todo_gone_changes_nothing(self):
        self.client.force_login(self.ada)
        ops.trash(self.photos, actor=self.bob)
        response = self.post(
            self.copy,
            self.photos,
            data={"project": self.website.pk, "target": str(self.internal.pk)},
        )
        self.assertContains(response, "Nothing was changed.")
        self.assertIn_([self.copy], self.launch)

    def test_clients(self):
        """Clients move to-dos they see to lists they see within the
        project (decided 2026-11-22), as a to-do's "Move to…"; no new list,
        no other project"""
        other = ops.create_list(
            project=self.website, title="Later", creator=self.ada, visible=True
        )
        self.client.force_login(self.cleo)
        target = url("todos_move_selected", self.copy)
        response = self.client.get(target)
        self.assertContains(response, f'value="{other.pk}"')
        self.assertNotContains(response, f'value="{self.internal.pk}"')
        self.assertNotContains(response, 'value="new"')
        self.assertNotContains(response, f'value="{self.orders.pk}"')
        response = self.client.post(target, {"target": str(self.internal.pk)})
        self.assertEqual(response.status_code, 200)
        # Another project's list isn't a choice, the project is ignored
        response = self.client.post(
            target, {"project": self.shop.pk, "target": str(self.orders.pk)}
        )
        self.assertEqual(response.status_code, 200)
        response = self.client.post(target, {"target": str(other.pk), "index": "0"})
        self.assertEqual(response.status_code, 302)
        self.assertIn_([self.copy], other)
        self.assertEqual(
            self.client.get(url("todos_move_selected", self.budget)).status_code, 404
        )
        # To-dos of several projects don't move together for clients
        invoice = ops.create_todo(
            todolist=self.orders, title="Invoice", creator=self.ada
        )
        response = self.client.get(url("todos_move_selected", self.copy, invoice))
        self.assertContains(response, "in several projects")


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
