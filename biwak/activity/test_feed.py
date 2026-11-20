import datetime as dt
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.utils import timezone

from biwak import cursors
from biwak.activity import feed
from biwak.activity.models import Action, Event
from biwak.activity.operations import record
from biwak.items import operations as ops
from biwak.test_utils import person, project


NOW = dt.datetime(2026, 11, 20, 12, 0, tzinfo=dt.UTC)


def event_at(actor, action, item, when, **data):
    """An event at a time (``record()`` uses the current time)"""
    event = record(actor=actor, action=action, project=item.project, item=item, **data)
    Event.objects.filter(pk=event.pk).update(created_at=when)
    return Event.objects.get(pk=event.pk)


class FeedBase(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.bob, self.cleo])
        self.internal = ops.create_list(
            project=self.project, title="Internal", creator=self.ada
        )
        self.shared = ops.create_list(
            project=self.project, title="Shared", creator=self.ada, visible=True
        )
        self.secret = ops.create_todo(
            todolist=self.internal, title="Secret", creator=self.ada
        )
        self.todo = ops.create_todo(
            todolist=self.shared, title="Open point", creator=self.ada
        )
        Event.objects.all().delete()

    def todos(self, todolist, count):
        todos = [
            ops.create_todo(todolist=todolist, title=f"Todo {n}", creator=self.ada)
            for n in range(count)
        ]
        Event.objects.all().delete()
        return todos


class MergeTest(FeedBase):
    def entries(self):
        events = list(feed.feed_events(self.ada))
        feed.attach(events)
        return feed.merge(events)

    def test_consecutive_events_merge(self):
        for n, todo in enumerate(self.todos(self.shared, 5)):
            event_at(
                self.ada,
                Action.COMPLETED,
                todo,
                NOW - dt.timedelta(minutes=10 * n),
            )
        (entry,) = self.entries()
        self.assertEqual(entry.count, 5)
        self.assertEqual(entry.what, "5 to-dos")
        self.assertEqual(entry.where, "Shared")

    def test_not_across_lists_people_actions_or_hours(self):
        a, b = self.todos(self.shared, 2)
        (c,) = self.todos(self.internal, 1)
        event_at(self.ada, Action.COMPLETED, a, NOW)
        # Another list
        event_at(self.ada, Action.COMPLETED, c, NOW - dt.timedelta(minutes=1))
        event_at(self.ada, Action.COMPLETED, b, NOW - dt.timedelta(minutes=2))
        self.assertEqual([e.count for e in self.entries()], [1, 1, 1])
        Event.objects.all().delete()
        # Another person
        event_at(self.ada, Action.COMPLETED, a, NOW)
        event_at(self.bob, Action.COMPLETED, b, NOW - dt.timedelta(minutes=1))
        self.assertEqual([e.count for e in self.entries()], [1, 1])
        Event.objects.all().delete()
        # Another action
        event_at(self.ada, Action.COMPLETED, a, NOW)
        event_at(self.ada, Action.REOPENED, b, NOW - dt.timedelta(minutes=1))
        self.assertEqual([e.count for e in self.entries()], [1, 1])
        Event.objects.all().delete()
        # More than an hour apart, but chains of events within an hour merge
        event_at(self.ada, Action.COMPLETED, a, NOW)
        event_at(self.ada, Action.COMPLETED, b, NOW - dt.timedelta(minutes=61))
        self.assertEqual([e.count for e in self.entries()], [1, 1])
        event_at(self.ada, Action.COMPLETED, a, NOW - dt.timedelta(minutes=100))
        self.assertEqual([e.count for e in self.entries()], [1, 2])

    def test_not_across_midnight(self):
        a, b = self.todos(self.shared, 2)
        zurich = ZoneInfo("Europe/Zurich")
        event_at(
            self.ada,
            Action.COMPLETED,
            a,
            dt.datetime(2026, 11, 20, 0, 10, tzinfo=zurich),
        )
        event_at(
            self.ada,
            Action.COMPLETED,
            b,
            dt.datetime(2026, 11, 19, 23, 50, tzinfo=zurich),
        )
        entries = self.entries()
        self.assertEqual([e.count for e in entries], [1, 1])
        days = feed.by_day(entries)
        self.assertEqual(
            [day for day, _entries in days],
            [dt.date(2026, 11, 20), dt.date(2026, 11, 19)],
        )

    def test_day_grouping_uses_the_local_time_zone(self):
        a, b = self.todos(self.shared, 2)
        # 23:30 UTC is already the next day in Zurich, 22:30 UTC isn't
        event_at(
            self.ada, Action.EDITED, a, dt.datetime(2026, 1, 5, 23, 30, tzinfo=dt.UTC)
        )
        event_at(
            self.bob, Action.EDITED, b, dt.datetime(2026, 1, 5, 22, 30, tzinfo=dt.UTC)
        )
        days = feed.by_day(self.entries())
        self.assertEqual(
            [(day, len(entries)) for day, entries in days],
            [(dt.date(2026, 1, 6), 1), (dt.date(2026, 1, 5), 1)],
        )

    def test_project_events_merge_per_project(self):
        for _n in range(2):
            record(actor=self.ada, action=Action.ADDED, project=self.project, name="X")
        (entry,) = self.entries()
        self.assertEqual(entry.what, "2 items")
        self.assertEqual(entry.where, "Website")


class FeedViewsTest(FeedBase):
    def test_staff_feed(self):
        record(
            actor=self.ada,
            action=Action.COMPLETED,
            project=self.project,
            item=self.secret,
        )
        record(
            actor=self.bob,
            action=Action.COMMENTED,
            project=self.project,
            item=self.todo,
        )
        self.client.force_login(self.ada)
        response = self.client.get("/feed/")
        self.assertContains(response, "Secret")
        self.assertContains(response, "Open point")
        self.assertContains(response, "Website")
        self.assertContains(response, "Today")
        self.assertContains(response, "Bob")

    def test_client_feed_has_no_internal_events(self):
        record(
            actor=self.ada,
            action=Action.COMPLETED,
            project=self.project,
            item=self.secret,
        )
        record(
            actor=self.ada,
            action=Action.EDITED,
            project=self.project,
            item=self.internal,
        )
        record(actor=self.ada, action=Action.JOINED, project=self.project)
        record(
            actor=self.ada,
            action=Action.COMPLETED,
            project=self.project,
            item=self.todo,
        )
        self.client.force_login(self.cleo)
        for url in ["/feed/", f"/projects/{self.project.pk}/feed/"]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertContains(response, "Open point")
                self.assertNotContains(response, "Secret")
                self.assertNotContains(response, "Internal")
                self.assertNotContains(response, "joined the project")
        # The person's feed too
        response = self.client.get(f"/people/{self.ada.pk}/feed/")
        self.assertContains(response, "Open point")
        self.assertNotContains(response, "Secret")

    def test_client_doesnt_see_where_to_do_moved(self):
        record(
            actor=self.ada,
            action=Action.MOVED,
            project=self.project,
            item=self.todo,
            to="Internal plans",
        )
        self.client.force_login(self.ada)
        self.assertContains(self.client.get("/feed/"), "Internal plans")
        self.client.force_login(self.cleo)
        self.assertNotContains(self.client.get("/feed/"), "Internal plans")

    def test_trashed_items_are_hidden(self):
        record(
            actor=self.ada, action=Action.EDITED, project=self.project, item=self.todo
        )
        ops.trash(self.todo, actor=self.ada)
        self.client.force_login(self.ada)
        response = self.client.get("/feed/")
        self.assertNotContains(response, "Open point")
        # Deleted for good: gone
        record(
            actor=self.ada, action=Action.EDITED, project=self.project, item=self.secret
        )
        self.assertContains(self.client.get("/feed/"), "Secret")
        self.secret.delete()
        self.assertNotContains(self.client.get("/feed/"), "Secret")

    def test_limited_projects_stay_hidden(self):
        other = project("Hidden", members=[self.bob], all_access=False)
        item = ops.create_list(project=other, title="Plans", creator=self.bob)
        record(actor=self.bob, action=Action.EDITED, project=other, item=item)
        self.client.force_login(self.ada)
        self.assertNotContains(self.client.get("/feed/"), "Plans")
        self.assertEqual(
            self.client.get(f"/projects/{other.pk}/feed/").status_code, 404
        )
        self.client.force_login(self.bob)
        self.assertContains(self.client.get("/feed/"), "Plans")

    def test_filters(self):
        record(
            actor=self.ada,
            action=Action.COMPLETED,
            project=self.project,
            item=self.todo,
        )
        record(
            actor=self.bob, action=Action.EDITED, project=self.project, item=self.secret
        )
        record(
            actor=self.bob, action=Action.EDITED, project=self.project, item=self.shared
        )
        self.client.force_login(self.ada)

        def titles(**params):
            response = self.client.get("/feed/", params)
            return {t for t in ["Open point", "Secret", "Shared"] if t in response.text}

        # The titles of the lists are in the "in Shared" of the to-dos too, so
        # look at the entries only
        self.assertEqual(titles(kind="list"), {"Shared"})
        self.assertEqual(titles(person=self.bob.pk), {"Secret", "Shared"})
        self.assertEqual(titles(action="completed"), {"Open point"})
        self.assertEqual(titles(clients="on"), {"Open point", "Shared"})
        self.assertEqual(titles(kind="todo", person=self.bob.pk), {"Secret"})
        # Garbage is ignored
        self.assertEqual(self.client.get("/feed/?kind=nope&person=x").status_code, 200)

    def test_project_and_person_feeds(self):
        other = project("Other", members=[self.ada, self.bob])
        item = ops.create_list(project=other, title="Elsewhere", creator=self.bob)
        record(actor=self.bob, action=Action.EDITED, project=other, item=item)
        record(
            actor=self.ada, action=Action.EDITED, project=self.project, item=self.todo
        )
        self.client.force_login(self.ada)
        response = self.client.get(f"/projects/{self.project.pk}/feed/")
        self.assertContains(response, "Open point")
        self.assertNotContains(response, "Elsewhere")
        response = self.client.get(f"/people/{self.bob.pk}/feed/")
        self.assertContains(response, "Elsewhere")
        self.assertNotContains(response, "Open point")
        self.assertContains(response, "Activity of Bob Example")
        # Somebody the viewer shares no project with
        stranger = person("Dora")
        self.assertEqual(
            self.client.get(f"/people/{stranger.pk}/feed/").status_code, 404
        )

    def test_pagination(self):
        for n in range(feed.PAGE_SIZE + 5):
            # Several events at the very same time
            event_at(
                self.ada,
                Action.EDITED,
                self.todo,
                NOW - dt.timedelta(minutes=n // 3 * 90),
            )
        self.client.force_login(self.ada)
        response = self.client.get("/feed/")
        self.assertContains(response, "Older")
        seen = response.text.count('<li class="mb-2">')
        older = response.context["older"]
        self.assertIn("before=", older)
        response = self.client.get(older)
        self.assertNotContains(response, "Older")
        # Entries are merged, so count the events in the entries
        total = sum(
            entry.count
            for page in [self.client.get("/feed/"), response]
            for _day, _label, entries in page.context["days"]
            for entry in entries
        )
        self.assertEqual(total, feed.PAGE_SIZE + 5)
        self.assertTrue(seen)
        self.assertEqual(self.client.get("/feed/?before=x").status_code, 400)

    def test_cursor_out_of_range(self):
        self.client.force_login(self.ada)
        response = self.client.get("/feed/", {"before": "9" * 30 + ",1"})
        self.assertEqual(response.status_code, 400)

    def test_cursor_roundtrip(self):
        event = event_at(
            self.ada, Action.EDITED, self.todo, NOW + dt.timedelta(microseconds=7)
        )
        self.assertEqual(
            cursors.decode(feed.cursor_for(event)), (event.created_at, event.pk)
        )

    def test_login_required(self):
        self.assertEqual(self.client.get("/feed/").status_code, 302)

    def test_project_page_links_to_the_feed(self):
        self.client.force_login(self.ada)
        self.assertContains(
            self.client.get(self.project.get_absolute_url()),
            f"/projects/{self.project.pk}/feed/",
        )

    def test_merged_entry_is_expandable(self):
        for todo in self.todos(self.shared, 3):
            record(
                actor=self.ada, action=Action.COMPLETED, project=self.project, item=todo
            )
        self.client.force_login(self.ada)
        response = self.client.get("/feed/")
        self.assertIn("completed 3 to-dos in Shared", " ".join(response.text.split()))
        self.assertContains(response, "<details>")
        self.assertContains(response, "Todo 2")
        self.assertEqual(timezone.localdate(), response.context["days"][0][0])
