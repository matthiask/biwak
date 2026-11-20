import datetime as dt
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import time_machine
from django.test import TestCase
from icalendar import Calendar

from biwak.accounts.models import APIToken, CalendarToken
from biwak.items import due, operations as ops
from biwak.items.models import Item
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
            ("2026-11-23", "later"),
        ]:
            with self.subTest(due_on=due_on):
                self.assertEqual(
                    due.group_of(d(due_on) if due_on else None, today), group
                )

    def test_a_sunday_has_no_rest_of_the_week(self):
        today = d("2026-11-22")
        self.assertEqual(due.group_of(d("2026-11-22"), today), "today")
        self.assertEqual(due.group_of(d("2026-11-23"), today), "later")
        # And a Monday has the whole week
        self.assertEqual(due.group_of(d("2026-11-29"), d("2026-11-23")), "this_week")
        self.assertEqual(due.group_of(d("2026-11-30"), d("2026-11-23")), "later")


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

    def todo(self, title, due=None, *, todolist=None, assignees=()):
        return ops.create_todo(
            todolist=todolist or self.shared,
            title=title,
            creator=self.ada,
            due_on=d(due) if due else None,
            assignees=assignees,
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
            sections = self.sections(self.client.get("/todos/"))
        self.assertEqual(
            sections,
            {
                "overdue": ["late"],
                "today": ["now"],
                "this_week": ["soon"],
                "later": ["far"],
                "none": ["whenever"],
            },
        )
        with at("2026-11-17 22:30", "UTC"):  # 23:30 on the 17th
            sections = self.sections(self.client.get("/todos/"))
        self.assertEqual(sections["today"], ["late"])
        # Sunday evening: the next day is later
        with at("2026-11-22 23:30"):
            sections = self.sections(self.client.get("/todos/"))
        self.assertEqual(sections["later"], ["far"])
        self.assertEqual(sections["overdue"], ["late", "now"])
        self.assertEqual(sections["today"], ["soon"])

    def test_across_projects_and_access(self):
        self.todo("Visible")
        self.todo("Elsewhere", todolist=self.other_list)
        self.todo("Secret", todolist=self.limited_list)
        self.client.force_login(self.ada)
        response = self.client.get("/todos/")
        self.assertContains(response, "Visible")
        self.assertContains(response, "Elsewhere")
        self.assertNotContains(response, "Secret")
        self.assertContains(response, "wb-client-badge")
        self.assertContains(response, "My to-dos")

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
        self.assertContains(self.client.get("/todos/"), "Visible")
        # No filter by visibility for clients, and no way to see others' projects
        self.assertNotContains(self.client.get("/todos/"), 'name="visible"')
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
            response = self.client.get("/todos/", params)
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
        self.assertEqual(found(list=self.internal.pk), ["Internal"])
        self.assertEqual(found(visible="yes"), ["Bobs", "Mine", "Nobodys"])
        self.assertEqual(found(visible="no"), ["Internal", "Other"])
        response = self.client.get("/todos/", {"assignee": "me"})
        self.assertContains(response, '<h1 class="wb-title">My to-dos</h1>')
        # Nonsense: an error, no to-dos
        for params in [
            {"assignee": "x"},
            {"project": "x"},
            {"list": self.limited_list.pk},
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
        response = self.client.get("/todos/?state=completed")
        self.assertEqual(len(response.context["page"]), 50)
        self.assertEqual(response.context["page"][0].title, "Done 54")
        self.assertNotContains(response, ">Open</a>")
        self.assertContains(response, "state=completed&page=2")
        response = self.client.get("/todos/?state=completed&page=2")
        self.assertEqual(
            [t.title for t in response.context["page"]],
            [f"Done {n:02}" for n in range(4, -1, -1)],
        )

    def test_archived_projects_and_lists_are_out_of_the_way(self):
        self.todo("Open")
        self.todo("Old", todolist=self.other_list)
        self.client.force_login(self.ada)
        ops.archive(self.other_list, actor=self.ada)
        self.assertNotContains(self.client.get("/todos/"), "Old")
        ops.unarchive(self.other_list, actor=self.ada)
        self.assertContains(self.client.get("/todos/"), "Old")
        self.other.archived_at = dt.datetime.now(dt.UTC)
        self.other.save()
        self.assertNotContains(self.client.get("/todos/"), "Old")

    def test_completing_from_the_list(self):
        item = self.todo("Do it", "2026-11-18")
        self.client.force_login(self.ada)
        response = self.client.get("/todos/?assignee=nobody")
        self.assertContains(response, 'value="/todos/?assignee=nobody"')
        response = self.client.post(
            f"/todos/{item.pk}/toggle/", {"next": "/todos/?assignee=nobody"}
        )
        self.assertRedirects(response, "/todos/?assignee=nobody")
        item.todo.refresh_from_db()
        self.assertIsNotNone(item.todo.completed_at)
        self.assertNotContains(self.client.get("/todos/"), "Do it")
        self.assertContains(self.client.get("/todos/?state=completed"), "Do it")
        # Not off to other sites
        response = self.client.post(
            f"/todos/{item.pk}/toggle/", {"next": "https://example.com/"}
        )
        self.assertRedirects(response, self.shared.get_absolute_url())

    def test_a_client_completes_a_visible_todo_from_the_list(self):
        item = self.todo("Visible")
        secret = self.todo("Secret", todolist=self.internal)
        self.client.force_login(self.cleo)
        self.assertEqual(
            self.client.post(f"/todos/{secret.pk}/toggle/").status_code, 404
        )
        self.client.post(f"/todos/{item.pk}/toggle/", {"next": "/todos/"})
        item.todo.refresh_from_db()
        self.assertEqual(item.todo.completed_by, self.cleo)


class APITest(ByDueTestCase):
    def api(self, user):
        _token, secret = APIToken.create_for(user=user, title="T", access="read")
        return {"authorization": f"Bearer {secret}"}

    def get(self, user, **params):
        return self.client.get("/api/v1/todos/", params, headers=self.api(user))

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
            self.assertEqual(
                self.titles(self.get(self.ada, list_id=self.internal.pk)), ["Internal"]
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
        self.assertEqual(
            self.get(self.ada, list_id=self.limited_list.pk).status_code, 404
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
            {"list_id": self.internal.pk},
            {"assignee": "nobody"},
        ]:
            with self.subTest(params=params):
                response = self.get(self.cleo, **params)
                self.assertNotIn("Internal", str(response.content))
        self.assertEqual(self.get(self.cleo, list_id=self.internal.pk).status_code, 404)
        self.assertEqual(self.get(self.cleo, project_id=self.other.pk).status_code, 404)
        self.assertEqual(self.titles(self.get(self.cleo, assignee="me")), ["Visible"])
        self.assertEqual(self.client.get("/api/v1/todos/").status_code, 401)


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
