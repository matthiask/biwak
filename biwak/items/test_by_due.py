import datetime as dt
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import time_machine
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from icalendar import Calendar

from biwak.accounts.models import APIToken, CalendarToken, User
from biwak.items import due, operations as ops
from biwak.items.models import Item
from biwak.projects import operations as project_ops
from biwak.projects.models import Membership
from biwak.test_utils import person, project


def d(text):
    return dt.date.fromisoformat(text)


def at(text, tz="Europe/Zurich"):
    return time_machine.travel(
        dt.datetime.fromisoformat(text).replace(tzinfo=ZoneInfo(tz)), tick=False
    )


class GroupingTest(TestCase):
    def test_groups(self):
        today = d("2026-11-18")  # a Wednesday
        for due_on, group in [
            (None, "none"),
            ("2026-11-17", "overdue"),
            ("2026-11-18", "today"),
            ("2026-11-19", "this_week"),
            ("2026-11-22", "this_week"),  # Sunday
            ("2026-11-23", "next_week"),  # Monday
            ("2026-11-29", "next_week"),  # The Sunday after
            ("2026-11-30", "later"),
            ("2027-01-04", "later"),
        ]:
            with self.subTest(due_on=due_on):
                self.assertEqual(
                    due.group_of(d(due_on) if due_on else None, today), group
                )

    def test_a_sunday_has_no_rest_of_the_week(self):
        today = d("2026-11-22")
        self.assertEqual(due.group_of(d("2026-11-22"), today), "today")
        self.assertEqual(due.group_of(d("2026-11-23"), today), "next_week")
        self.assertEqual(due.group_of(d("2026-11-29"), today), "next_week")
        self.assertEqual(due.group_of(d("2026-11-30"), today), "later")
        # And a Monday has the whole week
        monday = d("2026-11-23")
        self.assertEqual(due.group_of(d("2026-11-29"), monday), "this_week")
        self.assertEqual(due.group_of(d("2026-11-30"), monday), "next_week")
        self.assertEqual(due.group_of(d("2026-12-06"), monday), "next_week")
        self.assertEqual(due.group_of(d("2026-12-07"), monday), "later")

    def test_the_sections_split_later_into_months(self):
        class Item:
            def __init__(self, due_on):
                self.todo = type("T", (), {"due_on": due_on})

        today = d("2026-11-18")
        items = [
            Item(d(day))
            for day in [
                "2026-11-23",
                "2026-12-01",
                "2026-12-24",
                "2027-01-05",
                "2027-02-01",
            ]
        ]
        self.assertEqual(
            [
                (key, str(label), len(found))
                for key, label, found in due.sections(items, today)
            ],
            [
                ("next_week", "Next week", 1),
                ("later-2026-12", "December", 2),
                ("later-2027-01", "January 2027", 1),
                ("later-2027-02", "February 2027", 1),
            ],
        )


class ByDueTestCase(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.bob, self.cleo])
        self.shared = ops.create_list(
            project=self.project, title="Shared", creator=self.ada, visible=True
        )
        self.internal = ops.create_list(
            project=self.project, title="Internal", creator=self.ada
        )
        self.other = project("Other", members=[self.ada])
        self.other_list = ops.create_list(
            project=self.other, title="Elsewhere", creator=self.ada
        )
        self.limited = project("Secret", members=[self.bob], all_access=False)
        self.limited_list = ops.create_list(
            project=self.limited, title="Hidden", creator=self.bob
        )

    def todo(self, title, due=None, *, todolist=None, assignees=(), group=None):
        return ops.create_todo(
            todolist=todolist or self.shared,
            title=title,
            creator=self.ada,
            due_on=d(due) if due else None,
            assignees=assignees,
            group=group,
        )

    def sections(self, response):
        return {
            key: [t.title for t in todos]
            for key, _label, todos in response.context["sections"]
        }


class PageTest(ByDueTestCase):
    def test_sections_in_the_installations_time_zone(self):
        self.todo("late", "2026-11-17")
        self.todo("now", "2026-11-18")
        self.todo("soon", "2026-11-22")
        self.todo("far", "2026-11-23")
        self.todo("whenever")
        self.client.force_login(self.ada)
        # 23:30 UTC on the 17th is already 00:30 on the 18th in Zurich
        with at("2026-11-17 23:30", "UTC"):
            sections = self.sections(
                self.client.get("/todos/?assignee=anybody&grouping=due")
            )
        self.assertEqual(
            sections,
            {
                "overdue": ["late"],
                "today": ["now"],
                "this_week": ["soon"],
                "next_week": ["far"],
                "none": ["whenever"],
            },
        )
        with at("2026-11-17 22:30", "UTC"):  # 23:30 on the 17th
            sections = self.sections(
                self.client.get("/todos/?assignee=anybody&grouping=due")
            )
        self.assertEqual(sections["today"], ["late"])
        # Sunday evening: the next day is next week
        with at("2026-11-22 23:30"):
            sections = self.sections(
                self.client.get("/todos/?assignee=anybody&grouping=due")
            )
        self.assertEqual(sections["next_week"], ["far"])
        self.assertEqual(sections["overdue"], ["late", "now"])
        self.assertEqual(sections["today"], ["soon"])

    def test_later_is_one_section_per_month(self):
        self.todo("next", "2026-11-25")
        self.todo("december", "2026-12-10")
        self.todo("january", "2027-01-03")
        self.client.force_login(self.ada)
        with at("2026-11-18 12:00"):
            response = self.client.get("/todos/?assignee=anybody&grouping=due")
        headings = [str(label) for _k, label, _t in response.context["sections"]]
        self.assertEqual(headings, ["Next week", "December", "January 2027"])
        self.assertContains(response, ">December<")
        self.assertNotContains(response, ">Later<")

    def test_across_projects_and_access(self):
        self.todo("Visible")
        self.todo("Elsewhere", todolist=self.other_list)
        self.todo("Secret", todolist=self.limited_list)
        self.client.force_login(self.ada)
        response = self.client.get("/todos/?assignee=anybody&assignee=anybody")
        self.assertContains(response, "Visible")
        self.assertContains(response, "Elsewhere")
        self.assertNotContains(response, "Secret")
        self.assertContains(response, "wb-client-badge")
        self.assertContains(response, '<h1 class="wb-title">To-dos</h1>')

    def test_a_client_sees_only_visible_todos(self):
        self.todo("Visible")
        self.todo("Internal one", todolist=self.internal)
        self.todo("Elsewhere", todolist=self.other_list)
        self.client.force_login(self.cleo)
        for url in [
            "/todos/",
            f"/projects/{self.project.pk}/todos/",
            "/todos/?visible=no",
            "/todos/?state=completed",
        ]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, "Internal one")
                self.assertNotContains(response, "Elsewhere")
        self.assertContains(
            self.client.get("/todos/?assignee=anybody&assignee=anybody"), "Visible"
        )
        # No filter by visibility for clients, and no way to see others' projects
        self.assertNotContains(
            self.client.get("/todos/?assignee=anybody&assignee=anybody"),
            'name="visible"',
        )
        self.assertEqual(
            self.client.get(f"/projects/{self.other.pk}/todos/").status_code, 404
        )
        response = self.client.get(f"/todos/?project={self.other.pk}")
        self.assertNotContains(response, "Elsewhere")
        self.assertContains(response, "Select a valid choice")

    def test_project_page(self):
        self.todo("Here")
        self.todo("There", todolist=self.other_list)
        self.client.force_login(self.ada)
        response = self.client.get(f"/projects/{self.project.pk}/todos/")
        self.assertContains(response, "Here")
        self.assertNotContains(response, "There")
        self.assertNotContains(response, 'name="project"')
        self.assertEqual(
            self.client.get(f"/projects/{self.limited.pk}/todos/").status_code, 404
        )
        self.assertEqual(self.client.get("/projects/99999/todos/").status_code, 404)
        self.assertContains(
            self.client.get(self.project.get_absolute_url()),
            f"/projects/{self.project.pk}/todos/",
        )
        self.client.force_login(self.bob)
        self.assertContains(
            self.client.get(f"/projects/{self.limited.pk}/todos/"), "To-dos"
        )

    def test_filters(self):
        self.todo("Mine", "2026-11-18", assignees=[self.ada])
        self.todo("Bobs", "2026-11-19", assignees=[self.bob])
        self.todo("Nobodys", "2026-11-20")
        self.todo("Internal", todolist=self.internal)
        self.todo("Other", todolist=self.other_list)
        self.client.force_login(self.ada)

        def found(**params):
            response = self.client.get(
                "/todos/", {"grouping": "due", "assignee": "anybody"} | params
            )
            self.assertEqual(response.status_code, 200)
            return sorted(
                todo.title
                for _k, _l, todos in response.context["sections"]
                for todo in todos
            )

        self.assertEqual(found(), ["Bobs", "Internal", "Mine", "Nobodys", "Other"])
        self.assertEqual(found(assignee="me"), ["Mine"])
        self.assertEqual(found(assignee="nobody"), ["Internal", "Nobodys", "Other"])
        self.assertEqual(found(assignee=self.bob.pk), ["Bobs"])
        self.assertEqual(found(project=self.other.pk), ["Other"])
        self.assertEqual(found(visible="yes"), ["Bobs", "Mine", "Nobodys"])
        self.assertEqual(found(visible="no"), ["Internal", "Other"])
        response = self.client.get("/todos/", {"assignee": "me"})
        self.assertContains(response, '<h1 class="wb-title">My to-dos</h1>')
        # Nonsense: an error, no to-dos
        for params in [
            {"assignee": "x"},
            {"project": "x"},
        ]:
            with self.subTest(params=params):
                response = self.client.get("/todos/", params)
                self.assertContains(response, "Select a valid choice")
                self.assertContains(response, "Nothing to do.")

    def test_completed_are_paginated(self):
        items = [self.todo(f"Done {n:02}") for n in range(55)]
        for n, item in enumerate(items):
            with at(f"2026-11-01 {n // 4 + 8:02}:{n % 4 * 10:02}"):
                ops.complete(item, actor=self.ada)
        self.todo("Open")
        self.client.force_login(self.ada)
        response = self.client.get("/todos/?assignee=anybody&state=completed")
        self.assertEqual(len(response.context["page"]), 50)
        self.assertEqual(response.context["page"][0].title, "Done 54")
        self.assertNotContains(response, ">Open</a>")
        self.assertContains(response, "state=completed&page=2")
        response = self.client.get("/todos/?assignee=anybody&state=completed&page=2")
        self.assertEqual(
            [t.title for t in response.context["page"]],
            [f"Done {n:02}" for n in range(4, -1, -1)],
        )

    def test_archived_projects_and_lists_are_out_of_the_way(self):
        self.todo("Open")
        self.todo("Old", todolist=self.other_list)
        self.client.force_login(self.ada)
        ops.archive(self.other_list, actor=self.ada)
        self.assertNotContains(
            self.client.get("/todos/?assignee=anybody&assignee=anybody"), "Old"
        )
        ops.unarchive(self.other_list, actor=self.ada)
        self.assertContains(
            self.client.get("/todos/?assignee=anybody&assignee=anybody"), "Old"
        )
        self.other.archived_at = dt.datetime.now(dt.UTC)
        self.other.save()
        self.assertNotContains(
            self.client.get("/todos/?assignee=anybody&assignee=anybody"), "Old"
        )

    def test_completing_from_the_list(self):
        item = self.todo("Do it", "2026-11-18")
        self.client.force_login(self.ada)
        response = self.client.get("/todos/?assignee=nobody")
        self.assertContains(response, 'value="/todos/?assignee=nobody"')
        response = self.client.post(
            f"/todos/{item.pk}/toggle/",
            {"next": "/todos/?assignee=nobody", "done": "1"},
        )
        self.assertRedirects(response, "/todos/?assignee=nobody")
        item.todo.refresh_from_db()
        self.assertIsNotNone(item.todo.completed_at)
        self.assertNotContains(
            self.client.get("/todos/?assignee=anybody&assignee=anybody"), "Do it"
        )
        self.assertContains(
            self.client.get("/todos/?assignee=anybody&state=completed"), "Do it"
        )
        # Not off to other sites
        response = self.client.post(
            f"/todos/{item.pk}/toggle/", {"next": "https://example.com/", "done": "1"}
        )
        self.assertRedirects(response, self.shared.get_absolute_url())

    def test_a_client_completes_a_visible_todo_from_the_list(self):
        item = self.todo("Visible")
        secret = self.todo("Secret", todolist=self.internal)
        self.client.force_login(self.cleo)
        self.assertEqual(
            self.client.post(f"/todos/{secret.pk}/toggle/").status_code, 404
        )
        self.client.post(f"/todos/{item.pk}/toggle/", {"next": "/todos/", "done": "1"})
        item.todo.refresh_from_db()
        self.assertEqual(item.todo.completed_by, self.cleo)


class APITest(ByDueTestCase):
    def api(self, user):
        _token, secret = APIToken.create_for(user=user, title="T", access="read")
        return {"authorization": f"Bearer {secret}"}

    def get(self, user, **params):
        return self.client.get(
            "/api/v1/todos/", {"grouping": "due"} | params, headers=self.api(user)
        )

    def titles(self, response):
        self.assertEqual(response.status_code, 200, response.content)
        return [t["title"] for t in response.json()["results"]]

    def test_staff(self):
        self.todo("Far", "2026-12-24", assignees=[self.ada])
        self.todo("Whenever")
        self.todo("Soon", "2026-11-19", assignees=[self.bob])
        self.todo("Internal", "2026-11-20", todolist=self.internal)
        self.todo("Secret", todolist=self.limited_list)
        with at("2026-11-18 12:00"):
            response = self.get(self.ada)
            self.assertEqual(
                self.titles(response), ["Soon", "Internal", "Far", "Whenever"]
            )
            data = response.json()["results"]
            self.assertEqual(
                [t["due_group"] for t in data],
                ["this_week", "this_week", "later", "none"],
            )
            self.assertEqual(data[0]["project_name"], "Website")
            self.assertEqual(data[0]["list_title"], "Shared")
            self.assertEqual(data[1]["visible_to_clients"], False)
            self.assertEqual(self.titles(self.get(self.ada, assignee="me")), ["Far"])
            self.assertEqual(
                self.titles(self.get(self.ada, assignee=self.bob.pk)), ["Soon"]
            )
            self.assertEqual(
                self.titles(self.get(self.ada, assignee="nobody")),
                ["Internal", "Whenever"],
            )
            self.assertEqual(
                self.titles(self.get(self.ada, due_group="later")), ["Far"]
            )
            self.assertEqual(self.titles(self.get(self.ada, due_group="next_week")), [])
            self.todo("Next", "2026-11-24")
            self.assertEqual(
                self.titles(self.get(self.ada, due_group="next_week")), ["Next"]
            )
            self.assertEqual(
                self.get(self.ada, due_group="next_week").json()["results"][0][
                    "due_group"
                ],
                "next_week",
            )
            self.assertEqual(
                self.titles(
                    self.get(
                        self.ada, project_id=self.project.pk, visible_to_clients=False
                    )
                ),
                ["Internal"],
            )
        self.assertEqual(
            self.get(self.ada, project_id=self.limited.pk).status_code, 404
        )
        self.assertEqual(self.get(self.ada, assignee="x").status_code, 400)
        self.assertEqual(self.get(self.ada, due_group="soonish").status_code, 422)

    def test_cursor_pagination(self):
        for n, due_on in enumerate([
            "2026-11-20",
            None,
            "2026-11-19",
            "2026-11-19",
            None,
        ]):
            self.todo(f"t{n}", due_on)
        seen, cursor = [], None
        for _page in range(10):
            params = {"page_size": 2} | ({"cursor": cursor} if cursor else {})
            data = self.get(self.ada, **params).json()
            seen += [t["title"] for t in data["results"]]
            if not data["next"]:
                break
            cursor = parse_qs(urlsplit(data["next"]).query)["cursor"][0]
        self.assertEqual(seen, ["t2", "t3", "t0", "t1", "t4"])

    def test_completed(self):
        a, b = self.todo("a"), self.todo("b")
        with at("2026-11-01 10:00"):
            ops.complete(a, actor=self.ada)
        with at("2026-11-02 10:00"):
            ops.complete(b, actor=self.ada)
        self.todo("open")
        self.assertEqual(self.titles(self.get(self.ada, completed=True)), ["b", "a"])
        self.assertEqual(self.titles(self.get(self.ada)), ["open"])

    def test_a_client_sees_only_visible_todos(self):
        self.todo("Visible", "2026-11-20", assignees=[self.cleo])
        self.todo("Internal", "2026-11-20", todolist=self.internal)
        self.todo("Elsewhere", todolist=self.other_list)
        self.assertEqual(self.titles(self.get(self.cleo)), ["Visible"])
        for params in [
            {"visible_to_clients": False},
            {"assignee": "nobody"},
        ]:
            with self.subTest(params=params):
                response = self.get(self.cleo, **params)
                self.assertNotIn("Internal", str(response.content))
        self.assertEqual(self.get(self.cleo, project_id=self.other.pk).status_code, 404)
        self.assertEqual(self.titles(self.get(self.cleo, assignee="me")), ["Visible"])
        self.assertEqual(self.client.get("/api/v1/todos/").status_code, 401)

    def test_clients_find_nobody_by_somebody_they_may_not_know(self):
        """Somebody removed from the project stays assigned to completed
        to-dos; ``assignees`` doesn't name them to clients, and filtering
        by their ID finds nothing either (2026-11-28, specs/access.md)"""
        todo = self.todo("Pitch", assignees=[self.bob, self.ada])
        ops.complete(todo, actor=self.ada)
        project_ops.remove_member(self.project, self.bob, actor=self.ada)
        for user, titles in [(self.ada, ["Pitch"]), (self.cleo, [])]:
            with self.subTest(user=user):
                response = self.get(user, assignee=str(self.bob.pk), completed="true")
                self.assertEqual(self.titles(response), titles)
        # Members they know
        response = self.get(self.cleo, assignee=str(self.ada.pk), completed="true")
        self.assertEqual(self.titles(response), ["Pitch"])


class FeedTest(ByDueTestCase):
    def link(self, user):
        return CalendarToken.renew(user)

    def feed(self, link):
        return self.client.get(f"/calendar/{link.token}.ics")

    def events(self, response):
        self.assertEqual(response.status_code, 200)
        calendar = Calendar.from_ical(response.content)
        return [
            (str(e["summary"]), e["dtstart"].dt, e["dtend"].dt)
            for e in calendar.walk("VEVENT")
        ]

    def test_the_page(self):
        self.client.force_login(self.ada)
        self.assertContains(self.client.get("/accounts/calendar/"), "Create the link")
        self.assertNotContains(self.client.get("/accounts/calendar/"), ".ics")
        self.assertRedirects(
            self.client.post("/accounts/calendar/"), "/accounts/calendar/"
        )
        link = CalendarToken.objects.get(user=self.ada)
        response = self.client.get("/accounts/calendar/")
        self.assertContains(response, f"http://testserver/calendar/{link.token}.ics")
        self.assertContains(response, "Make a new link")
        self.assertContains(self.client.get("/"), "/accounts/calendar/")
        # Another person's link isn't shown
        self.client.force_login(self.bob)
        self.assertNotContains(self.client.get("/accounts/calendar/"), link.token)
        self.client.logout()
        self.assertEqual(self.client.get("/accounts/calendar/").status_code, 302)

    def test_archived_lists_are_out_of_the_feed(self):
        self.todo("Old", "2026-11-20", assignees=[self.ada], todolist=self.other_list)
        link = self.link(self.ada)
        self.assertEqual(len(self.events(self.feed(link))), 1)
        ops.archive(self.other_list, actor=self.ada)
        self.assertEqual(self.events(self.feed(link)), [])

    def test_the_feed_needs_no_login(self):
        self.todo("Mine", "2026-11-20", assignees=[self.ada])
        self.todo("Bobs", "2026-11-20", assignees=[self.bob])
        self.todo("No date", assignees=[self.ada])
        done = self.todo("Done", "2026-11-21", assignees=[self.ada])
        ops.complete(done, actor=self.ada)
        self.todo(
            "Internal", "2026-12-31", todolist=self.internal, assignees=[self.ada]
        )
        link = self.link(self.ada)
        response = self.feed(link)
        self.assertEqual(response["Content-Type"], "text/calendar; charset=utf-8")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(
            self.events(response),
            [
                ("Mine", d("2026-11-20"), d("2026-11-21")),
                ("Internal", d("2026-12-31"), d("2027-01-01")),
            ],
        )
        calendar = Calendar.from_ical(response.content)
        event = next(iter(calendar.walk("VEVENT")))
        self.assertIn("/todos/", str(event["url"]))

    def test_a_new_link_replaces_the_old_one(self):
        old = self.link(self.ada)
        new = CalendarToken.renew(self.ada)
        self.assertNotEqual(old.token, new.token)
        self.assertEqual(self.feed(old).status_code, 404)
        self.assertEqual(self.feed(new).status_code, 200)
        self.assertEqual(self.client.get("/calendar/nonsense.ics").status_code, 404)

    def test_a_client_gets_only_what_is_visible(self):
        self.todo("Visible", "2026-11-20", assignees=[self.cleo])
        self.todo(
            "Internal", "2026-11-20", todolist=self.internal, assignees=[self.ada]
        )
        link = self.link(self.cleo)
        self.assertEqual([e[0] for e in self.events(self.feed(link))], ["Visible"])
        # Hiding the list hides its to-dos from the feed too
        ops.set_visibility(self.shared, visible=False, actor=self.ada)
        self.assertEqual(self.events(self.feed(link)), [])

    def test_losing_access(self):
        self.todo("Mine", "2026-11-20", assignees=[self.bob])
        link = self.link(self.bob)
        self.assertEqual(len(self.events(self.feed(link))), 1)
        # Gone from the limited project (the all-access one stays open to staff)
        limited = self.todo(
            "Hidden", "2026-11-20", todolist=self.limited_list, assignees=[self.bob]
        )
        self.assertEqual(len(self.events(self.feed(link))), 2)
        Membership.objects.filter(project=self.limited, user=self.bob).delete()
        self.assertEqual([e[0] for e in self.events(self.feed(link))], ["Mine"])
        self.assertTrue(Item.objects.filter(pk=limited.pk).exists())
        # Inactive people's feeds are empty (and don't reveal that)
        self.bob.is_active = False
        self.bob.save()
        self.assertEqual(self.events(self.feed(link)), [])

    def test_mentions_are_names(self):
        """Titles and the list's title show mentions as names, not the
        syntax"""
        self.shared.title = f"Shared with [@Bob](person:{self.bob.pk})"
        self.shared.save(update_fields=["title"])
        self.todo(
            f"Call [@Bob](person:{self.bob.pk})", "2026-11-20", assignees=[self.ada]
        )
        response = self.feed(self.link(self.ada))
        event = next(iter(Calendar.from_ical(response.content).walk("VEVENT")))
        self.assertEqual(str(event["summary"]), f"Call @{self.bob.get_short_name()}")
        self.assertEqual(
            str(event["description"]),
            f"{self.project} / Shared with @{self.bob.get_short_name()}",
        )


class ByProjectTest(ByDueTestCase):
    def setUp(self):
        super().setUp()
        self.doing = ops.create_group(todolist=self.shared.todolist, title="Doing")
        self.soon = ops.create_group(todolist=self.shared.todolist, title="Soon")
        self.later_list = ops.create_list(
            project=self.project, title="Later list", creator=self.ada, visible=True
        )

    def grouped(self, response):
        return [
            (
                project.name,
                [
                    (
                        todolist.title,
                        [
                            (group and group.title, [t.title for t in todos])
                            for group, todos in groups
                        ],
                    )
                    for todolist, groups in lists
                ],
            )
            for project, lists in response.context["projects"]
        ]

    def fill(self):
        self.todo("Z in list two", todolist=self.later_list)
        self.todo("Second", "2026-11-10")
        self.todo("First")
        self.todo("In soon", group=self.soon)
        self.todo("In doing", group=self.doing)
        self.todo("Elsewhere", todolist=self.other_list)
        self.todo("Internal", todolist=self.internal)
        self.todo("Secret", todolist=self.limited_list)

    def test_projects_lists_groups_and_todos(self):
        self.fill()
        self.client.force_login(self.ada)
        with at("2026-11-18 12:00"):
            response = self.client.get("/todos/?assignee=anybody&assignee=anybody")
        self.assertEqual(
            self.grouped(response),
            [
                ("Other", [("Elsewhere", [(None, ["Elsewhere"])])]),
                (
                    self.project.name,
                    [
                        (
                            "Shared",
                            [
                                (None, ["Second", "First"]),
                                ("Doing", ["In doing"]),
                                ("Soon", ["In soon"]),
                            ],
                        ),
                        ("Internal", [(None, ["Internal"])]),
                        ("Later list", [(None, ["Z in list two"])]),
                    ],
                ),
            ],
        )
        self.assertContains(response, "Second")

    def test_a_client_sees_no_internal_lists(self):
        self.fill()
        self.client.force_login(self.cleo)
        response = self.client.get("/todos/?assignee=anybody&assignee=anybody")
        self.assertEqual(
            [(p, [t for t, _g in lists]) for p, lists in self.grouped(response)],
            [(self.project.name, ["Shared", "Later list"])],
        )
        self.assertNotContains(response, "Internal")
        self.assertNotContains(response, "Elsewhere")

    def test_empty_projects_and_lists_are_left_out(self):
        self.client.force_login(self.ada)
        response = self.client.get("/todos/?assignee=anybody&assignee=anybody")
        self.assertEqual(self.grouped(response), [])
        self.assertContains(response, "Nothing to do.")

    def test_the_project_page_has_no_project_heading(self):
        self.fill()
        self.client.force_login(self.ada)
        response = self.client.get(f"/projects/{self.project.pk}/todos/")
        self.assertEqual(
            [name for name, _lists in self.grouped(response)], [self.project.name]
        )
        self.assertNotContains(response, 'class="h5 mb-2"')
        self.assertContains(response, "data-list=")
        self.assertContains(response, "data-group=")

    def test_the_grouping_is_a_query_parameter(self):
        self.fill()
        self.client.force_login(self.ada)
        # By project is the default, a bad value is the default too
        self.assertIn(
            "projects",
            self.client.get("/todos/?assignee=anybody&assignee=anybody").context,
        )
        self.assertIn(
            "sections", self.client.get("/todos/?assignee=anybody&grouping=due").context
        )
        self.assertIn(
            "projects",
            self.client.get("/todos/?assignee=anybody&grouping=project").context,
        )
        self.assertEqual(self.client.post("/todos/grouping/").status_code, 404)

    def test_the_grouping_is_a_field_of_the_filter_form(self):
        self.client.force_login(self.ada)
        response = self.client.get("/todos/?assignee=me&grouping=due")
        form = response.context["form"]
        self.assertEqual(form["grouping"].value(), "due")
        self.assertContains(response, 'name="grouping"')
        self.assertContains(response, "Group by")
        self.assertNotContains(response, 'aria-label="Grouping"')
        self.assertIn("sections", response.context)
        # An invalid value is an error and shows no to-dos
        response = self.client.get("/todos/?assignee=anybody&grouping=x")
        self.assertTrue(response.context["form"].errors)
        # The project's page too
        response = self.client.get(f"/projects/{self.project.pk}/todos/")
        self.assertContains(response, 'name="grouping"')

    def test_changing_the_grouping_writes_nothing(self):
        self.fill()
        self.client.force_login(self.ada)
        before = User.objects.filter(pk=self.ada.pk).values().get()
        self.client.get("/todos/?assignee=anybody&grouping=due")
        self.assertEqual(User.objects.filter(pk=self.ada.pk).values().get(), before)

    def test_completed_are_not_grouped(self):
        todo = self.todo("Done")
        ops.complete(todo, actor=self.ada)
        self.client.force_login(self.ada)
        response = self.client.get(
            "/todos/", {"state": "completed", "assignee": "anybody"}
        )
        self.assertIn("page", response.context)
        self.assertNotIn("projects", response.context)
        self.assertContains(response, "Done")

    def test_the_overdue_badge_stays(self):
        self.todo("Late", "2026-11-10")
        self.client.force_login(self.ada)
        with at("2026-11-18 12:00"):
            response = self.client.get("/todos/?assignee=anybody&assignee=anybody")
        self.assertContains(response, "Overdue")

    def test_the_number_of_queries_stays_the_same(self):
        self.client.force_login(self.ada)
        self.fill()
        self.client.get("/todos/?assignee=anybody&assignee=anybody")  # warm up
        with CaptureQueriesContext(connection) as few:
            self.client.get("/todos/?assignee=anybody&assignee=anybody")
        for n in range(4):
            other = project(f"Extra {n}", members=[self.ada])
            for m in range(2):
                todolist = ops.create_list(
                    project=other, title=f"List {m}", creator=self.ada
                )
                group = ops.create_group(todolist=todolist.todolist, title=f"Group {m}")
                for k in range(3):
                    self.todo(
                        f"T{n}{m}{k}", "2026-11-10", todolist=todolist, group=group
                    )
        with CaptureQueriesContext(connection) as many:
            response = self.client.get("/todos/?assignee=anybody&assignee=anybody")
        self.assertEqual(len(response.context["projects"]), 6)
        self.assertEqual(len(many), len(few))

    def test_the_api(self):
        self.fill()
        # by project is the person's choice here, "due" the other
        todos = self.api_get(self.ada)
        self.assertEqual(
            [t["title"] for t in todos],
            [
                "Elsewhere",
                "Second",
                "First",
                "In doing",
                "In soon",
                "Internal",
                "Z in list two",
            ],
        )
        first = todos[1]
        self.assertEqual(first["project_name"], self.project.name)
        self.assertEqual(first["list_title"], "Shared")
        self.assertEqual(first["list_position"], self.shared.position)
        self.assertIsNone(first["group"])
        self.assertEqual(todos[3]["group"]["title"], "Doing")
        self.assertEqual(todos[3]["group"]["position"], self.doing.position)
        by_due = self.api_get(self.ada, grouping="due")
        self.assertEqual(by_due[0]["title"], "Second")
        self.assertEqual(by_due[-1]["due_group"], "none")
        self.assertEqual(self.api_get(self.ada, grouping="x", raw=True), 422)
        # Clients only see what is visible
        self.assertEqual(
            [t["title"] for t in self.api_get(self.cleo)],
            ["Second", "First", "In doing", "In soon", "Z in list two"],
        )

    def test_api_cursor_pages_keep_the_order(self):
        self.fill()
        _token, secret = APIToken.create_for(user=self.ada, title="T", access="read")
        headers = {"authorization": f"Bearer {secret}"}
        titles, cursor = [], None
        while True:
            params = {"page_size": 2} | ({"cursor": cursor} if cursor else {})
            data = self.client.get("/api/v1/todos/", params, headers=headers).json()
            titles += [t["title"] for t in data["results"]]
            cursor = (
                data["next"] and parse_qs(urlsplit(data["next"]).query)["cursor"][0]
            )
            if not cursor:
                break
        self.assertEqual(
            titles, [t["title"] for t in self.api_get(self.ada, size=None)]
        )

    def api_get(self, user, *, raw=False, size=200, **params):
        _token, secret = APIToken.create_for(user=user, title="T", access="read")
        response = self.client.get(
            "/api/v1/todos/",
            params | ({"page_size": size} if size else {}),
            headers={"authorization": f"Bearer {secret}"},
        )
        if raw:
            return response.status_code
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["results"]


class HeaderAndResetTest(TestCase):
    """ "Reset filters" only with a filter set; "Assigned to me" in the
    header keeps the other filters"""

    def setUp(self):
        self.ada = person("Ada")
        self.client.force_login(self.ada)

    def test_reset_only_with_a_filter(self):
        self.assertNotContains(self.client.get("/todos/"), "Reset filters")
        self.assertNotContains(self.client.get("/todos/?grouping=due"), "Reset filters")
        self.assertContains(self.client.get("/todos/?state=completed"), "Reset filters")
        # Mine is the default across projects, "Anybody" a filter
        self.assertNotContains(self.client.get("/todos/?assignee=me"), "Reset filters")
        self.assertNotContains(self.client.get("/todos/?assignee="), "Reset filters")
        self.assertContains(
            self.client.get("/todos/?assignee=anybody"), "Reset filters"
        )

    def test_assigned_to_me_keeps_the_other_filters(self):
        response = self.client.get(
            "/todos/?assignee=anybody&state=completed&grouping=due&page=2"
        )
        link = response.context["mine_query"]
        self.assertEqual(
            parse_qs(link),
            {"state": ["completed"], "grouping": ["due"]},
        )
        self.assertContains(response, "Assigned to me")
        for query in ["?assignee=me", ""]:
            self.assertNotContains(self.client.get("/todos/" + query), "Assigned to me")

    def test_links_leave_out_empty_values_and_defaults(self):
        # Spelled-out defaults and empty values (a form sent without
        # JavaScript) stay out of the links the page makes (specs/ui.md)
        response = self.client.get(
            "/todos/?project=&assignee=anybody&state=completed&visible=&grouping=project"
        )
        self.assertEqual(response.context["mine_query"], "state=completed")
        self.assertEqual(
            response.context["querystring"], "assignee=anybody&state=completed"
        )
        response = self.client.get("/todos/?assignee=me&grouping=&state=")
        self.assertNotContains(response, "Assigned to me")
        self.assertFalse(response.context["filtered"])

    def test_mine_is_the_default_across_projects(self):
        bob = person("Bob")
        site = project(members=[self.ada, bob])
        todolist = ops.create_list(project=site, title="Launch", creator=self.ada)
        for title, who in [("Mine here", self.ada), ("Bobs here", bob)]:
            todo = ops.create_todo(todolist=todolist, title=title, creator=self.ada)
            ops.assign(todo, [who], actor=self.ada)
        response = self.client.get("/todos/")
        self.assertEqual(response.context["title"], "My to-dos")
        self.assertContains(response, "Mine here")
        self.assertNotContains(response, "Bobs here")
        self.assertContains(self.client.get("/todos/?assignee=anybody"), "Bobs here")
        # In a project its to-dos, anybody's
        response = self.client.get(f"/projects/{site.pk}/todos/")
        self.assertContains(response, "Bobs here")


class NobodyActiveTest(TestCase):
    def test_assigned_only_to_deactivated_people_is_nobodys(self):
        ada, gone = person("Ada"), person("Gone")
        site = project(members=[ada, gone])
        todolist = ops.create_list(project=site, title="Launch", creator=ada)
        left = ops.create_todo(todolist=todolist, title="Left behind", creator=ada)
        ops.assign(left, [gone], actor=ada)
        ops.create_todo(todolist=todolist, title="Unassigned", creator=ada)
        taken = ops.create_todo(todolist=todolist, title="Taken", creator=ada)
        ops.assign(taken, [ada, gone], actor=ada)
        User.objects.filter(pk=gone.pk).update(is_active=False)
        found = {t.title for t in due.todos(ada, assignee="nobody")}
        self.assertEqual(found, {"Left behind", "Unassigned"})


class ClientBadgeByListTest(TestCase):
    """The project's to-dos by list mark the list as visible to clients, not
    each of its to-dos, which share the list's visibility (the user,
    2026-11-28: "This could be calmer. Mark only the list as client
    visible"); by due date the rows keep their badges, lists mixed"""

    def test_the_list_not_its_rows(self):
        ada = person("Ada")
        p = project(members=[ada])
        shared = ops.create_list(project=p, title="Shared", creator=ada, visible=True)
        internal = ops.create_list(project=p, title="Internal", creator=ada)
        for todolist in (shared, internal):
            for title in ("One", "Two"):
                ops.create_todo(
                    todolist=todolist, title=f"{todolist} {title}", creator=ada
                )
        self.client.force_login(ada)
        url = f"/projects/{p.pk}/todos/"
        html = self.client.get(url).content.decode()
        self.assertEqual(html.count("wb-client-badge"), 1)
        heading = html[html.index(f'data-list="{shared.pk}"') :].split("</h3>", 1)[0]
        self.assertIn("wb-client-badge", heading)
        html = self.client.get(url + "?grouping=due").content.decode()
        self.assertEqual(html.count("wb-client-badge"), 2)
