import datetime as dt
from zoneinfo import ZoneInfo

import time_machine
from django.test import TestCase

from biwak import schedules
from biwak.accounts.models import APIToken
from biwak.activity.models import Action, Event, Subscription
from biwak.items import operations as ops
from biwak.items.models import Item
from biwak.test_utils import person, project


ZURICH = ZoneInfo("Europe/Zurich")


def d(text):
    return dt.date.fromisoformat(text)


def at(text, tz=ZURICH):
    return time_machine.travel(
        dt.datetime.fromisoformat(text).replace(tzinfo=tz), tick=False
    )


class RecurrenceTestCase(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.bob, self.cleo])
        self.list = ops.create_list(
            project=self.project, title="Chores", creator=self.ada, visible=True
        )
        self.internal = ops.create_list(
            project=self.project, title="Internal", creator=self.ada
        )

    def todo(self, rule, due=None, **kwargs):
        return ops.create_todo(
            todolist=kwargs.pop("todolist", self.list),
            title="Water the plants",
            creator=self.ada,
            due_on=d(due) if due else None,
            recurrence=rule,
            **kwargs,
        )

    def following(self, item):
        return Item.objects.filter(todo__previous=item).first()


class OperationsTest(RecurrenceTestCase):
    def test_completing_creates_the_next_one(self):
        group = ops.create_group(todolist=self.list.todolist, title="Weekly")
        item = self.todo(
            "FREQ=WEEKLY;BYDAY=MO",
            "2026-11-16",
            group=group,
            notes="With *care*",
            assignees=[self.ada, self.cleo],
        )
        other = self.todo("", group=group)
        Event.objects.all().delete()
        with at("2026-11-20 10:00"):
            ops.complete(item, actor=self.bob)
        new = self.following(item)
        self.assertEqual(new.title, "Water the plants")
        self.assertEqual(new.parent, self.list)
        self.assertEqual(new.todo.group, group)
        self.assertEqual(new.todo.notes, "With *care*")
        self.assertEqual(new.todo.due_on, d("2026-11-23"))
        self.assertEqual(new.todo.recurrence, "FREQ=WEEKLY;BYDAY=MO")
        self.assertIsNone(new.todo.completed_at)
        self.assertEqual(new.todo.previous, item)
        self.assertEqual(new.creator, self.ada)
        self.assertTrue(new.is_client_visible)
        # At the end of its group, the old one stays completed
        self.assertGreater(new.position, other.position)
        self.assertEqual(Item.objects.filter(todo__recurrence__gt="").count(), 2)
        self.assertEqual(set(new.todo.assignees.all()), {self.ada, self.cleo})
        self.assertEqual(
            set(Subscription.objects.filter(item=new).values_list("user", flat=True)),
            set(Subscription.objects.filter(item=item).values_list("user", flat=True)),
        )
        self.assertEqual(
            list(
                Event.objects.filter(item=new, action=Action.CREATED).values_list(
                    "actor", flat=True
                )
            ),
            [self.bob.pk],
        )
        self.assertTrue(
            Event.objects.filter(item=item, action=Action.COMPLETED).exists()
        )

    def test_without_a_rule_nothing_happens(self):
        item = self.todo("")
        ops.complete(item, actor=self.ada)
        self.assertEqual(Item.objects.filter(kind="todo").count(), 1)

    def test_next_date_after_today_not_after_the_due_date(self):
        item = self.todo("FREQ=WEEKLY;BYDAY=MO", "2026-10-05")
        with at("2026-11-20 10:00"):
            ops.complete(item, actor=self.ada)
        self.assertEqual(self.following(item).todo.due_on, d("2026-11-23"))

    def test_completed_early_is_next_due_after_the_due_date(self):
        # Due Friday, done on Wednesday: next due the Friday after
        item = self.todo("FREQ=WEEKLY;BYDAY=FR", "2026-11-27")
        with at("2026-11-25 10:00"):
            ops.complete(item, actor=self.ada)
        self.assertEqual(self.following(item).todo.due_on, d("2026-12-04"))

    def test_without_due_date_counts_from_today(self):
        item = self.todo("FREQ=DAILY")
        with at("2026-11-20 10:00"):
            ops.complete(item, actor=self.ada)
        self.assertEqual(self.following(item).todo.due_on, d("2026-11-21"))

    def test_end_of_month(self):
        rule = schedules.from_preset("monthly", d("2026-01-31"))
        item = self.todo(rule, "2026-01-31")
        due = []
        for today in ["2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30"]:
            with at(f"{today} 12:00"):
                ops.complete(item, actor=self.ada)
            item = self.following(item)
            due.append(item.todo.due_on.isoformat())
        self.assertEqual(due, ["2026-02-28", "2026-03-31", "2026-04-30", "2026-05-31"])

    def test_leap_day(self):
        item = self.todo(schedules.from_preset("yearly", d("2028-02-29")), "2028-02-29")
        with at("2028-02-29 12:00"):
            ops.complete(item, actor=self.ada)
        self.assertEqual(self.following(item).todo.due_on, d("2029-02-28"))

    def test_last_weekday_of_the_month(self):
        item = self.todo("FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1", "2026-10-30")
        with at("2026-10-30 12:00"):
            ops.complete(item, actor=self.ada)
        self.assertEqual(self.following(item).todo.due_on, d("2026-11-30"))

    def test_time_zone_around_midnight(self):
        # 23:30 UTC is already the next day in Zurich, summer and winter
        for utc, due in [
            ("2026-07-10 22:30", "2026-07-12"),  # 11 July, 00:30 CEST
            ("2026-07-10 21:30", "2026-07-11"),  # 10 July, 23:30 CEST
            ("2026-12-10 23:30", "2026-12-12"),  # 11 December, 00:30 CET
            ("2026-12-10 22:30", "2026-12-11"),  # 10 December, 23:30 CET
            ("2026-03-28 23:30", "2026-03-30"),  # the night of the change
            ("2026-10-24 22:30", "2026-10-26"),  # the night of the change back
        ]:
            with self.subTest(utc=utc):
                item = self.todo("FREQ=DAILY")
                with at(utc, ZoneInfo("UTC")):
                    ops.complete(item, actor=self.ada)
                self.assertEqual(self.following(item).todo.due_on, d(due))

    def test_count(self):
        item = self.todo("FREQ=DAILY", "2026-11-20", recurrence_count=2)
        counts = []
        with at("2026-11-20 12:00"):
            while item:
                ops.complete(item, actor=self.ada)
                item = self.following(item)
                counts.append(item and item.todo.recurrence_count)
        self.assertEqual(counts, [1, 0, None])

    def test_end_date(self):
        item = self.todo("FREQ=DAILY", "2026-11-20", recurrence_ends_on=d("2026-11-21"))
        with at("2026-11-20 12:00"):
            ops.complete(item, actor=self.ada)
            second = self.following(item)
            self.assertEqual(second.todo.due_on, d("2026-11-21"))
            self.assertEqual(second.todo.recurrence_ends_on, d("2026-11-21"))
        with at("2026-11-21 12:00"):
            ops.complete(second, actor=self.ada)
        self.assertIsNone(self.following(second))

    def test_reopening_keeps_the_next_and_makes_no_second(self):
        item = self.todo("FREQ=DAILY", "2026-11-20")
        ops.complete(item, actor=self.ada)
        new = self.following(item)
        ops.reopen(item, actor=self.ada)
        self.assertTrue(Item.objects.filter(pk=new.pk).exists())
        ops.complete(item, actor=self.ada)
        self.assertEqual(Item.objects.filter(todo__previous=item).count(), 1)
        # Not even once the next one is done: one series, no branches
        ops.complete(new, actor=self.ada)
        ops.reopen(item, actor=self.ada)
        ops.complete(item, actor=self.ada)
        self.assertEqual(Item.objects.filter(todo__previous=item).count(), 1)

    def test_assignees_who_cant_follow_are_left_out(self):
        item = self.todo("FREQ=DAILY", assignees=[self.ada, self.cleo, self.bob])
        self.bob.is_active = False
        self.bob.save()
        # Hidden from clients since: Cleo can't see the next to-do
        ops.set_visibility(self.list, visible=False, actor=self.ada)
        ops.complete(item, actor=self.ada)
        self.assertEqual(list(self.following(item).todo.assignees.all()), [self.ada])

    def test_a_client_completes_a_visible_recurring_todo(self):
        item = self.todo("FREQ=DAILY", "2026-11-20", assignees=[self.cleo])
        with at("2026-11-20 12:00"):
            ops.complete(item, actor=self.cleo)
        new = self.following(item)
        self.assertEqual(new.todo.due_on, d("2026-11-21"))
        self.assertTrue(new.is_client_visible)
        self.assertEqual(list(new.todo.assignees.all()), [self.cleo])

    def test_update_and_validation(self):
        item = self.todo("")
        ops.update_todo(
            item,
            actor=self.ada,
            recurrence=" rrule:freq=daily ",
            recurrence_ends_on=d("2027-01-01"),
            recurrence_count=3,
        )
        todo = item.todo
        todo.refresh_from_db()
        self.assertEqual(
            (todo.recurrence, todo.recurrence_ends_on, todo.recurrence_count),
            ("FREQ=DAILY", d("2027-01-01"), 3),
        )
        # The end alone keeps the rule
        ops.update_todo(item, actor=self.ada, recurrence_count=None)
        todo.refresh_from_db()
        self.assertEqual(
            (todo.recurrence, todo.recurrence_ends_on), ("FREQ=DAILY", d("2027-01-01"))
        )
        with self.assertRaises(schedules.InvalidRule):
            ops.update_todo(item, actor=self.ada, recurrence="FREQ=HOURLY")
        with self.assertRaises(schedules.InvalidRule):
            self.todo("sometimes")
        # Removing the rule removes its end and count
        ops.update_todo(item, actor=self.ada, recurrence="")
        todo.refresh_from_db()
        self.assertEqual(
            (todo.recurrence, todo.recurrence_ends_on, todo.recurrence_count),
            ("", None, None),
        )


class PagesTest(RecurrenceTestCase):
    def test_the_todo_page_sets_the_repeat(self):
        item = self.todo("", "2026-11-20")
        self.client.force_login(self.ada)
        url = item.get_absolute_url()
        self.assertContains(self.client.get(url), "Repeat")
        data = {
            "form": "todo",
            "title": "Water",
            "due_on": "2026-11-20",
            "repeat": "weekly",
            "recurrence_count": "3",
        }
        self.assertRedirects(self.client.post(url, data), url)
        item.todo.refresh_from_db()
        self.assertEqual(item.todo.recurrence, "FREQ=WEEKLY;BYDAY=FR")
        self.assertEqual(item.todo.recurrence_count, 3)
        response = self.client.get(url)
        self.assertContains(response, "Repeats: every Friday.")
        self.assertContains(response, '<option value="weekly" selected>')
        # Custom
        data |= {"repeat": "custom", "custom_rule": "FREQ=WEEKLY;BYDAY=MO,TH"}
        self.client.post(url, data)
        item.todo.refresh_from_db()
        self.assertEqual(item.todo.recurrence, "FREQ=WEEKLY;BYDAY=MO,TH")
        self.assertContains(self.client.get(url), "FREQ=WEEKLY;BYDAY=MO,TH")
        # Invalid, empty
        for rule in ["FREQ=HOURLY", ""]:
            response = self.client.post(url, data | {"custom_rule": rule})
            self.assertEqual(response.status_code, 200)
            item.todo.refresh_from_db()
            self.assertEqual(item.todo.recurrence, "FREQ=WEEKLY;BYDAY=MO,TH")
        # Removing it
        self.client.post(url, data | {"repeat": ""})
        item.todo.refresh_from_db()
        self.assertEqual((item.todo.recurrence, item.todo.recurrence_count), ("", None))

    def test_the_inline_form(self):
        self.client.force_login(self.ada)
        url = self.list.get_absolute_url()
        self.assertContains(self.client.get(url), 'name="repeat"')
        response = self.client.post(
            url,
            {
                "title": "Pay rent",
                "due_on": "2026-01-31",
                "repeat": "monthly",
                "recurrence_ends_on": "2027-01-31",
            },
            headers={"X-Biwak-Fragment": "1"},
        )
        self.assertEqual(response.status_code, 201)
        todo = Item.objects.get(title="Pay rent").todo
        self.assertEqual(
            (todo.recurrence, todo.recurrence_ends_on),
            ("FREQ=MONTHLY;BYMONTHDAY=28,29,30,31;BYSETPOS=-1", d("2027-01-31")),
        )
        response = self.client.post(
            url,
            {"title": "Bad", "repeat": "custom", "custom_rule": "nope"},
            headers={"X-Biwak-Fragment": "1"},
        )
        self.assertEqual(response.status_code, 422)
        self.assertFalse(Item.objects.filter(title="Bad").exists())

    def test_completing_from_the_page_and_the_link_to_the_previous(self):
        item = self.todo("FREQ=DAILY", "2026-11-20")
        self.client.force_login(self.ada)
        with at("2026-11-20 12:00"):
            self.client.post(f"/todos/{item.pk}/toggle/")
        new = self.following(item)
        response = self.client.get(new.get_absolute_url())
        self.assertContains(response, "Previous:")
        self.assertContains(response, "completed on 20. November 2026 by Ada")
        self.assertContains(response, item.get_absolute_url())

    def test_a_client_doesnt_see_an_internal_previous(self):
        item = self.todo("FREQ=DAILY", "2026-11-20")
        ops.complete(item, actor=self.ada)
        new = self.following(item)
        # Moved to an internal list since
        ops.move_todo(item, todolist=self.internal, actor=self.ada)
        self.client.force_login(self.cleo)
        response = self.client.get(new.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Previous:")
        self.client.force_login(self.ada)
        self.assertContains(self.client.get(new.get_absolute_url()), "Previous:")


class APITest(RecurrenceTestCase):
    def api(self, user):
        _token, secret = APIToken.create_for(user=user, title="Test", access="write")
        return {"authorization": f"Bearer {secret}"}

    def send(self, method, path, user, data=None):
        return getattr(self.client, method)(
            f"/api/v1/{path}",
            data,
            content_type="application/json",
            headers=self.api(user),
        )

    def test_create_patch_and_complete(self):
        response = self.send(
            "post",
            f"lists/{self.list.pk}/todos/",
            self.ada,
            {
                "title": "Pay rent",
                "due_on": "2026-11-20",
                "recurrence": "monthly",
                "recurrence_count": 2,
                "recurrence_ends_on": "2027-12-31",
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()
        self.assertEqual(data["recurrence"], "FREQ=MONTHLY;BYMONTHDAY=20")
        self.assertEqual(data["recurrence_description"], "the 20th of every month")
        self.assertEqual(data["recurrence_count"], 2)
        self.assertEqual(data["recurrence_ends_on"], "2027-12-31")
        self.assertIsNone(data["previous_id"])
        response = self.send(
            "patch", f"todos/{data['id']}/", self.ada, {"recurrence": "FREQ=DAILY"}
        )
        self.assertEqual(response.json()["recurrence"], "FREQ=DAILY")
        self.assertEqual(response.json()["recurrence_count"], 2)
        with at("2026-11-20 12:00"):
            response = self.send("post", f"todos/{data['id']}/complete/", self.ada)
        new = self.following(Item.objects.get(pk=data["id"]))
        self.assertEqual(response.json()["recurrence_count"], 2)
        response = self.send("get", f"todos/{new.pk}/", self.ada)
        self.assertEqual(response.json()["previous_id"], data["id"])
        self.assertEqual(response.json()["recurrence_count"], 1)
        # null removes it with its end and count
        response = self.send(
            "patch", f"todos/{new.pk}/", self.ada, {"recurrence": None}
        )
        self.assertEqual(response.json()["recurrence"], "")
        self.assertIsNone(response.json()["recurrence_count"])

    def test_preset_follows_the_new_due_date(self):
        item = self.todo("")
        response = self.send(
            "patch",
            f"todos/{item.pk}/",
            self.ada,
            {"due_on": "2026-11-21", "recurrence": "weekly"},
        )
        self.assertEqual(response.json()["recurrence"], "FREQ=WEEKLY;BYDAY=SA")

    def test_errors(self):
        for body in [
            {"recurrence": "sometimes"},
            {"recurrence": "FREQ=WEEKLY;COUNT=3"},
            {"recurrence_count": 0, "recurrence": "daily"},
        ]:
            with self.subTest(body=body):
                response = self.send(
                    "post",
                    f"lists/{self.list.pk}/todos/",
                    self.ada,
                    {"title": "x"} | body,
                )
                self.assertEqual(response.status_code, 400)
        item = self.todo("")
        response = self.send(
            "patch", f"todos/{item.pk}/", self.ada, {"recurrence": "x"}
        )
        self.assertEqual(response.status_code, 400)

    def test_client_completes_and_doesnt_learn_internal_ids(self):
        item = self.todo("FREQ=DAILY", "2026-11-20")
        response = self.send("post", f"todos/{item.pk}/complete/", self.cleo)
        self.assertEqual(response.status_code, 200)
        new = self.following(item)
        ops.move_todo(item, todolist=self.internal, actor=self.ada)
        self.assertIsNone(
            self.send("get", f"todos/{new.pk}/", self.cleo).json()["previous_id"]
        )
        # Staff don't get it either (the API doesn't know who is asking)
        self.assertIsNone(
            self.send("get", f"todos/{new.pk}/", self.ada).json()["previous_id"]
        )
        self.assertEqual(
            self.send("get", f"todos/{item.pk}/", self.cleo).status_code, 404
        )
