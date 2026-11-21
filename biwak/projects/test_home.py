"""Home at ``/`` (specs/dashboard.md): every section for staff and for
clients, the unread marks, and the projects page at ``/projects/``"""

import datetime as dt
import re

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from biwak import schedules
from biwak.activity import lantern, mentions
from biwak.activity.models import Event, Notification
from biwak.activity.operations import subscribe
from biwak.bookmarks import operations as bookmark_ops
from biwak.checkins.support import CheckinTestCase
from biwak.items import operations as ops
from biwak.items.models import Todo
from biwak.projects import operations as project_ops
from biwak.projects.models import Project
from biwak.test_utils import person, project


class HomeTestCase(TestCase):
    def setUp(self):
        self.today = schedules.today()
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

    def day(self, days):
        return self.today + dt.timedelta(days=days)

    def todo(self, title, *, days=None, assignees=(), internal=False, creator=None):
        return ops.create_todo(
            todolist=self.internal if internal else self.shared,
            title=title,
            creator=creator or self.ada,
            due_on=None if days is None else self.day(days),
            assignees=assignees,
        )

    def get(self, user, url="/", **params):
        self.client.force_login(user)
        return self.client.get(url, params)

    def section(self, user, name):
        """The HTML of a section of Home, empty if it's not there"""
        content = self.page(user).content.decode()
        found = re.search(
            rf'<section[^>]*data-home="{name}".*?</section>', content, re.DOTALL
        )
        return found[0] if found else ""

    def page(self, user):
        response = self.get(user)
        self.assertEqual(response.status_code, 200)
        return response


class RoutingTest(HomeTestCase):
    def test_home_is_the_root_and_the_projects_page_moved(self):
        self.assertEqual(reverse("dashboard"), "/")
        self.assertEqual(reverse("projects"), "/projects/")
        response = self.get(self.ada, "/projects/")
        self.assertContains(response, "wb-project-grid")
        self.assertContains(response, "<h1>Projects</h1>")
        response = self.page(self.ada)
        self.assertContains(response, '<h1 class="wb-title">Home</h1>')
        self.assertNotContains(response, "wb-project-grid")

    def test_the_old_archived_address_redirects(self):
        response = self.get(self.ada, "/", archived=1)
        self.assertRedirects(response, "/projects/?archived=1")

    def test_the_brand_links_home_and_the_navigation_the_projects(self):
        content = self.page(self.ada).content.decode()
        self.assertIn('<a class="navbar-brand" href="/"', content)
        self.assertIn('href="/projects/"', content)

    def test_login_is_required(self):
        self.client.logout()
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])


class DueTest(HomeTestCase):
    def test_my_open_to_dos_overdue_or_due_within_a_week(self):
        for title, days in [
            ("Overdue job", -2),
            ("Today job", 0),
            ("Friday job", 3),
            ("Edge job", 7),
            ("Far job", 8),
            ("Undated job", None),
        ]:
            self.todo(title, days=days, assignees=[self.ada])
        self.todo("Bobs job", days=0, assignees=[self.bob])
        done = self.todo("Done job", days=0, assignees=[self.ada])
        ops.complete(done, actor=self.ada)
        response = self.page(self.ada)
        titles = [t.title for _k, _l, ts in response.context["sections"] for t in ts]
        self.assertEqual(titles, ["Overdue job", "Today job", "Friday job", "Edge job"])
        self.assertEqual(
            [key for key, _l, _t in response.context["sections"]][:2],
            ["overdue", "today"],
        )
        self.assertContains(response, "Overdue")
        labels = {key: label for key, label, _t in response.context["sections"]}
        # The to-do due in 7 days is always after this week
        self.assertEqual(labels["next_week"], "Next week")
        self.assertContains(response, "Next week")
        self.assertNotContains(response, ">Later<")
        # More to-dos than shown: the link has the number
        self.assertContains(response, "All 6 to-dos")

    def test_at_most_ten_the_most_urgent_first(self):
        for n in range(12):
            self.todo(f"Job {n}", days=n % 5, assignees=[self.ada])
        response = self.page(self.ada)
        found = [t for _k, _l, ts in response.context["sections"] for t in ts]
        self.assertEqual(len(found), 10)
        self.assertEqual(
            [t.todo.due_on for t in found], sorted(t.todo.due_on for t in found)
        )
        self.assertContains(response, "All 12 to-dos")

    def test_nothing_due_says_so_and_links_to_all(self):
        self.todo("Undated job", assignees=[self.ada])
        response = self.page(self.ada)
        self.assertContains(response, "Nothing due this week.")
        self.assertContains(response, 'href="/todos/?assignee=me&amp;grouping=due"')
        self.assertContains(response, "All 1 to-dos")
        self.assertContains(self.page(self.bob), "All my to-dos")

    def test_a_client_sees_visible_to_dos_only(self):
        self.todo("Public job", days=1, assignees=[self.cleo])
        # Assigned to the client but internal: never shown
        hidden = self.todo("Hidden job", days=1, internal=True, assignees=[self.ada])
        Todo.assignees.through.objects.create(todo_id=hidden.pk, user=self.cleo)
        response = self.page(self.cleo)
        self.assertContains(response, "Public job")
        self.assertNotContains(response, "Hidden job")

    def test_archived_projects_and_lists_are_left_out(self):
        self.todo("Archived list job", days=0, assignees=[self.ada])
        other = project("Old", members=[self.ada])
        other_list = ops.create_list(project=other, title="L", creator=self.ada)
        ops.create_todo(
            todolist=other_list,
            title="Old project job",
            creator=self.ada,
            due_on=self.today,
            assignees=[self.ada],
        )
        project_ops.archive_project(other, actor=self.ada)
        ops.archive(self.shared, actor=self.ada)
        response = self.page(self.ada)
        self.assertEqual(response.context["sections"], [])
        self.assertNotIn("Old project job", self.section(self.ada, "due"))

    def test_to_dos_of_limited_projects_follow_access(self):
        secret = project("Secret", members=[self.bob], all_access=False)
        todolist = ops.create_list(project=secret, title="S", creator=self.bob)
        item = ops.create_todo(
            todolist=todolist,
            title="Secret job",
            creator=self.bob,
            due_on=self.today,
            assignees=[self.bob],
        )
        Todo.assignees.through.objects.create(todo_id=item.pk, user=self.ada)
        self.assertNotContains(self.page(self.ada), "Secret job")
        self.assertContains(self.page(self.bob), "Secret job")

    def test_completing_goes_back_to_home(self):
        item = self.todo("Pack", days=0, assignees=[self.ada])
        self.client.force_login(self.ada)
        content = self.client.get("/").content.decode()
        self.assertIn(f'action="/todos/{item.pk}/toggle/"', content)
        response = self.client.post(f"/todos/{item.pk}/toggle/", {"next": "/"})
        self.assertRedirects(response, "/")
        self.assertNotIn("Pack", self.section(self.ada, "due"))


class WaitingTest(HomeTestCase):
    def test_staff_see_the_to_dos_they_assigned_to_others(self):
        self.todo("Bobs job", days=1, assignees=[self.bob])
        self.todo("Own job", days=1, assignees=[self.ada])
        self.todo("Far job", days=20, assignees=[self.bob])
        self.todo("Undated job", assignees=[self.bob])
        response = self.page(self.ada)
        found = [t.title for _k, _l, ts in response.context["waiting"] for t in ts]
        self.assertEqual(found, ["Bobs job"])
        self.assertContains(response, "Waiting on others")
        self.assertContains(
            response, 'href="/todos/?assignee=&amp;assigned_by=me&amp;grouping=due"'
        )

    def test_not_the_ones_assigned_to_me_too(self):
        self.todo("Shared job", days=1, assignees=[self.ada, self.bob])
        self.assertEqual(self.page(self.ada).context["waiting"], [])

    def test_left_out_without_any(self):
        self.assertNotContains(self.page(self.ada), "Waiting on others")

    def test_the_other_person_did_not_assign_it(self):
        self.todo("Bobs job", days=1, assignees=[self.bob])
        self.assertNotContains(self.page(self.bob), "Waiting on others")

    def test_clients_never_get_the_section(self):
        self.todo("Visible job", days=1, assignees=[self.ada], creator=self.cleo)
        self.assertEqual(self.page(self.cleo).context["waiting"], [])
        self.assertNotContains(self.page(self.cleo), "Waiting on others")

    def test_internal_to_dos_stay_with_staff(self):
        self.todo("Internal job", days=1, internal=True, assignees=[self.bob])
        self.assertContains(self.page(self.ada), "Internal job")


class CheckinsTest(CheckinTestCase):
    def setUp(self):
        super().setUp()
        self.shared = self.question(
            "Shared question", visible=True, people=[self.ada, self.cleo]
        )
        self.run_at("2027-03-22 09:00")

    def home(self, user):
        self.client.force_login(user)
        return self.client.get("/")

    def test_the_questions_waiting_with_their_project(self):
        response = self.home(self.ada)
        self.assertContains(response, "Waiting for your answer")
        self.assertContains(response, "How are you?")
        self.assertContains(response, "Shared question")
        self.assertContains(response, "Website")

    def test_answered_ones_go_away_and_the_section_with_them(self):
        from biwak.checkins import operations as checkin_ops

        checkin_ops.answer(self.item, user=self.ada, content="Fine")
        checkin_ops.answer(self.shared, user=self.ada, content="Fine")
        self.assertNotContains(self.home(self.ada), "Waiting for your answer")

    def test_clients_get_their_visible_questions_only(self):
        response = self.home(self.cleo)
        self.assertContains(response, "Shared question")
        self.assertNotContains(response, "How are you?")

    def test_nobody_asked_nothing_shown(self):
        self.assertNotContains(self.home(self.bob), "Shared question")

    def test_archived_projects_are_left_out(self):
        project_ops.archive_project(self.project, actor=self.ada)
        self.assertNotContains(self.home(self.ada), "Waiting for your answer")


class UpdatesTest(HomeTestCase):
    def days(self, user):
        return self.page(user).context["days"]

    def titles(self, user):
        events = [
            event
            for _d, _l, entries in self.days(user)
            for entry in entries
            for event in entry.events
        ]
        return {event.data.get("title") for event in events}

    def test_everything_in_bookmarked_projects(self):
        todo = self.todo("Pack")
        bookmark_ops.add_bookmark(self.bob, project=self.project)
        ops.complete(todo, actor=self.ada)
        self.assertIn("Pack", self.titles(self.bob))
        self.assertContains(self.page(self.bob), "Recent updates")
        self.assertContains(self.page(self.bob), 'href="/feed/"')

    def test_without_bookmarks_only_what_concerns_me(self):
        self.todo("Plain job")
        self.todo("Bobs job", assignees=[self.bob])
        ops.add_comment(
            self.todo("Chat"), author=self.ada, content=mentions.syntax(self.bob)
        )
        found = self.titles(self.bob)
        self.assertIn("Bobs job", found)
        self.assertIn("Chat", found)
        self.assertNotIn("Plain job", found)

    def test_the_two_sources_together_and_each_event_once(self):
        other = project("Other", members=[self.ada, self.bob])
        other_list = ops.create_list(project=other, title="L", creator=self.ada)
        ops.create_todo(todolist=other_list, title="Elsewhere", creator=self.ada)
        ops.create_todo(
            todolist=other_list,
            title="Assigned elsewhere",
            creator=self.ada,
            assignees=[self.bob],
        )
        self.todo("Bookmarked job", assignees=[self.bob])
        bookmark_ops.add_bookmark(self.bob, project=self.project)
        found = self.titles(self.bob)
        self.assertTrue({"Assigned elsewhere", "Bookmarked job"} <= found)
        self.assertNotIn("Elsewhere", found)
        events = [
            e
            for _d, _l, entries in self.days(self.bob)
            for entry in entries
            for e in entry.events
        ]
        self.assertEqual(len(events), len({e.pk for e in events}))

    def test_my_own_actions_show_too(self):
        bookmark_ops.add_bookmark(self.ada, project=self.project)
        self.todo("My own job")
        self.assertIn("My own job", self.titles(self.ada))

    def test_only_the_last_week(self):
        self.todo("Old job", assignees=[self.bob])
        Event.objects.update(created_at=timezone.now() - dt.timedelta(days=8))
        self.assertEqual(self.days(self.bob), [])
        self.assertNotContains(self.page(self.bob), "Recent updates")

    def test_at_most_ten_entries(self):
        bookmark_ops.add_bookmark(self.bob, project=self.project)
        for n in range(15):
            # Different people and actions would merge: separate lists do not
            todolist = ops.create_list(
                project=self.project, title=f"List {n}", creator=self.ada, visible=True
            )
            ops.create_todo(todolist=todolist, title=f"Job {n}", creator=self.ada)
        entries = [e for _d, _l, es in self.days(self.bob) for e in es]
        self.assertEqual(len(entries), 10)

    def test_empty_is_left_out(self):
        self.assertNotContains(self.page(self.bob), "Recent updates")

    def test_clients_see_what_the_feed_shows_them(self):
        self.todo("Public job", assignees=[self.cleo])
        self.todo("Internal job", internal=True)
        bookmark_ops.add_bookmark(self.cleo, project=self.project)
        found = self.titles(self.cleo)
        self.assertIn("Public job", found)
        self.assertNotIn("Internal job", found)
        self.assertNotContains(self.page(self.cleo), "Internal job")

    def test_a_client_mentioned_in_an_internal_item_learns_nothing(self):
        item = self.todo("Internal job", internal=True)
        event = Event.objects.get(item=item, action="created")
        event.data["mentioned"] = [self.cleo.pk]
        event.save()
        self.assertNotContains(self.page(self.cleo), "Internal job")

    def test_archived_projects_are_left_out(self):
        bookmark_ops.add_bookmark(self.bob, project=self.project)
        self.todo("Pack", assignees=[self.bob])
        project_ops.archive_project(self.project, actor=self.ada)
        self.assertEqual(self.days(self.bob), [])

    def test_limited_projects_without_access_show_nothing(self):
        secret = project("Secret", members=[self.bob], all_access=False)
        todolist = ops.create_list(project=secret, title="S", creator=self.bob)
        ops.create_todo(todolist=todolist, title="Secret job", creator=self.bob)
        bookmark_ops.add_bookmark(self.bob, project=secret)
        self.assertContains(self.page(self.bob), "Secret job")
        # Ada was never a member: her bookmark of it can't exist, and
        # nothing mentions her
        self.assertNotContains(self.page(self.ada), "Secret job")


class ProjectsTest(HomeTestCase):
    def cards(self, user):
        return [p.name for p in self.page(user).context["projects"]]

    def test_bookmarked_projects_newest_bookmark_first(self):
        a = project("Alpha", members=[self.ada])
        b = project("Beta", members=[self.ada])
        project("Gamma", members=[self.ada])
        bookmark_ops.add_bookmark(self.ada, project=a)
        bookmark_ops.add_bookmark(self.ada, project=b)
        response = self.page(self.ada)
        self.assertEqual(self.cards(self.ada), ["Beta", "Alpha"])
        self.assertNotContains(response, "Bookmark projects to keep them here.")
        self.assertContains(response, 'href="/projects/"')

    def test_counts_of_my_to_dos_are_on_the_cards(self):
        bookmark_ops.add_bookmark(self.ada, project=self.project)
        self.todo("A", days=-1, assignees=[self.ada])
        self.todo("B", assignees=[self.ada])
        response = self.page(self.ada)
        self.assertContains(response, "2 open")
        self.assertContains(response, "1 overdue")

    def test_without_bookmarks_six_active_projects_with_a_hint(self):
        for n in range(8):
            project(f"P{n}", members=[self.ada])
        response = self.page(self.ada)
        self.assertEqual(len(response.context["projects"]), 6)
        self.assertContains(response, "Bookmark projects to keep them here.")

    def test_without_bookmarks_only_projects_I_am_a_member_of(self):
        project("Not mine", members=[self.bob])
        self.assertEqual(self.cards(self.ada), ["Website"])

    def test_archived_projects_are_left_out(self):
        other = project("Old", members=[self.ada])
        bookmark_ops.add_bookmark(self.ada, project=other)
        project_ops.archive_project(other, actor=self.ada)
        self.assertNotIn("Old", self.cards(self.ada))

    def test_a_new_person_without_projects(self):
        newcomer = person("Dora")
        response = self.page(newcomer)
        self.assertContains(response, "You're not in a project yet.")
        self.assertNotContains(response, "Bookmark projects to keep them here.")
        self.assertNotContains(response, "Waiting on others")
        self.assertContains(response, "Nothing due this week.")
        # Own staff may create one
        self.assertContains(response, "New project")

    def test_a_new_client_cannot_create_projects(self):
        newcomer = person("Dora", client=True)
        response = self.page(newcomer)
        self.assertContains(response, "You're not in a project yet.")
        self.assertNotContains(response, "New project")

    def test_a_client_with_one_project(self):
        self.assertEqual(self.cards(self.cleo), ["Website"])

    def test_a_client_never_sees_projects_without_access(self):
        project("Other", members=[self.ada])
        self.assertEqual(self.cards(self.cleo), ["Website"])

    def test_a_partner_sees_only_their_projects(self):
        from biwak.test_utils import partner

        pia = partner("Pia")
        project("Joint", members=[self.ada, pia])
        self.assertEqual(self.cards(pia), ["Joint"])


class BookmarksTest(HomeTestCase):
    def test_bookmarked_items_newest_first_at_most_five(self):
        items = [self.todo(f"Job {n}") for n in range(7)]
        for item in items:
            bookmark_ops.add_bookmark(self.bob, item=item)
        bookmark_ops.add_bookmark(self.bob, project=self.project)
        response = self.page(self.bob)
        found = [b.item.title for b in response.context["bookmarks"]]
        self.assertEqual(found, [f"Job {n}" for n in range(6, 1, -1)])
        self.assertIn('href="/bookmarks/"', self.section(self.bob, "bookmarks"))

    def test_none_left_out(self):
        bookmark_ops.add_bookmark(self.bob, project=self.project)
        self.assertEqual(self.section(self.bob, "bookmarks"), "")

    def test_what_I_cant_see_anymore_is_hidden(self):
        item = self.todo("Secret", internal=True)
        bookmark_ops.add_bookmark(self.cleo, item=item)
        self.assertEqual(self.page(self.cleo).context["bookmarks"], [])

    def test_archived_projects_are_left_out(self):
        item = self.todo("Pack")
        bookmark_ops.add_bookmark(self.bob, item=item)
        project_ops.archive_project(self.project, actor=self.ada)
        self.assertEqual(self.page(self.bob).context["bookmarks"], [])

    def test_a_client_sees_their_visible_ones(self):
        item = self.todo("Pack")
        bookmark_ops.add_bookmark(self.cleo, item=item)
        self.assertContains(self.page(self.cleo), "Pack")


class LinksTest(HomeTestCase):
    def test_staff(self):
        links = self.section(self.ada, "links")
        self.assertNotIn("New project", links)
        for text in [
            "To-dos I assigned",
            "Search",
            "Subscribe to your to-dos in a calendar",
            "Notification settings",
            "API tokens and the CLI",
        ]:
            self.assertIn(text, links)

    def test_clients(self):
        links = self.section(self.cleo, "links")
        self.assertIn("Subscribe to your to-dos in a calendar", links)
        self.assertIn("Notification settings", links)
        for text in ["New project", "To-dos I assigned", "API tokens"]:
            self.assertNotIn(text, links)

    def test_partners_cannot_create_projects(self):
        from biwak.test_utils import partner

        pia = partner("Pia")
        project("Joint", members=[self.ada, pia])
        self.assertNotContains(self.page(pia), "New project")


class UnreadTest(HomeTestCase):
    def setUp(self):
        super().setUp()
        self.item = self.todo("Pack", days=0, assignees=[self.bob])
        subscribe(self.bob, self.item)
        with self.captureOnCommitCallbacks(execute=True):
            ops.add_comment(self.item, author=self.ada, content="Where is it?")
        self.notification = Notification.objects.filter(
            user=self.bob, event__item=self.item, read_at__isnull=True
        ).first()

    def test_a_row_with_unread_notifications_is_marked(self):
        self.assertIsNotNone(self.notification)
        response = self.page(self.bob)
        self.assertContains(response, "wb-lantern-unread")
        self.assertContains(
            response, f'data-lantern-read="/lantern/{self.notification.pk}/"'
        )

    def test_rows_without_are_plain(self):
        lantern.read(self.bob, item=self.item)
        response = self.page(self.bob)
        self.assertContains(response, "Pack")
        self.assertNotContains(response, "wb-lantern-unread")
        self.assertNotContains(response, "data-lantern-read")

    def test_loading_reads_nothing(self):
        self.page(self.bob)
        self.assertTrue(
            Notification.objects.filter(user=self.bob, read_at__isnull=True).exists()
        )

    def test_following_the_link_reads_it_in_the_lantern_too(self):
        self.client.force_login(self.bob)
        self.client.post(
            f"/lantern/{self.notification.pk}/", headers={"hx-request": "true"}
        )
        self.assertEqual(lantern.unread_count(self.bob), 0)
        self.assertNotContains(self.client.get("/"), "wb-lantern-unread")

    def test_reading_in_the_lantern_removes_the_mark_and_unread_brings_it_back(self):
        self.client.force_login(self.bob)
        self.client.post("/lantern/read/", {"item": self.item.pk})
        self.assertNotContains(self.client.get("/"), "wb-lantern-unread")
        self.client.post("/lantern/unread/", {"item": self.item.pk})
        self.assertContains(self.client.get("/"), "wb-lantern-unread")

    def test_marking_unread_keeps_it_out_of_the_mail(self):
        from django.core import mail

        from biwak.activity.mails import send_mails

        self.client.force_login(self.bob)
        self.client.post(f"/lantern/{self.notification.pk}/")
        self.client.post("/lantern/unread/", {"item": self.item.pk})
        mail.outbox.clear()
        send_mails(now=timezone.now() + dt.timedelta(days=2))
        self.assertEqual(mail.outbox, [])

    def test_the_mark_shows_in_the_row_the_update_and_the_bookmark(self):
        bookmark_ops.add_bookmark(self.bob, item=self.item)
        bookmark_ops.add_bookmark(self.bob, project=self.project)
        response = self.page(self.bob)
        # The to-do's row, its update and its bookmark
        self.assertGreaterEqual(response.content.decode().count("wb-lantern-unread"), 3)

    def test_a_client_gets_marks_by_the_visibility_rules(self):
        public = self.todo("Public", days=0, assignees=[self.cleo])
        subscribe(self.cleo, public)
        with self.captureOnCommitCallbacks(execute=True):
            ops.add_comment(public, author=self.ada, content="Hi")
            ops.add_comment(self.item, author=self.ada, content="Internal chat")
        response = self.page(self.cleo)
        self.assertContains(response, "wb-lantern-unread")
        self.assertNotContains(response, "Internal chat")
        self.assertNotContains(response, f"/todos/{self.item.pk}/")


class QueriesTest(HomeTestCase):
    def count(self, user):
        self.client.force_login(user)
        with CaptureQueriesContext(connection) as queries:
            self.assertEqual(self.client.get("/").status_code, 200)
        return len(queries)

    def fill(self, n):
        for number in range(n):
            other = project(f"Project {number}", members=[self.ada, self.bob])
            todolist = ops.create_list(project=other, title="L", creator=self.ada)
            item = ops.create_todo(
                todolist=todolist,
                title=f"Job {number}",
                creator=self.ada,
                due_on=self.day(number % 7),
                assignees=[self.ada if number % 2 else self.bob],
            )
            bookmark_ops.add_bookmark(self.ada, project=other)
            bookmark_ops.add_bookmark(self.ada, item=item)
            ops.add_comment(item, author=self.bob, content="Hi")

    def test_a_fixed_number_of_queries_with_many_projects(self):
        self.fill(3)
        few = self.count(self.ada)
        self.fill(30)
        self.assertEqual(Project.objects.count(), 34)  # Not none
        self.assertEqual(self.count(self.ada), few)
        self.assertEqual(self.count(self.bob), self.count(self.bob))

    def test_the_same_for_a_client(self):
        self.fill(2)
        few = self.count(self.cleo)
        self.fill(20)
        self.assertEqual(self.count(self.cleo), few)
