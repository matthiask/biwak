"""Start dates on to-dos (specs/start-dates.md)"""

import datetime as dt
import re
from zoneinfo import ZoneInfo

import time_machine
from django.core import mail
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone, translation

from biwak.activity.models import Action, Event
from biwak.formats import format_range
from biwak.items import operations as ops
from biwak.items.models import Item
from biwak.test_utils import person, project


ZURICH = ZoneInfo("Europe/Zurich")


def d(text):
    return dt.date.fromisoformat(text)


def on(day):
    """Today is ``day`` in the installation's time zone"""
    return time_machine.travel(
        dt.datetime.fromisoformat(f"{day} 10:00").replace(tzinfo=ZURICH), tick=False
    )


class StartDatesBase(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.bob, self.cleo])
        self.list = ops.create_list(
            project=self.project, title="Camp", creator=self.ada, visible=True
        )

    def todo(self, title="Pack the tents", *, due=None, starts=None, **kwargs):
        return ops.create_todo(
            todolist=kwargs.pop("todolist", self.list),
            title=title,
            creator=kwargs.pop("creator", self.ada),
            due_on=d(due) if due else None,
            starts_on=d(starts) if starts else None,
            **kwargs,
        )

    def refresh(self, item):
        return Item.objects.select_related("todo").get(pk=item.pk)


class OperationsTest(StartDatesBase):
    def test_a_start_date_with_a_due_date(self):
        item = self.todo(due="2026-12-07", starts="2026-12-03")
        self.assertEqual(item.todo.starts_on, d("2026-12-03"))
        self.assertEqual(
            self.todo(due="2026-12-07", starts="2026-12-07").todo.starts_on,
            d("2026-12-07"),
        )

    def test_no_start_date_without_a_due_date_or_after_it(self):
        with self.assertRaisesMessage(ops.InvalidDates, "needs a due date"):
            self.todo(starts="2026-12-03")
        with self.assertRaisesMessage(ops.InvalidDates, "can't be after"):
            self.todo(due="2026-12-03", starts="2026-12-04")
        self.assertFalse(Item.objects.filter(title="Pack the tents").exists())

    def test_changing_the_dates(self):
        item = self.todo(due="2026-12-07")
        ops.update_todo(item, actor=self.ada, starts_on=d("2026-12-03"))
        self.assertEqual(self.refresh(item).todo.starts_on, d("2026-12-03"))
        with self.assertRaises(ops.InvalidDates):
            # The due date before the start
            ops.update_todo(item, actor=self.ada, due_on=d("2026-12-01"))
        with self.assertRaises(ops.InvalidDates):
            ops.update_todo(
                item, actor=self.ada, due_on=None, starts_on=d("2026-12-03")
            )
        ops.update_todo(
            item, actor=self.ada, due_on=d("2026-12-01"), starts_on=d("2026-11-30")
        )
        todo = self.refresh(item).todo
        self.assertEqual(
            (todo.starts_on, todo.due_on), (d("2026-11-30"), d("2026-12-01"))
        )

    def test_removing_the_due_date_removes_the_start_date(self):
        item = self.todo(due="2026-12-07", starts="2026-12-03")
        ops.update_todo(item, actor=self.ada, due_on=None)
        todo = self.refresh(item).todo
        self.assertEqual((todo.starts_on, todo.due_on), (None, None))

    def test_changing_the_start_date_records_an_edit(self):
        item = self.todo(due="2026-12-07")
        Event.objects.all().delete()
        ops.update_todo(item, actor=self.ada, starts_on=d("2026-12-03"))
        event = Event.objects.get(action=Action.EDITED)
        self.assertEqual(event.data["fields"], ["starts_on"])
        self.assertEqual(event.data["starts_on"], "2026-12-03")
        self.assertIsNone(event.data["starts_was"])
        self.assertEqual(event.data["due_on"], "2026-12-07")
        self.assertEqual(event.data["due_was"], "2026-12-07")

    def test_the_same_dates_record_nothing(self):
        item = self.todo(due="2026-12-07", starts="2026-12-03")
        Event.objects.all().delete()
        ops.update_todo(
            item, actor=self.ada, due_on=d("2026-12-07"), starts_on=d("2026-12-03")
        )
        self.assertFalse(Event.objects.exists())


class RecurrenceTest(StartDatesBase):
    def test_the_next_one_keeps_the_distance(self):
        item = self.todo(
            due="2026-11-27", starts="2026-11-23", recurrence="FREQ=WEEKLY;BYDAY=FR"
        )
        with on("2026-11-26"):
            ops.complete(item, actor=self.bob)
        following = Item.objects.get(todo__previous=item)
        self.assertEqual(following.todo.due_on, d("2026-12-04"))
        self.assertEqual(following.todo.starts_on, d("2026-11-30"))

    def test_without_a_start_date_none(self):
        item = self.todo(due="2026-11-27", recurrence="FREQ=WEEKLY;BYDAY=FR")
        with on("2026-11-26"):
            ops.complete(item, actor=self.bob)
        self.assertIsNone(Item.objects.get(todo__previous=item).todo.starts_on)


class TimelineTest(StartDatesBase):
    def lines(self, item):
        from biwak.activity.test_timeline import region

        self.client.force_login(self.ada)
        return region(self.client.get(item.get_absolute_url()))

    def test_changed_the_dates(self):
        item = self.todo(due="2026-12-07")
        Event.objects.all().delete()
        ops.update_todo(item, actor=self.bob, starts_on=d("2026-12-03"))
        (line,) = self.lines(item)
        self.assertIn("changed the dates to 3–7 Dec 2026", line)

    def test_back_to_the_same_dates_is_nothing(self):
        item = self.todo(due="2026-12-07")
        Event.objects.all().delete()
        ops.update_todo(item, actor=self.bob, starts_on=d("2026-12-03"))
        ops.update_todo(item, actor=self.bob, starts_on=None)
        self.assertEqual(self.lines(item), [])

    def test_the_due_date_alone_as_before(self):
        item = self.todo()
        Event.objects.all().delete()
        ops.update_todo(item, actor=self.bob, due_on=d("2026-12-07"))
        (line,) = self.lines(item)
        self.assertIn("set the due date to 7 Dec 2026", line)


class RangeTest(SimpleTestCase):
    def test_ranges(self):
        cases = [
            ("2026-12-03", "2026-12-07", "MONTH_DAY_FORMAT", "3–7 Dec"),
            ("2026-11-28", "2026-12-03", "MONTH_DAY_FORMAT", "28 Nov – 3 Dec"),
            ("2026-12-28", "2027-01-03", "MONTH_DAY_FORMAT", "28 Dec – 3 Jan"),
            ("2026-12-03", "2026-12-07", "SHORT_DATE_FORMAT", "3–7 Dec 2026"),
            (
                "2026-12-28",
                "2027-01-03",
                "SHORT_DATE_FORMAT",
                "28 Dec 2026 – 3 Jan 2027",
            ),
            (
                "2026-12-03",
                "2026-12-07",
                "SHORT_WEEKDAY_DATE_FORMAT",
                "Thu, 3 Dec – Mon, 7 Dec 2026",
            ),
            (None, "2026-12-07", "MONTH_DAY_FORMAT", "7 Dec"),
            ("2026-12-07", "2026-12-07", "MONTH_DAY_FORMAT", "7 Dec"),
        ]
        with translation.override("en"):
            for start, end, name, expected in cases:
                with self.subTest(start=start, end=end, name=name):
                    self.assertEqual(
                        format_range(start and d(start), d(end), name), expected
                    )

    def test_german(self):
        with translation.override("de"):
            self.assertEqual(
                format_range(d("2026-12-03"), d("2026-12-07"), "MONTH_DAY_FORMAT"),
                "3.–7. Dez.",
            )
            self.assertEqual(
                format_range(d("2026-11-28"), d("2026-12-03"), "MONTH_DAY_FORMAT"),
                "28. Nov. – 3. Dez.",
            )


def between(html, start, end):
    """The part of ``html`` from ``start`` to the next ``end``, empty if it
    isn't there"""
    found = re.search(re.escape(start) + r".*?" + re.escape(end), html, re.DOTALL)
    return found[0] if found else ""


class FormsTest(StartDatesBase):
    FRAGMENT = {"X-Biwak-Fragment": "1"}

    def test_the_inline_form(self):
        self.client.force_login(self.ada)
        url = self.list.get_absolute_url()
        page = self.client.get(url).content.decode()
        self.assertIn('name="starts_on"', page)
        self.assertIn("data-starts-on", page)
        response = self.client.post(
            url,
            {"title": "Book", "due_on": "2026-12-07", "starts_on": "2026-12-03"},
            headers=self.FRAGMENT,
        )
        self.assertEqual(response.status_code, 201)
        self.assertIn("3–7 Dec", response.content.decode())
        self.assertEqual(Item.objects.get(title="Book").todo.starts_on, d("2026-12-03"))
        for data, error in [
            ({"starts_on": "2026-12-03"}, "A start date needs a due date."),
            (
                {"due_on": "2026-12-01", "starts_on": "2026-12-03"},
                "The start date can't be after the due date.",
            ),
        ]:
            with self.subTest(data=data):
                response = self.client.post(
                    url, {"title": "Bad"} | data, headers=self.FRAGMENT
                )
                self.assertEqual(response.status_code, 422)
                self.assertIn(error, response.content.decode())
        self.assertFalse(Item.objects.filter(title="Bad").exists())

    def edit(self, user, item, **data):
        self.client.force_login(user)
        return self.client.post(
            reverse("todo_edit", args=[item.pk]),
            {
                "form": "todo",
                "title": item.title,
                "notes": "",
                "recurrence_frequency": "",
                "assignees": [p.pk for p in item.todo.assignees.all()],
            }
            | data,
        )

    def test_the_edit_form_as_staff_and_as_a_client(self):
        item = self.todo(due="2026-12-07")
        for user, starts in [(self.ada, "2026-12-03"), (self.cleo, "2026-12-04")]:
            with self.subTest(user=user):
                response = self.edit(user, item, due_on="2026-12-07", starts_on=starts)
                self.assertRedirects(
                    response, item.get_absolute_url(), fetch_redirect_response=False
                )
                self.assertEqual(self.refresh(item).todo.starts_on, d(starts))
        response = self.edit(self.ada, item, due_on="", starts_on="2026-12-03")
        self.assertContains(response, "A start date needs a due date.")
        response = self.edit(
            self.ada, item, due_on="2026-12-01", starts_on="2026-12-03"
        )
        self.assertContains(
            response, "The start date can&#x27;t be after the due date."
        )
        self.assertEqual(self.refresh(item).todo.starts_on, d("2026-12-04"))

    def test_the_edit_form_shows_the_start_date(self):
        item = self.todo(due="2026-12-07", starts="2026-12-03")
        self.client.force_login(self.ada)
        page = self.client.get(reverse("todo_edit", args=[item.pk])).content.decode()
        self.assertRegex(
            page,
            r'name="starts_on"[^>]*value="2026-12-03"|value="2026-12-03"[^>]*name="starts_on"',
        )

    def test_the_to_dos_page_says_when_it_starts(self):
        item = self.todo(due="2026-12-07", starts="2026-12-03")
        for user in [self.ada, self.cleo]:
            with self.subTest(user=user):
                self.client.force_login(user)
                page = self.client.get(item.get_absolute_url()).content.decode()
                self.assertIn("Starts on", page)
                self.assertIn("Thursday, 3 December 2026", page)
        self.client.force_login(self.ada)
        other = self.todo("Other", due="2026-12-07")
        self.assertNotIn(
            "Starts on", self.client.get(other.get_absolute_url()).content.decode()
        )


class RowsTest(StartDatesBase):
    def test_rows_show_the_range(self):
        self.todo("Within", due="2026-12-07", starts="2026-12-03")
        self.todo("Across", due="2026-12-03", starts="2026-11-28")
        self.todo("Plain", due="2026-12-09")
        for user in [self.ada, self.cleo]:
            with self.subTest(user=user), on("2026-11-20"):
                self.client.force_login(user)
                page = self.client.get(self.list.get_absolute_url()).content.decode()
                self.assertIn("3–7 Dec", page)
                self.assertIn("28 Nov – 3 Dec", page)
                self.assertIn("9 Dec", page)

    def test_overdue_by_the_due_date(self):
        self.todo("Late", due="2026-11-24", starts="2026-11-20")
        self.client.force_login(self.ada)
        with on("2026-11-26"):
            page = self.client.get(self.list.get_absolute_url()).content.decode()
        self.assertIn("Overdue · 20–24 Nov", page)


class StartingLaterTest(StartDatesBase):
    """On 26 November 2026: "Now" started yesterday, "Today" starts today,
    "Later" on 30 November; the internal one only for staff"""

    def setUp(self):
        super().setUp()
        self.internal = ops.create_list(
            project=self.project, title="Internal", creator=self.ada
        )
        people = [self.ada, self.cleo]
        self.todo("Now", due="2026-11-28", starts="2026-11-25", assignees=people)
        self.todo("Today", due="2026-11-28", starts="2026-11-26", assignees=people)
        self.todo("Later", due="2026-12-01", starts="2026-11-30", assignees=people)
        self.todo("No date", assignees=people)
        self.todo(
            "Secret later",
            due="2026-12-01",
            starts="2026-11-30",
            todolist=self.internal,
            assignees=[self.ada],
        )

    def page(self, user, url, **params):
        self.client.force_login(user)
        with on("2026-11-26"):
            response = self.client.get(url, params)
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        found = re.search(
            r"<details[^>]*data-starting-later.*?</details>", html, re.DOTALL
        )
        later = found[0] if found else ""
        return html.replace(later, ""), later

    def test_my_to_dos_and_the_to_dos_page(self):
        for user, hidden in [(self.ada, None), (self.cleo, "Secret later")]:
            for params in [{}, {"grouping": "due"}]:
                for url in ["/todos/", f"/projects/{self.project.pk}/todos/"]:
                    with self.subTest(user=user, params=params, url=url):
                        current, later = self.page(user, url, **params)
                        for title in ["Now", "Today", "No date"]:
                            self.assertIn(title, current)
                            self.assertNotIn(title, later)
                        self.assertNotIn("Later", current)
                        self.assertIn("Later", later)
                        count = 1 if hidden else 2
                        self.assertIn(f"Starting later ({count})", later)
                        if hidden:
                            self.assertNotIn(hidden, current + later)
                        else:
                            self.assertIn("Secret later", later)

    def test_nothing_starting_later_nothing_shown(self):
        _current, later = self.page(self.bob, "/todos/")
        self.assertEqual(later, "")

    def test_completed_ones_are_not_split(self):
        for item in Item.objects.filter(title__in=["Now", "Later"]):
            ops.complete(item, actor=self.ada)
        current, later = self.page(self.ada, "/todos/", state="completed")
        self.assertEqual(later, "")
        self.assertIn("Now", current)
        self.assertIn("Later", current)

    def test_lists_and_search_show_it_as_always(self):
        current, later = self.page(self.cleo, self.list.get_absolute_url())
        self.assertIn("Later", current)
        self.assertEqual(later, "")

    def test_home(self):
        self.todo(
            "Far later", due="2026-12-20", starts="2026-12-10", assignees=[self.ada]
        )
        for user, hidden in [(self.ada, None), (self.cleo, "Secret later")]:
            with self.subTest(user=user):
                html, later = self.page(user, "/")
                due = between(html, 'data-home="due"', "</section>")
                self.assertIn("Now", due)
                self.assertIn("Today", due)
                self.assertNotIn("Later", due)
                self.assertIn("Later", later)
                self.assertNotIn("Far later", later)
                if hidden:
                    self.assertNotIn(hidden, html + later)
                    self.assertIn("Starting later (1)", later)
                else:
                    self.assertIn("Starting later (2)", later)

    def test_home_without_any_starting_later(self):
        Item.objects.filter(title__icontains="later").delete()
        html, later = self.page(self.ada, "/")
        self.assertEqual(later, "")
        self.assertNotIn("Starting later", html)


class CalendarTest(StartDatesBase):
    def test_the_feed_shows_the_range(self):
        from icalendar import Calendar

        from biwak.accounts.models import CalendarToken

        self.todo("Range", due="2026-12-07", starts="2026-12-03", assignees=[self.ada])
        self.todo("Day", due="2026-12-09", assignees=[self.ada])
        link = CalendarToken.renew(self.ada)
        response = self.client.get(f"/calendar/{link.token}.ics")
        events = {
            str(e["summary"]): (e["dtstart"].dt, e["dtend"].dt)
            for e in Calendar.from_ical(response.content).walk("VEVENT")
        }
        self.assertEqual(events["Range"], (d("2026-12-03"), d("2026-12-08")))
        self.assertEqual(events["Day"], (d("2026-12-09"), d("2026-12-10")))


@override_settings(
    BASE_URL="https://biwak.example.org", DEFAULT_FROM_EMAIL="biwak@example.org"
)
class MailTest(StartDatesBase):
    def test_the_mail_says_when_it_starts(self):
        from biwak.activity.mails import send_mails
        from biwak.activity.operations import subscribe

        item = self.todo(due="2026-12-07")
        subscribe(self.bob, item)
        with self.captureOnCommitCallbacks(execute=True):
            ops.update_todo(item, actor=self.ada, starts_on=d("2026-12-03"))
        with self.captureOnCommitCallbacks(execute=True):
            send_mails(now=timezone.now() + dt.timedelta(minutes=11))
        (message,) = [m for m in mail.outbox if m.to == [self.bob.email]]
        self.assertIn("Starts on: 3 December 2026", message.body)
        self.assertIn("changed it.", message.body)
