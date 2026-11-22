import datetime as dt
import re
from zoneinfo import ZoneInfo

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from biwak import cursors
from biwak.accounts.models import APIToken
from biwak.activity import feed
from biwak.activity.mails import describe
from biwak.activity.models import Action, Event
from biwak.activity.operations import record
from biwak.items import operations as ops
from biwak.items.models import Item
from biwak.projects.operations import archive_project
from biwak.test_utils import person, project


NOW = dt.datetime(2026, 11, 20, 12, 0, tzinfo=dt.UTC)


def event_at(actor, action, item, when, **data):
    """An event at a time (``record()`` uses the current time)"""
    event = record(actor=actor, action=action, project=item.project, item=item, **data)
    Event.objects.filter(pk=event.pk).update(created_at=when)
    return Event.objects.get(pk=event.pk)


def squash(response):
    """The page's text with whitespace collapsed"""
    return " ".join(response.content.decode().split())


def page_text(response):
    """The text of the page's main part, without tags"""
    html = response.content.decode().split("<main", 1)[1].split("</main>")[0]
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


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


class ArchivedProjectTest(FeedBase):
    def test_archived_projects_are_out_of_the_feed(self):
        ops.create_todo(todolist=self.shared, title="Zebra crossing", creator=self.ada)
        archive_project(self.project, actor=self.ada)
        self.assertFalse(feed.feed_events(self.ada).exists())
        # A project's own feed stays readable
        self.assertTrue(feed.feed_events(self.ada, project=self.project).exists())


class MergeTest(FeedBase):
    def entries(self):
        events = list(feed.feed_events(self.ada))
        feed.attach(events, self.ada)
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


class ConversationTest(FeedBase):
    def comment(self, author, minutes, item=None, text="Hm"):
        comment = ops.add_comment(item or self.todo, author=author, content=text)
        Event.objects.filter(data__comment=comment.pk).update(
            created_at=NOW - dt.timedelta(minutes=minutes)
        )
        return comment

    def entries(self, user=None):
        user = user or self.ada
        events = list(feed.feed_events(user))
        feed.attach(events, user)
        return feed.merge(events)

    def test_comments_on_one_item_by_anyone_make_a_conversation(self):
        self.comment(self.ada, 30, text="First")
        self.comment(self.bob, 20, text="Second")
        self.comment(self.ada, 10, text="Third")
        (entry,) = self.entries()
        self.assertTrue(entry.is_conversation)
        self.assertEqual(entry.item, self.todo)
        self.assertEqual(
            [e.excerpt for e in entry.comments], ["First", "Second", "Third"]
        )

    def test_other_events_in_between_dont_break_it_up(self):
        self.comment(self.ada, 40, text="First")
        event_at(self.bob, Action.COMPLETED, self.todo, NOW - dt.timedelta(minutes=30))
        self.comment(self.bob, 20, text="Second")
        reaction = event_at(
            self.ada, Action.REACTED, self.todo, NOW - dt.timedelta(minutes=10)
        )
        entries = self.entries()
        # The conversation sits where its newest comment is: below the reaction
        self.assertEqual([e.is_conversation for e in entries], [False, True, False])
        self.assertEqual(entries[0].latest.pk, reaction.pk)
        self.assertEqual(entries[1].count, 2)
        self.assertEqual(entries[2].latest.action, Action.COMPLETED)

    def test_not_across_items_hours_or_midnight(self):
        other = ops.create_todo(todolist=self.shared, title="Other", creator=self.ada)
        Event.objects.all().delete()
        self.comment(self.ada, 5, text="One")
        self.comment(self.bob, 6, other, text="Two")
        # A chain of comments within an hour of each other
        self.comment(self.bob, 60, text="Three")
        self.comment(self.bob, 119, text="Four")
        self.comment(self.bob, 181, text="Five")
        counts = [(e.is_conversation, e.count) for e in self.entries()]
        # "One" and "Two" are on different items but the same list and merge
        # as before; "Three" and "Four" are within an hour of the one before
        # (and of One), "Five" isn't
        self.assertEqual(counts, [(True, 3), (False, 1), (False, 1)])
        Event.objects.all().delete()
        zurich = ZoneInfo("Europe/Zurich")
        midnight = dt.datetime(2026, 11, 21, 0, 0, tzinfo=zurich)
        for n, when in enumerate([midnight, midnight - dt.timedelta(minutes=10)]):
            comment = ops.add_comment(self.todo, author=self.ada, content=str(n))
            Event.objects.filter(data__comment=comment.pk).update(created_at=when)
        self.assertEqual([e.is_conversation for e in self.entries()], [False, False])

    def test_the_page(self):
        self.comment(self.ada, 30, text="Can we do Monday?")
        self.comment(self.bob, 20, text="Monday works")
        self.client.force_login(self.ada)
        response = self.client.get("/feed/")
        self.assertIn("Conversation on Open point", page_text(response))
        self.assertContains(response, "Can we do Monday?")
        self.assertContains(response, "Monday works")
        self.assertNotContains(response, "commented on")
        self.assertNotContains(response, "<details>")
        self.assertLess(
            response.text.index("Can we do Monday?"),
            response.text.index("Monday works"),
        )

    def test_clients_see_the_comments_they_may_see(self):
        # Comments while the list was internal are no events for clients
        self.comment(self.ada, 50, self.secret, text="Internal one")
        self.comment(self.ada, 40, self.secret, text="Internal two")
        ops.set_visibility(self.internal, visible=True, actor=self.ada)
        self.comment(self.ada, 30, self.secret, text="Now visible")
        self.comment(self.cleo, 20, self.secret, text="Thanks")
        self.comment(self.ada, 10, self.secret, text="Welcome")
        self.client.force_login(self.cleo)
        response = self.client.get("/feed/")
        self.assertIn("Conversation on Secret", page_text(response))
        self.assertNotContains(response, "Internal one")
        self.assertNotContains(response, "Internal two")
        for text in ["Now visible", "Thanks", "Welcome"]:
            self.assertContains(response, text)
        # Staff see all five in one conversation
        self.client.force_login(self.ada)
        days = self.client.get("/feed/").context["days"]
        entries = [e for _day, _label, es in days for e in es]
        (entry,) = [e for e in entries if e.is_conversation]
        self.assertEqual(entry.count, 5)
        # And a client sees nothing of a list that's internal again
        ops.set_visibility(self.internal, visible=False, actor=self.ada)
        self.client.force_login(self.cleo)
        self.assertNotIn("Conversation on Secret", page_text(self.client.get("/feed/")))

    def test_a_fixed_number_of_queries(self):
        def queries():
            self.client.force_login(self.ada)
            with CaptureQueriesContext(connection) as captured:
                self.client.get("/feed/")
            return len(captured)

        self.comment(self.ada, 100, text="Start")
        self.comment(self.bob, 90, text="Reply")
        few = queries()
        for n in range(8):
            self.comment(self.bob, 80 - n, text=f"More {n}")
        other = ops.create_todo(todolist=self.shared, title="Other", creator=self.ada)
        for n in range(4):
            self.comment(self.ada, 20 - n, other, text=f"Elsewhere {n}")
        self.assertEqual(queries(), few)


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

    def test_mentions_in_where_and_to(self):
        """Lists' titles with mentions show them as @Name, not the syntax"""
        mention = f"[@Bob Example](person:{self.bob.pk})"
        todolist = ops.create_list(
            project=self.project, title=f"For {mention}", creator=self.ada
        )
        # Merged: "2 to-dos in …"
        ops.create_todo(todolist=todolist, title="Pack", creator=self.ada)
        ops.create_todo(todolist=todolist, title="Go", creator=self.ada)
        record(
            actor=self.ada,
            action=Action.MOVED,
            project=self.project,
            item=self.secret,
            to=todolist.title,
        )
        self.client.force_login(self.ada)
        response = self.client.get("/feed/")
        self.assertContains(response, "in For @Bob")
        self.assertRegex(response.content.decode(), r"to\s+For @Bob")
        self.assertNotContains(response, "person:")

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
        # Filtered by the person too
        response = self.client.get("/feed/", {"person": self.ada.pk})
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
        # The person filter is a combobox (specs/ui.md, "Forms"), saying who
        # people are but not finding them by their address
        response = self.client.get("/feed/")
        self.assertContains(response, 'data-combobox=""')
        self.assertContains(response, "Bob Example · Our organization")
        self.assertNotContains(response, "data-search")

    def test_project_feed_and_person_filter(self):
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
        response = self.client.get("/feed/", {"person": self.bob.pk})
        self.assertContains(response, "Elsewhere")
        self.assertNotContains(response, "Open point")
        # The person's own feed page is gone, without a redirect (decided
        # 2026-11-22): their page shows their last entries
        self.assertEqual(
            self.client.get(f"/people/{self.bob.pk}/feed/").status_code, 404
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
        seen = response.text.count('<li class="mb-2 wb-event" data-kb-row>')
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

    def test_project_page_links_to_the_feed(self):
        self.client.force_login(self.ada)
        self.assertContains(
            self.client.get(self.project.get_absolute_url()),
            f"/projects/{self.project.pk}/feed/",
        )

    def test_merged_entry_shows_its_to_dos(self):
        for todo in self.todos(self.shared, 3):
            record(
                actor=self.ada, action=Action.COMPLETED, project=self.project, item=todo
            )
        self.client.force_login(self.ada)
        response = self.client.get("/feed/")
        self.assertIn("completed 3 to-dos in Shared", " ".join(response.text.split()))
        # The single to-dos show right away, nothing is hidden in a details
        self.assertNotContains(response, "<details>")
        for n in range(3):
            self.assertContains(response, f"Todo {n}")
        self.assertEqual(timezone.localdate(), response.context["days"][0][0])


class PersonLinksTest(FeedBase):
    """Names in the activity link to the person's page where the viewer may
    open it, else they're plain text (decided 2026-11-22)"""

    def link(self, person):
        return f'href="/people/{person.pk}/"'

    def test_staff_get_links_from_actors_and_the_people_named(self):
        ops.assign(self.todo, [self.cleo], actor=self.bob)
        self.client.force_login(self.ada)
        for url in ["/feed/", f"/projects/{self.project.pk}/feed/"]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertContains(response, self.link(self.bob))
                self.assertContains(response, self.link(self.cleo))
                self.assertIn("Bob assigned Cleo to", page_text(response))

    def test_a_client_gets_plain_text_for_somebody_it_may_not_know(self):
        record(
            actor=self.bob, action=Action.EDITED, project=self.project, item=self.todo
        )
        record(
            actor=self.ada, action=Action.EDITED, project=self.project, item=self.todo
        )
        # Bob left: Cleo shares no project with him anymore
        self.project.memberships.filter(user=self.bob).delete()
        self.client.force_login(self.cleo)
        response = self.client.get("/feed/")
        self.assertContains(response, self.link(self.ada))
        self.assertIn("Bob", page_text(response))
        self.assertNotContains(response, self.link(self.bob))
        # Own staff may know everybody
        self.client.force_login(self.ada)
        self.assertContains(self.client.get("/feed/"), self.link(self.bob))

    def test_my_activity_is_the_activity_filtered_by_me(self):
        self.client.force_login(self.cleo)
        response = self.client.get("/feed/")
        self.assertContains(response, f'href="/feed/?person={self.cleo.pk}"')
        self.assertContains(response, "My activity")

    def test_the_menu_entry_without_a_project_too(self):
        loner = person("Eve")
        self.client.force_login(loner)
        response = self.client.get("/feed/")
        self.assertContains(response, f'href="/feed/?person={loner.pk}"')
        self.assertTrue(
            response
            .context["form"]
            .fields["person"]
            .queryset.filter(pk=loner.pk)
            .exists()
        )


class EventsBeforeVisibleTest(TestCase):
    """Clients only see events of the time an item was visible to them:
    events store the title at the time, assignees and people mentioned
    (decided 2026-11-20, specs/access.md)"""

    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.bob, self.cleo])
        internal = ops.create_list(
            project=self.project, title="Internal", creator=self.ada
        )
        self.shared = ops.create_list(
            project=self.project, title="Shared", creator=self.ada, visible=True
        )
        # Created internally, renamed, moved into a visible list
        self.todo = ops.create_todo(
            todolist=internal, title="Raise the rate for Cleo", creator=self.ada
        )
        ops.assign(self.todo, [self.bob], actor=self.ada)
        ops.update_todo(self.todo, actor=self.ada, title="Plan the next phase")
        ops.move_todo(self.todo, todolist=self.shared, actor=self.ada)
        # A visible list made internal and visible again
        self.other = ops.create_list(
            project=self.project, title="Later", creator=self.ada, visible=True
        )
        ops.set_visibility(self.other, visible=False, actor=self.ada)
        ops.update_list(self.other, actor=self.ada, title="Codename Falcon")
        ops.update_list(self.other, actor=self.bob, title="Later still")
        ops.set_visibility(self.other, visible=True, actor=self.ada)

    def test_events_store_whether_clients_saw_the_item(self):
        self.assertEqual(
            [
                (e.item.pk, e.action, e.is_client_visible)
                for e in Event.objects.filter(
                    item__in=[self.todo, self.other]
                ).order_by("pk")
            ],
            [
                (self.todo.pk, Action.CREATED, False),
                (self.todo.pk, Action.ASSIGNED, False),
                (self.todo.pk, Action.EDITED, False),
                (self.todo.pk, Action.MOVED, True),
                (self.other.pk, Action.CREATED, True),
                (self.other.pk, Action.VISIBILITY_CHANGED, False),
                (self.other.pk, Action.EDITED, False),
                (self.other.pk, Action.EDITED, False),
                (self.other.pk, Action.VISIBILITY_CHANGED, True),
            ],
        )

    def test_pages(self):
        self.client.force_login(self.cleo)
        for url in [
            "/feed/",
            f"/projects/{self.project.pk}/feed/",
            f"/feed/?person={self.ada.pk}",
            f"/people/{self.ada.pk}/",
            self.project.get_absolute_url(),
        ]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertContains(response, "Plan the next phase")
                self.assertNotContains(response, "Raise the rate")
                self.assertNotContains(response, "Falcon")
        # Staff see everything
        self.client.force_login(self.ada)
        response = self.client.get("/feed/")
        self.assertContains(response, "Raise the rate")
        self.assertContains(response, "Falcon")

    def test_api(self):
        _token, secret = APIToken.create_for(user=self.cleo, title="T", access="read")
        headers = {"authorization": f"Bearer {secret}"}
        for path in [
            "feed/",
            f"projects/{self.project.pk}/feed/",
            f"people/{self.ada.pk}/feed/",
        ]:
            with self.subTest(path=path):
                results = self.client.get(f"/api/v1/{path}", headers=headers).json()[
                    "results"
                ]
                self.assertNotIn("Raise the rate", str(results))
                self.assertNotIn("Falcon", str(results))
                self.assertNotIn(
                    "assigned", [e["action"] for e in results]
                )  # Bob's ID while internal
                self.assertTrue(results)


class GroupMoveTest(FeedBase):
    """Moving a to-do to another group of its list (a board column) is an
    event, merged like edits (decided 2026-11-21)"""

    def setUp(self):
        super().setUp()
        self.doing = ops.create_group(todolist=self.shared.todolist, title="Doing")
        self.done = ops.create_group(todolist=self.shared.todolist, title="Done")

    def move(self, group, item=None, actor=None):
        item = item or self.todo
        ops.move_todo(item, todolist=item.parent, group=group, actor=actor or self.ada)

    def moves(self):
        return list(
            Event.objects.filter(action=Action.MOVED).values_list("data", flat=True)
        )

    def test_one_event_with_the_group(self):
        self.move(self.done)
        [data] = self.moves()
        self.assertEqual((data["group"], data["list"]), ("Done", "Shared"))
        self.client.force_login(self.ada)
        response = self.client.get("/feed/")
        self.assertIn("to Done", squash(response))

    def test_back_and_forth_is_one_event_with_the_last_group(self):
        self.move(self.done)
        self.move(self.doing)
        self.move(self.done)
        self.assertEqual([data["group"] for data in self.moves()], ["Done"])
        # Somebody else, or later: an event of its own
        self.move(self.doing, actor=self.bob)
        self.assertEqual(len(self.moves()), 2)
        Event.objects.update(created_at=timezone.now() - dt.timedelta(minutes=11))
        self.move(self.done, actor=self.bob)
        self.assertEqual(len(self.moves()), 3)

    def test_reordering_within_the_group_records_nothing(self):
        other = ops.create_todo(todolist=self.shared, title="Other", creator=self.ada)
        Event.objects.all().delete()
        ops.move_todo(other, todolist=self.shared, index=0, actor=self.ada)
        self.assertEqual(self.moves(), [])

    def test_clients_see_it_on_visible_todos_only(self):
        self.move(self.done)
        group = ops.create_group(todolist=self.internal.todolist, title="Hidden")
        self.move(group, item=self.secret)
        self.client.force_login(self.cleo)
        response = self.client.get("/feed/")
        self.assertIn("to Done", squash(response))
        self.assertNotContains(response, "Secret")
        self.assertNotContains(response, "Hidden")

    def test_mails_name_the_group_for_clients_too(self):
        self.move(self.done)
        event = Event.objects.get(action=Action.MOVED)
        for user in [self.bob, self.cleo]:
            self.assertEqual(describe(event, user), "Ada Example moved it to Done.")


class MoveTargetTest(FeedBase):
    """Clients see the target list of a move between lists if the list is
    visible to them now (decided 2026-11-21)"""

    def setUp(self):
        super().setUp()
        self.plans = ops.create_list(
            project=self.project, title="Plans", creator=self.ada, visible=True
        )
        self.drafts = ops.create_list(
            project=self.project, title="Drafts", creator=self.ada
        )
        self.second = ops.create_todo(
            todolist=self.shared, title="Second point", creator=self.ada
        )
        Event.objects.all().delete()

    def move(self, todolist, todo=None):
        ops.move_todo(todo or self.todo, todolist=todolist, actor=self.ada)

    def feed(self, user):
        self.client.force_login(user)
        return self.client.get("/feed/")

    def keep_visible(self, *todos):
        """A to-do in an internal list is internal as well, which hides its
        events from clients anyway; to test the target list's own check the
        stored visibility stays"""
        Item.objects.filter(pk__in=[t.pk for t in todos]).update(is_client_visible=True)
        Event.objects.filter(item__in=todos).update(is_client_visible=True)

    def test_stores_the_lists_id(self):
        self.move(self.plans)
        [data] = Event.objects.values_list("data", flat=True)
        self.assertEqual((data["to"], data["to_id"]), ("Plans", self.plans.pk))

    def test_client_sees_a_visible_list_but_not_an_internal_one(self):
        self.move(self.plans)
        self.move(self.drafts, self.second)
        self.keep_visible(self.second)
        response = self.feed(self.cleo)
        self.assertIn("to Plans", squash(response))
        self.assertContains(response, "Second point")
        self.assertNotContains(response, "Drafts")
        for user in [self.ada, self.bob]:
            response = self.feed(user)
            self.assertIn("to Plans", squash(response))
            self.assertIn("to Drafts", squash(response))

    def test_a_list_made_internal_later_disappears(self):
        self.move(self.plans)
        self.assertIn("to Plans", squash(self.feed(self.cleo)))
        ops.set_visibility(self.plans, visible=False, actor=self.ada)
        self.keep_visible(self.todo)
        response = self.feed(self.cleo)
        self.assertContains(response, "Open point")
        self.assertNotContains(response, "Plans")
        self.assertIn("to Plans", squash(self.feed(self.ada)))

    def test_the_current_title_is_shown(self):
        self.move(self.plans)
        ops.update_list(self.plans, actor=self.ada, title="Roadmap")
        self.assertIn("to Roadmap", squash(self.feed(self.cleo)))
        self.assertNotIn("to Plans", squash(self.feed(self.cleo)))

    def test_old_events_without_the_id_stay_staff_only(self):
        record(
            actor=self.ada,
            action=Action.MOVED,
            project=self.project,
            item=self.todo,
            to="Plans",
        )
        self.assertIn("to Plans", squash(self.feed(self.ada)))
        self.assertNotContains(self.feed(self.cleo), "Plans")

    def test_api(self):
        def moved(user):
            _token, secret = APIToken.create_for(user=user, title="T", access="read")
            response = self.client.get(
                "/api/v1/feed/",
                {"action": "moved"},
                headers={"authorization": f"Bearer {secret}"},
            )
            [event] = response.json()["results"]
            return event["data"]

        self.move(self.plans)
        self.assertEqual(moved(self.cleo)["to"], "Plans")
        self.assertEqual(moved(self.cleo)["to_id"], self.plans.pk)
        ops.update_list(self.plans, actor=self.ada, title="Roadmap")
        self.assertEqual(moved(self.ada)["to"], "Roadmap")
        ops.set_visibility(self.plans, visible=False, actor=self.ada)
        self.keep_visible(self.todo)
        self.assertNotIn("to", moved(self.cleo))
        self.assertNotIn("to_id", moved(self.cleo))
        self.assertEqual(moved(self.ada)["to"], "Roadmap")
        # Where it came from is for the timeline only
        self.assertNotIn("to_was", moved(self.ada))

    def test_a_fixed_number_of_queries(self):
        def count(user):
            events = list(feed.feed_events(user))
            with CaptureQueriesContext(connection) as queries:
                feed.add_target_lists(events, user)
            return len(queries)

        self.move(self.plans)
        few = (count(self.cleo), count(self.ada))
        for n in range(5):
            todo = ops.create_todo(
                todolist=self.shared, title=f"More {n}", creator=self.ada
            )
            self.move(self.plans, todo)
        self.assertEqual((count(self.cleo), count(self.ada)), few)
        # Staff: one more, whether they're the own organization (the old
        # title of lists they can't see, specs/access.md)
        self.assertEqual(few, (1, 2))


class MoveOutOfGroupTest(FeedBase):
    def test_reads_out_of_its_group(self):
        group = ops.create_group(todolist=self.shared.todolist, title="Done")
        ops.move_todo(self.todo, todolist=self.shared, group=group, actor=self.ada)
        # In the group from before (moving it in and out at once is nothing)
        Event.objects.all().delete()
        ops.move_todo(self.todo, todolist=self.shared, group=None, actor=self.ada)
        [event] = Event.objects.filter(action=Action.MOVED)
        self.assertEqual(event.data["group"], "")
        for user in [self.ada, self.cleo]:
            self.client.force_login(user)
            self.assertIn("out of its group", squash(self.client.get("/feed/")))
            self.assertEqual(
                describe(event, user), "Ada Example moved it out of its group."
            )


class ToggleNetTest(FeedBase):
    """Completing and reopening back and forth (decided 2026-11-21): every
    one is recorded; the feed shows a person's consecutive ones on an item
    (each within an hour of the one before, on the same day) as the net
    change, nothing when the to-do is back where it started"""

    def actions(self):
        return list(
            Event.objects
            .filter(item=self.todo)
            .order_by("created_at", "pk")
            .values_list("action", flat=True)
        )

    def shown(self):
        events = list(feed.feed_events(self.ada))
        feed.attach(events, self.ada)
        return [event.action for entry in feed.merge(events) for event in entry.events]

    def test_back_and_forth_is_recorded_and_shows_the_net_change(self):
        ops.complete(self.todo, actor=self.ada)
        ops.reopen(self.todo, actor=self.ada)
        self.assertEqual(self.actions(), [Action.COMPLETED, Action.REOPENED])
        self.assertEqual(self.shown(), [])
        ops.complete(self.todo, actor=self.ada)
        self.assertEqual(self.shown(), [Action.COMPLETED])
        self.client.force_login(self.bob)
        text = page_text(self.client.get("/feed/"))
        self.assertEqual(text.count("completed Open point"), 1)
        self.assertNotIn("reopened Open point", text)

    def test_other_events_in_between_dont_break_it_up(self):
        ops.complete(self.todo, actor=self.ada)
        ops.add_comment(self.todo, author=self.bob, content="Really?")
        ops.reopen(self.todo, actor=self.ada)
        self.assertEqual(self.shown(), [Action.COMMENTED])

    def test_someone_else_reopening_shows(self):
        ops.complete(self.todo, actor=self.ada)
        ops.reopen(self.todo, actor=self.bob)
        ops.complete(self.todo, actor=self.ada)
        self.assertEqual(
            self.shown(), [Action.COMPLETED, Action.REOPENED, Action.COMPLETED]
        )

    def test_more_than_an_hour_apart_shows(self):
        event_at(self.ada, Action.COMPLETED, self.todo, NOW - dt.timedelta(minutes=61))
        event_at(self.ada, Action.REOPENED, self.todo, NOW)
        self.assertEqual(self.shown(), [Action.REOPENED, Action.COMPLETED])

    def test_chains_each_within_an_hour(self):
        event_at(self.ada, Action.COMPLETED, self.todo, NOW - dt.timedelta(minutes=100))
        event_at(self.ada, Action.REOPENED, self.todo, NOW - dt.timedelta(minutes=50))
        event_at(self.ada, Action.COMPLETED, self.todo, NOW)
        self.assertEqual(self.shown(), [Action.COMPLETED])


class MoveBackTest(FeedBase):
    """A to-do moved into another column or list and back shows nothing,
    like completing and reopening (decision B, specs/feed.md)"""

    def shown(self):
        events = list(feed.feed_events(self.ada))
        feed.attach(events, self.ada)
        return [
            (event.action, event.data.get("group", event.data.get("to")))
            for entry in feed.merge(events)
            for event in entry.events
        ]

    def test_into_a_column_and_back(self):
        done = ops.create_group(todolist=self.shared.todolist, title="Done")
        Event.objects.all().delete()
        ops.move_todo(self.todo, todolist=self.shared, group=done, actor=self.ada)
        ops.move_todo(self.todo, todolist=self.shared, group=None, actor=self.ada)
        self.assertEqual(self.shown(), [])
        ops.move_todo(self.todo, todolist=self.shared, group=done, actor=self.ada)
        self.assertEqual(self.shown(), [(Action.MOVED, "Done")])

    def test_into_another_list_and_back(self):
        plans = ops.create_list(project=self.project, title="Plans", creator=self.ada)
        Event.objects.all().delete()
        ops.move_todo(self.todo, todolist=plans, actor=self.ada)
        ops.add_comment(self.todo, author=self.bob, content="Why?")
        ops.move_todo(self.todo, todolist=self.shared, actor=self.ada)
        self.assertEqual(self.shown(), [(Action.COMMENTED, None)])
        # Elsewhere in the end: the last move
        ops.move_todo(self.todo, todolist=plans, actor=self.ada)
        self.assertEqual(
            self.shown(), [(Action.MOVED, "Plans"), (Action.COMMENTED, None)]
        )

    def test_someone_else_moving_it_back_shows(self):
        plans = ops.create_list(project=self.project, title="Plans", creator=self.ada)
        Event.objects.all().delete()
        ops.move_todo(self.todo, todolist=plans, actor=self.ada)
        ops.move_todo(self.todo, todolist=self.shared, actor=self.bob)
        self.assertEqual(len(self.shown()), 2)

    def test_someone_elses_move_in_between_shows_in_a_persons_feed(self):
        # The person's feed leaves Bob's move out, but it still breaks up
        # Ada's moves: they show as they do in the whole feed
        plans = ops.create_list(project=self.project, title="Plans", creator=self.ada)
        later = ops.create_list(project=self.project, title="Later", creator=self.ada)
        Event.objects.all().delete()
        ops.move_todo(self.todo, todolist=plans, actor=self.ada)
        ops.move_todo(self.todo, todolist=later, actor=self.bob)
        ops.move_todo(self.todo, todolist=self.shared, actor=self.ada)
        self.client.force_login(self.ada)
        whole = page_text(self.client.get("/feed/"))
        self.assertEqual(whole.count("moved Open point"), 3)
        for url in [f"/people/{self.ada.pk}/", f"/feed/?person={self.ada.pk}"]:
            with self.subTest(url=url):
                text = page_text(self.client.get(url))
                self.assertEqual(text.count("moved Open point"), 2)

    def test_someone_elses_toggles_in_between_show_in_a_persons_feed(self):
        ops.complete(self.todo, actor=self.ada)
        ops.reopen(self.todo, actor=self.bob)
        ops.complete(self.todo, actor=self.bob)
        ops.reopen(self.todo, actor=self.ada)
        events = list(feed.feed_events(self.ada, person=self.ada))
        feed.attach(events, self.ada)
        shown = [e.action for entry in feed.merge(events) for e in entry.events]
        self.assertEqual(shown, [Action.REOPENED, Action.COMPLETED])

    def test_a_column_move_before_moving_to_another_list_and_back(self):
        # Ada drags it from X to Y, moves it into another list and back into
        # X: it's where it was, nothing says it's in Y
        x = ops.create_group(todolist=self.shared.todolist, title="ColX")
        y = ops.create_group(todolist=self.shared.todolist, title="ColY")
        plans = ops.create_list(project=self.project, title="Plans", creator=self.ada)
        ops.move_todo(self.todo, todolist=self.shared, group=x, actor=self.ada)
        Event.objects.all().delete()
        ops.move_todo(self.todo, todolist=self.shared, group=y, actor=self.ada)
        ops.move_todo(self.todo, todolist=plans, actor=self.ada)
        ops.move_todo(self.todo, todolist=self.shared, group=x, actor=self.ada)
        self.assertEqual(self.shown(), [])

    def test_a_column_move_before_moving_back_into_another_column(self):
        # Back in the list, but in Y: the last move says so
        x = ops.create_group(todolist=self.shared.todolist, title="ColX")
        y = ops.create_group(todolist=self.shared.todolist, title="ColY")
        plans = ops.create_list(project=self.project, title="Plans", creator=self.ada)
        ops.move_todo(self.todo, todolist=self.shared, group=x, actor=self.ada)
        Event.objects.all().delete()
        ops.move_todo(self.todo, todolist=self.shared, group=y, actor=self.ada)
        ops.move_todo(self.todo, todolist=plans, actor=self.ada)
        ops.move_todo(self.todo, todolist=self.shared, group=y, actor=self.ada)
        self.assertEqual(self.shown(), [(Action.MOVED, "Shared")])

    def test_moved_to_another_list_then_into_a_column_there(self):
        plans = ops.create_list(project=self.project, title="Plans", creator=self.ada)
        later = ops.create_group(todolist=plans.todolist, title="Later")
        Event.objects.all().delete()
        ops.move_todo(self.todo, todolist=plans, actor=self.ada)
        ops.move_todo(self.todo, todolist=plans, group=later, actor=self.ada)
        self.assertEqual(
            self.shown(), [(Action.MOVED, "Later"), (Action.MOVED, "Plans")]
        )


class PageEdgeTest(FeedBase):
    """A page ends between entries: what merges is never split by a page's
    edge (specs/feed.md)"""

    def test_an_entry_is_never_split(self):
        todos = self.todos(self.shared, feed.PAGE_SIZE + 10)
        # Ten edits of other to-dos by Bob, then Ada's completions, all
        # within minutes: the edge falls among Ada's
        for n, todo in enumerate(todos):
            actor, action = (
                (self.bob, Action.EDITED) if n < 10 else (self.ada, Action.COMPLETED)
            )
            event_at(actor, action, todo, NOW - dt.timedelta(minutes=n))
        # An hour and more later on: a page may end there
        event_at(self.bob, Action.EDITED, self.todo, NOW - dt.timedelta(hours=3))
        self.client.force_login(self.ada)
        first = self.client.get("/feed/")
        entries = [e for _d, _l, es in first.context["days"] for e in es]
        self.assertEqual([e.count for e in entries], [10, feed.PAGE_SIZE])
        second = self.client.get(first.context["older"])
        entries = [e for _d, _l, es in second.context["days"] for e in es]
        self.assertEqual([e.count for e in entries], [1])

    def test_a_pair_cancelling_out_is_never_split(self):
        todos = self.todos(self.shared, feed.PAGE_SIZE - 1)
        for n, todo in enumerate(todos):
            event_at(self.bob, Action.EDITED, todo, NOW - dt.timedelta(hours=2 * n))
        last = NOW - dt.timedelta(hours=2 * feed.PAGE_SIZE)
        event_at(self.ada, Action.REOPENED, self.todo, last)
        event_at(self.ada, Action.COMPLETED, self.todo, last - dt.timedelta(minutes=5))
        self.client.force_login(self.ada)
        first = self.client.get("/feed/")
        self.assertNotIn("Ada reopened", page_text(first))
        self.assertIsNone(first.context["older"])
