"""The due date as a badge (specs/todos.md, "The to-do's page"): danger when an open
to-do is past due, quiet "Today", never for completed ones"""

import datetime as dt
from zoneinfo import ZoneInfo

import time_machine
from django.test import TestCase
from django.urls import reverse

from biwak.items import operations as ops
from biwak.test_utils import person, project


NOW = dt.datetime(2026, 11, 20, 10, 0, tzinfo=ZoneInfo("Europe/Zurich"))
DAY = dt.timedelta(days=1)


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ada = person("Ada")
        cls.project = project(members=[cls.ada])
        cls.todolist = ops.create_list(
            project=cls.project, title="Launch", creator=cls.ada
        )

    def setUp(self):
        travel = time_machine.travel(NOW, tick=False)
        travel.start()
        self.addCleanup(travel.stop)
        self.client.force_login(self.ada)
        self.today = NOW.date()

    def todo(self, due_on, *, completed=False):
        item = ops.create_todo(
            todolist=self.todolist, title="Pack", creator=self.ada, due_on=due_on
        )
        if completed:
            ops.complete(item, actor=self.ada)
        return item


class DueBadgeTest(Base):
    def pages(self, item):
        """Where a to-do shows its date: the list, the board, the to-do's
        page, "my to-dos" and the list by due date"""
        yield self.todolist.get_absolute_url()
        yield self.todolist.get_absolute_url() + "?view=board"
        yield item.get_absolute_url()
        yield reverse("todos") + "?assignee=anybody"
        yield reverse("project_todos", args=[self.project.pk])

    def assert_badge(self, item, expected):
        for url in self.pages(item):
            html = self.client.get(url).content.decode()
            # A later date is only text; the to-do's page has it in its facts
            shown = (
                None
                if url == item.get_absolute_url() and expected == "later"
                else expected
            )
            for state in ["overdue", "today", "later"]:
                self.assertEqual(
                    f'data-due="{state}"' in html, state == shown, (url, state)
                )

    def test_overdue(self):
        item = self.todo(self.today - DAY)
        self.assert_badge(item, "overdue")
        html = self.client.get(self.todolist.get_absolute_url()).content.decode()
        self.assertIn("Overdue · 19 Nov", html)
        self.assertIn("wb-tone-danger", html)

    def test_today(self):
        item = self.todo(self.today)
        self.assert_badge(item, "today")
        html = self.client.get(self.todolist.get_absolute_url()).content.decode()
        self.assertIn(">Today<", html)
        self.assertNotIn("wb-tone-danger", html)

    def test_later_is_plain_text(self):
        self.assert_badge(self.todo(self.today + DAY), "later")

    def test_no_date_no_badge(self):
        item = self.todo(None)
        for url in self.pages(item):
            self.assertNotContains(self.client.get(url), "data-due=")

    def test_completed_is_never_overdue(self):
        item = self.todo(self.today - DAY, completed=True)
        for url in [item.get_absolute_url(), reverse("todos") + "?completed=1"]:
            html = self.client.get(url).content.decode()
            self.assertNotIn('data-due="overdue"', html, url)
            self.assertNotIn("wb-tone-danger", html, url)

    def test_the_day_is_the_persons_today(self):
        # Just before midnight in Zurich it's still the 20th there
        with time_machine.travel(NOW.replace(hour=23, minute=50), tick=False):
            item = self.todo(self.today)
            self.assert_badge(item, "today")


class PaletteBadgeTest(Base):
    """Bookmarked to-dos in the palette's results"""

    def bookmarked(self, item):
        from biwak.bookmarks import operations as link_ops

        link_ops.add_bookmark(self.ada, item=item)
        return self.client.get(reverse("palette")).json()["bookmarks"][0]["due"]

    def test_overdue_today_later_and_completed(self):
        self.assertEqual(
            self.bookmarked(self.todo(self.today - DAY)),
            {"state": "overdue", "label": "Overdue · 19 Nov"},
        )
        self.assertEqual(
            self.bookmarked(self.todo(self.today)),
            {"state": "today", "label": "Today"},
        )
        self.assertIsNone(self.bookmarked(self.todo(self.today + DAY)))
        self.assertIsNone(self.bookmarked(self.todo(self.today - DAY, completed=True)))

    def test_other_kinds_have_none(self):
        from biwak.bookmarks import operations as link_ops

        link_ops.add_bookmark(self.ada, item=self.todolist)
        data = self.client.get(reverse("palette")).json()
        self.assertIsNone(data["bookmarks"][0]["due"])


class TodoPageBadgeTest(Base):
    """On the to-do's page the badge sits next to the date in the facts
    (specs/todos.md, "The to-do's page")"""

    def facts(self, item):
        html = self.client.get(item.get_absolute_url()).content.decode()
        return html[html.index('<dl class="wb-facts">') : html.index("</dl>")]

    def test_overdue_next_to_the_date(self):
        facts = self.facts(self.todo(self.today - DAY))
        self.assertRegex(
            facts,
            r"Thursday, 19 November 2026\s*<span\s+class=\"badge wb-tone-danger\""
            r"[^>]*>Overdue</span>",
        )

    def test_today_next_to_the_date(self):
        facts = self.facts(self.todo(self.today))
        self.assertRegex(facts, r"Friday, 20 November 2026\s*<span[^>]*>Today</span>")

    def test_later_is_just_the_date(self):
        facts = self.facts(self.todo(self.today + DAY))
        self.assertIn("Saturday, 21 November 2026", facts)
        self.assertNotIn("data-due", facts)

    def test_no_badge_line_above_the_facts(self):
        item = self.todo(self.today - DAY)
        html = self.client.get(item.get_absolute_url()).content.decode()
        self.assertEqual(html.count('data-due="overdue"'), 1)
