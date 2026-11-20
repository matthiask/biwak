"""The projects page (specs/projects-overview.md): favorites, ordering,
cards, the stored activity times and what clients see of them"""

import datetime as dt
from io import StringIO
from zoneinfo import ZoneInfo

import time_machine
from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from biwak.accounts.models import APIToken, User
from biwak.activity.models import Action, Event
from biwak.activity.operations import record
from biwak.bookmarks import operations as bookmarks
from biwak.items import operations as ops
from biwak.projects import operations as project_ops
from biwak.projects.models import Membership, Project
from biwak.test_utils import person, project


def at(text):
    return time_machine.travel(
        dt.datetime.fromisoformat(text).replace(tzinfo=ZoneInfo("Europe/Zurich")),
        tick=False,
    )


def when(text):
    return dt.datetime.fromisoformat(text).replace(tzinfo=ZoneInfo("Europe/Zurich"))


def reload(p):
    return Project.objects.get(pk=p.pk)


class OverviewTestCase(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)

    def names(self, user, **params):
        self.client.force_login(user)
        response = self.client.get(reverse("projects"), params)
        self.assertEqual(response.status_code, 200)
        return [p.name for p in response.context["projects"]], response

    def api(self, path, user=None, **params):
        _token, secret = APIToken.create_for(
            user=user or self.ada, title="T", access="write"
        )
        return self.client.get(
            f"/api/v1/{path}", params, headers={"authorization": f"Bearer {secret}"}
        )


class ActivityTimesTest(OverviewTestCase):
    """record() keeps the two columns"""

    def setUp(self):
        super().setUp()
        self.project = project("Website", members=[self.ada, self.cleo])
        self.shared = ops.create_list(
            project=self.project, title="Shared", creator=self.ada, visible=True
        )
        self.internal = ops.create_list(
            project=self.project, title="Internal", creator=self.ada
        )
        Project.objects.update(last_activity_at=None, last_client_activity_at=None)

    def test_visible_item_event_counts_for_both(self):
        with at("2026-11-20 10:00"):
            ops.create_todo(todolist=self.shared, title="A", creator=self.ada)
        p = reload(self.project)
        self.assertEqual(p.last_activity_at, when("2026-11-20 10:00"))
        self.assertEqual(p.last_client_activity_at, when("2026-11-20 10:00"))

    def test_internal_item_event_counts_for_staff_only(self):
        with at("2026-11-20 10:00"):
            ops.create_todo(todolist=self.shared, title="A", creator=self.ada)
        with at("2026-11-20 12:00"):
            ops.create_todo(todolist=self.internal, title="B", creator=self.ada)
        p = reload(self.project)
        self.assertEqual(p.last_activity_at, when("2026-11-20 12:00"))
        self.assertEqual(p.last_client_activity_at, when("2026-11-20 10:00"))

    def test_project_event_counts_for_staff_only(self):
        with at("2026-11-20 10:00"):
            project_ops.add_member(self.project, self.bob, actor=self.ada)
        p = reload(self.project)
        self.assertEqual(p.last_activity_at, when("2026-11-20 10:00"))
        self.assertIsNone(p.last_client_activity_at)

    def test_never_goes_back(self):
        with at("2026-11-20 10:00"):
            record(actor=self.ada, action=Action.EDITED_PROJECT, project=self.project)
        with at("2026-11-19 10:00"):
            record(actor=self.ada, action=Action.EDITED_PROJECT, project=self.project)
        self.assertEqual(
            reload(self.project).last_activity_at, when("2026-11-20 10:00")
        )

    def test_one_update_per_event(self):
        item = ops.create_todo(todolist=self.shared, title="A", creator=self.ada)
        with CaptureQueriesContext(connection) as queries:
            record(
                actor=self.ada,
                action=Action.EDITED,
                project=self.project,
                item=item,
            )
        updates = [
            q for q in queries if q["sql"].startswith('UPDATE "projects_project"')
        ]
        self.assertEqual(len(updates), 1)

    def test_changing_the_times_is_not_audited(self):
        from biwak.audit.models import LoggedAction

        LoggedAction.objects.all().delete()
        record(actor=self.ada, action=Action.EDITED_PROJECT, project=self.project)
        self.assertEqual(LoggedAction.objects.count(), 0)


class RecomputeTest(OverviewTestCase):
    def setUp(self):
        super().setUp()
        self.project = project("Website", members=[self.ada, self.cleo])
        self.shared = ops.create_list(
            project=self.project, title="Shared", creator=self.ada, visible=True
        )
        self.internal = ops.create_list(
            project=self.project, title="Internal", creator=self.ada
        )
        Event.objects.all().delete()

    def event(self, text, item=None, action=Action.EDITED):
        e = record(actor=self.ada, action=action, project=self.project, item=item)
        Event.objects.filter(pk=e.pk).update(created_at=when(text))

    def test_recompute_from_events(self):
        todo = ops.create_todo(todolist=self.shared, title="A", creator=self.ada)
        Event.objects.all().delete()
        self.event("2026-11-01 10:00", todo)
        self.event("2026-11-02 10:00", self.internal)
        self.event("2026-11-03 10:00")  # a project event
        Project.objects.update(last_activity_at=None, last_client_activity_at=None)
        self.assertEqual(project_ops.recompute_activity(), 1)
        p = reload(self.project)
        self.assertEqual(p.last_activity_at, when("2026-11-03 10:00"))
        self.assertEqual(p.last_client_activity_at, when("2026-11-01 10:00"))
        # Nothing to change the second time
        self.assertEqual(project_ops.recompute_activity(), 0)

    def test_drift_after_switching_to_internal(self):
        todo = ops.create_todo(todolist=self.shared, title="A", creator=self.ada)
        Event.objects.all().delete()
        self.event("2026-11-01 10:00", todo)
        self.event("2026-11-02 10:00", self.shared)
        project_ops.recompute_activity()
        self.assertEqual(
            reload(self.project).last_client_activity_at, when("2026-11-02 10:00")
        )
        ops.set_visibility(self.shared, visible=False, actor=self.ada)
        # Counted for clients when it happened, until the nightly job
        self.assertEqual(
            reload(self.project).last_client_activity_at, when("2026-11-02 10:00")
        )
        project_ops.recompute_activity()
        self.assertIsNone(reload(self.project).last_client_activity_at)

    def test_trashed_items_dont_count(self):
        todo = ops.create_todo(todolist=self.shared, title="A", creator=self.ada)
        Event.objects.all().delete()
        self.event("2026-11-05 10:00", todo)
        self.event("2026-11-01 10:00", self.shared)
        ops.trash(todo, actor=self.ada)
        Event.objects.filter(action=Action.TRASHED).delete()
        project_ops.recompute_activity()
        p = reload(self.project)
        self.assertEqual(p.last_activity_at, when("2026-11-01 10:00"))
        self.assertEqual(p.last_client_activity_at, when("2026-11-01 10:00"))

    def test_projects_without_events(self):
        project_ops.recompute_activity()
        p = reload(self.project)
        self.assertIsNone(p.last_activity_at)
        self.assertIsNone(p.last_client_activity_at)

    def test_fairy_tasks(self):
        self.event("2026-11-01 10:00", self.shared)
        Project.objects.update(last_activity_at=None, last_client_activity_at=None)
        call_command("fairy_tasks", stdout=StringIO())
        p = reload(self.project)
        self.assertEqual(p.last_activity_at, when("2026-11-01 10:00"))
        self.assertEqual(p.last_client_activity_at, when("2026-11-01 10:00"))


class MigrationFillTest(OverviewTestCase):
    def test_migration_uses_the_nightly_sql(self):
        """The data migration runs the same statement as fairy_tasks"""
        from importlib import import_module

        migration = import_module("biwak.projects.migrations.0002_project_activity")
        self.assertIs(
            migration.RECOMPUTE_ACTIVITY_SQL, project_ops.RECOMPUTE_ACTIVITY_SQL
        )
        self.assertIn(
            project_ops.RECOMPUTE_ACTIVITY_SQL,
            [getattr(op, "sql", None) for op in migration.Migration.operations],
        )


class OrderTest(OverviewTestCase):
    def setUp(self):
        super().setUp()
        members = [self.ada, self.cleo]
        self.alpha = project("Alpha", members=members)
        self.beta = project("beta", members=members)
        self.gamma = project("Gamma", members=members)
        self.quiet = project("Delta", members=members)
        Project.objects.update(last_activity_at=None, last_client_activity_at=None)
        for p, day in [(self.alpha, 1), (self.beta, 3), (self.gamma, 2)]:
            Project.objects.filter(pk=p.pk).update(
                last_activity_at=when(f"2026-11-0{day} 10:00"),
                last_client_activity_at=when(f"2026-11-0{day} 10:00"),
            )

    def test_default_is_by_activity_without_events_last(self):
        self.assertEqual(self.ada.project_order, "activity")
        names, _ = self.names(self.ada)
        self.assertEqual(names, ["beta", "Gamma", "Alpha", "Delta"])

    def test_by_name(self):
        project_ops.set_project_order(self.ada, "name")
        names, _ = self.names(self.ada)
        self.assertEqual(names, ["Alpha", "beta", "Delta", "Gamma"])

    def test_favorites_first_in_both_orders(self):
        bookmarks.add_bookmark(self.ada, project=self.alpha)
        bookmarks.add_bookmark(self.ada, project=self.quiet)
        names, _response = self.names(self.ada)
        self.assertEqual(names, ["Alpha", "Delta", "beta", "Gamma"])
        project_ops.set_project_order(self.ada, "name")
        names, _ = self.names(self.ada)
        self.assertEqual(names, ["Alpha", "Delta", "beta", "Gamma"])
        bookmarks.add_bookmark(self.ada, project=self.gamma)
        names, _ = self.names(self.ada)
        self.assertEqual(names, ["Alpha", "Delta", "Gamma", "beta"])

    def test_bookmarks_are_per_person(self):
        bookmarks.add_bookmark(self.cleo, project=self.quiet)
        names, _ = self.names(self.ada)
        self.assertEqual(names[0], "beta")
        names, _ = self.names(self.cleo)
        self.assertEqual(names[0], "Delta")

    def test_the_switch(self):
        self.client.force_login(self.ada)
        response = self.client.post(reverse("project_order"), {"order": "name"})
        self.assertRedirects(response, reverse("projects"))
        self.ada.refresh_from_db()
        self.assertEqual(self.ada.project_order, "name")
        # Stays: it's the person's setting, not the request's
        names, _ = self.names(self.ada)
        self.assertEqual(names[0], "Alpha")
        response = self.client.post(reverse("project_order"), {"order": "activity"})
        self.ada.refresh_from_db()
        self.assertEqual(self.ada.project_order, "activity")
        self.assertEqual(
            self.client.post(reverse("project_order"), {"order": "x"}).status_code, 400
        )
        # Not saved on GET
        self.assertEqual(
            self.client.get(reverse("project_order"), {"order": "name"}).status_code,
            405,
        )
        self.ada.refresh_from_db()
        self.assertEqual(self.ada.project_order, "activity")

    def test_clients_can_switch_too(self):
        self.client.force_login(self.cleo)
        self.client.post(reverse("project_order"), {"order": "name"})
        self.cleo.refresh_from_db()
        self.assertEqual(self.cleo.project_order, "name")

    def test_login_required(self):
        response = self.client.post(reverse("project_order"), {"order": "name"})
        self.assertNotEqual(response.status_code, 200)
        self.assertEqual(User.objects.filter(project_order="name").count(), 0)

    def test_archived_stay_alphabetical_without_cards(self):
        for p in (self.gamma, self.alpha):
            project_ops.archive_project(p, actor=self.ada)
        names, response = self.names(self.ada, archived=1)
        self.assertEqual(names, ["Alpha", "Gamma"])
        self.assertNotContains(response, "wb-project-card")
        self.assertNotContains(response, reverse("project_order"))


class ClientColumnTest(OverviewTestCase):
    """Internal activity never changes what a client sees"""

    def setUp(self):
        super().setUp()
        self.old = project("Old", members=[self.ada, self.cleo])
        self.busy = project("Busy", members=[self.ada, self.cleo])
        self.shared = {}
        self.internal = {}
        for p in (self.old, self.busy):
            self.shared[p] = ops.create_list(
                project=p, title="Shared", creator=self.ada, visible=True
            )
            self.internal[p] = ops.create_list(
                project=p, title="Internal", creator=self.ada
            )
        Event.objects.all().delete()
        Project.objects.update(last_activity_at=None, last_client_activity_at=None)
        with at("2026-11-10 10:00"):
            ops.create_todo(
                todolist=self.shared[self.busy], title="Seen", creator=self.ada
            )
        with at("2026-11-12 10:00"):
            ops.create_todo(
                todolist=self.shared[self.old], title="Seen too", creator=self.ada
            )

    def state(self, user):
        names, response = self.names(user)
        times = {p.name: p.activity for p in response.context["projects"]}
        api = {
            p["name"]: p["last_activity_at"] for p in self.api("projects/", user).json()
        }
        api_names = [p["name"] for p in self.api("projects/", user).json()]
        self.assertEqual(names, api_names)
        counts = {
            p.name: (p.open_count, p.overdue_count)
            for p in response.context["projects"]
        }
        return names, times, api, counts

    def test_internal_activity_changes_nothing_for_a_client(self):
        with at("2026-11-11 10:00"):
            ops.create_todo(
                todolist=self.shared[self.busy],
                title="Mine",
                creator=self.ada,
                assignees=[self.cleo],
                due_on=dt.date(2026, 11, 1),
            )
        before = self.state(self.cleo)
        self.assertEqual(before[0], ["Old", "Busy"])
        self.assertEqual(before[3]["Busy"], (1, 1))
        with at("2026-11-15 10:00"):
            internal = ops.create_todo(
                todolist=self.internal[self.busy],
                title="Secret",
                creator=self.ada,
                assignees=[self.ada],
                due_on=dt.date(2026, 11, 1),
            )
            ops.complete(internal, actor=self.ada)
            ops.set_visibility(self.internal[self.busy], visible=False, actor=self.ada)
            project_ops.add_member(self.busy, self.bob, actor=self.ada)
            record(actor=self.ada, action=Action.EDITED_PROJECT, project=self.busy)
        self.assertEqual(self.state(self.cleo), before)
        # Also after the nightly recomputation
        project_ops.recompute_activity()
        self.assertEqual(self.state(self.cleo), before)
        # Staff do see it
        names, times, api, _ = self.state(self.ada)
        self.assertEqual(names[0], "Busy")
        self.assertEqual(times["Busy"], when("2026-11-15 10:00"))
        self.assertEqual(api["Busy"], "2026-11-15T09:00:00Z")

    def test_visible_activity_moves_it_for_a_client(self):
        with at("2026-11-16 10:00"):
            ops.create_todo(
                todolist=self.shared[self.busy], title="News", creator=self.ada
            )
        names, times, _api, _ = self.state(self.cleo)
        self.assertEqual(names, ["Busy", "Old"])
        self.assertEqual(times["Busy"], when("2026-11-16 10:00"))

    def test_counts_are_of_what_the_client_sees(self):
        with at("2026-11-15 10:00"):
            for title, lst in [
                ("Seen", self.shared[self.busy]),
                ("Hidden", self.internal[self.busy]),
            ]:
                ops.create_todo(
                    todolist=lst,
                    title=title,
                    creator=self.ada,
                    assignees=[self.ada, self.cleo]
                    if lst.is_client_visible
                    else [self.ada],
                    due_on=dt.date(2026, 11, 1),
                )
        with at("2026-11-20 10:00"):
            _, _, _, counts = self.state(self.cleo)
            self.assertEqual(counts["Busy"], (1, 1))
            _, _, _, counts = self.state(self.ada)
            self.assertEqual(counts["Busy"], (2, 2))


class CardsTest(OverviewTestCase):
    def setUp(self):
        super().setUp()
        self.project = project("Website", members=[self.ada, self.cleo])
        self.project.description = "First line **bold**\n\nSecond line"
        self.project.save()
        self.shared = ops.create_list(
            project=self.project, title="Shared", creator=self.ada, visible=True
        )
        Event.objects.all().delete()
        Project.objects.update(last_activity_at=None, last_client_activity_at=None)

    def test_card_content(self):
        with at("2026-11-20 08:00"):
            ops.create_todo(
                todolist=self.shared,
                title="Late",
                creator=self.ada,
                assignees=[self.ada],
                due_on=dt.date(2026, 11, 1),
            )
            ops.create_todo(
                todolist=self.shared,
                title="Fine",
                creator=self.ada,
                assignees=[self.ada],
            )
            ops.create_todo(todolist=self.shared, title="Not mine", creator=self.ada)
        with at("2026-11-20 11:00"):
            _, response = self.names(self.ada)
        self.assertContains(response, "First line bold")
        self.assertNotContains(response, "Second line")
        self.assertContains(response, "3\xa0hours ago")
        self.assertContains(response, "2 open")
        self.assertContains(response, "1 overdue")
        self.assertContains(response, 'title="Bookmark"')
        self.assertContains(response, "wb-client-badge")

    def test_no_counts_when_zero(self):
        _, response = self.names(self.ada)
        self.assertNotContains(response, " open")
        self.assertNotContains(response, "overdue")

    def test_no_activity_no_time(self):
        Project.objects.update(last_activity_at=None, last_client_activity_at=None)
        _, response = self.names(self.ada)
        self.assertNotContains(response, "ago")

    def test_clients_badge_staff_only(self):
        _, response = self.names(self.cleo)
        self.assertNotContains(response, "wb-client-badge")
        self.assertNotContains(response, "Has client members")
        self.assertContains(response, "Website")
        # Without client members no badge for staff either
        Membership.objects.filter(user=self.cleo).delete()
        _, response = self.names(self.ada)
        self.assertNotContains(response, "wb-client-badge")

    def test_lock_for_limited(self):
        project("Secret", members=[self.ada], all_access=False)
        _, response = self.names(self.ada)
        self.assertContains(response, "Limited: members only")

    def test_admin_section_stays(self):
        admin = person("Root", is_admin=True)
        project("Secret", members=[self.ada], all_access=False)
        names, response = self.names(admin)
        self.assertNotIn("Secret", names)
        self.assertContains(response, "not a member of")

    def test_bookmark_from_a_card(self):
        self.client.force_login(self.ada)
        url = reverse("project_bookmark", args=[self.project.pk])
        response = self.client.post(
            url, {"bookmark": "1", "card": "1"}, headers={"HX-Request": "true"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "bi-bookmark-fill")
        self.assertNotContains(response, "<html")
        self.assertTrue(bookmarks.is_bookmarked(self.ada, project=self.project))
        response = self.client.post(url, {"card": "1"}, headers={"HX-Request": "true"})
        self.assertNotContains(response, "bi-bookmark-fill")
        self.assertFalse(bookmarks.is_bookmarked(self.ada, project=self.project))
        # The page shows the filled icon
        bookmarks.add_bookmark(self.ada, project=self.project)
        _, response = self.names(self.ada)
        self.assertContains(response, "bi-bookmark-fill")

    def test_cant_bookmark_what_you_cant_open(self):
        secret = project("Secret", members=[self.ada], all_access=False)
        self.client.force_login(self.cleo)
        response = self.client.post(
            reverse("project_bookmark", args=[secret.pk]),
            {"bookmark": "1", "card": "1"},
            headers={"HX-Request": "true"},
        )
        self.assertEqual(response.status_code, 404)

    def test_limited_projects_stay_hidden_from_non_members(self):
        project("Secret", members=[self.bob], all_access=False)
        names, _ = self.names(self.ada)
        self.assertEqual(names, ["Website"])
        names, _ = self.names(self.cleo)
        self.assertEqual(names, ["Website"])


class QueryCountTest(OverviewTestCase):
    def build(self, n):
        for i in range(n):
            p = project(f"P{i:03}", members=[self.ada, self.cleo])
            lst = ops.create_list(project=p, title="L", creator=self.ada, visible=True)
            ops.create_todo(
                todolist=lst,
                title="T",
                creator=self.ada,
                assignees=[self.ada, self.cleo],
                due_on=dt.date(2026, 1, 1),
            )
            if i % 3 == 0:
                bookmarks.add_bookmark(self.ada, project=p)

    def count(self, user):
        self.client.force_login(user)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse("projects"))
        self.assertEqual(response.status_code, 200)
        return len(queries), response

    def test_fixed_number_of_queries(self):
        self.build(5)
        small = {u: self.count(u)[0] for u in (self.ada, self.cleo)}
        self.build(195)
        for user in (self.ada, self.cleo):
            number, response = self.count(user)
            self.assertEqual(len(response.context["projects"]), 200)
            self.assertEqual(number, small[user])
            self.assertLessEqual(number, 12)
        self.client.force_login(self.ada)
        with self.assertNumQueries(small[self.ada]):
            self.client.get(reverse("projects"))

    def test_api(self):
        self.build(5)
        self.api("projects/")
        with CaptureQueriesContext(connection) as small:
            self.api("projects/")
        self.build(45)
        with CaptureQueriesContext(connection) as large:
            response = self.api("projects/")
        self.assertEqual(len(response.json()), 50)
        self.assertEqual(len(large), len(small))


class ApiTest(OverviewTestCase):
    def setUp(self):
        super().setUp()
        members = [self.ada, self.cleo]
        self.alpha = project("Alpha", members=members)
        self.beta = project("Beta", members=members)
        self.gamma = project("Gamma", members=members)
        Project.objects.update(last_activity_at=None, last_client_activity_at=None)
        Project.objects.filter(pk=self.alpha.pk).update(
            last_activity_at=when("2026-11-01 10:00")
        )
        Project.objects.filter(pk=self.beta.pk).update(
            last_activity_at=when("2026-11-02 10:00"),
            last_client_activity_at=when("2026-11-01 09:00"),
        )
        bookmarks.add_bookmark(self.ada, project=self.gamma)

    def names(self, user=None, **params):
        return [p["name"] for p in self.api("projects/", user, **params).json()]

    def test_orders(self):
        self.assertEqual(self.names(), ["Gamma", "Beta", "Alpha"])
        self.assertEqual(self.names(order="name"), ["Gamma", "Alpha", "Beta"])
        project_ops.set_project_order(self.ada, "name")
        self.assertEqual(self.names(), ["Gamma", "Alpha", "Beta"])
        self.assertEqual(self.names(order="activity"), ["Gamma", "Beta", "Alpha"])
        self.assertEqual(self.api("projects/", order="x").status_code, 422)

    def test_fields(self):
        data = {p["name"]: p for p in self.api("projects/").json()}
        self.assertTrue(data["Gamma"]["is_bookmarked"])
        self.assertFalse(data["Beta"]["is_bookmarked"])
        self.assertIsNone(data["Gamma"]["last_activity_at"])
        self.assertTrue(data["Beta"]["is_member"])
        self.assertTrue(data["Beta"]["last_activity_at"].startswith("2026-11-02"))
        # Also on a single project and in the bookmarks
        one = self.api(f"projects/{self.gamma.pk}/").json()
        self.assertTrue(one["is_bookmarked"])
        self.assertIn("last_activity_at", one)
        self.assertEqual(
            self.api("bookmarks/").json()[0]["project"]["is_bookmarked"], True
        )

    def test_clients_get_their_column(self):
        data = {p["name"]: p for p in self.api("projects/", self.cleo).json()}
        self.assertTrue(data["Beta"]["last_activity_at"].startswith("2026-11-01"))
        self.assertIsNone(data["Alpha"]["last_activity_at"])
        self.assertEqual(self.names(self.cleo), ["Beta", "Alpha", "Gamma"])
        self.assertFalse(data["Gamma"]["is_bookmarked"])

    def test_archived(self):
        project_ops.archive_project(self.alpha, actor=self.ada)
        project_ops.archive_project(self.beta, actor=self.ada)
        self.assertEqual(self.names(archived="true"), ["Alpha", "Beta"])
        self.assertEqual(self.names(), ["Gamma"])
