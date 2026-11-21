"""Seeing more without opening everything (specs/glance.md)"""

import datetime as dt

import time_machine
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from biwak.accounts.models import APIToken
from biwak.activity import mentions
from biwak.activity.models import Event
from biwak.files.test_attachments import upload
from biwak.items import operations as ops
from biwak.items.models import Comment
from biwak.templatetags.biwak import excerpt
from biwak.test_utils import person, project


class Fixture(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.cleo])
        self.internal = ops.create_list(
            project=self.project, title="Internal", creator=self.ada
        )
        self.shared = ops.create_list(
            project=self.project, title="Shared", creator=self.ada, visible=True
        )
        self.secret = ops.create_todo(
            todolist=self.internal,
            title="Secret",
            creator=self.ada,
            notes="Internal notes",
        )
        self.todo = ops.create_todo(
            todolist=self.shared,
            title="Open point",
            creator=self.ada,
            notes=f"Some **notes** for [@Ada](person:{self.ada.pk})",
        )
        Event.objects.all().delete()


class MentionsTest(Fixture):
    def test_current_names_with_the_item(self):
        text = f"[@Ada Example](person:{self.ada.pk})"
        self.ada.full_name = "Ada Renamed"
        self.ada.short_name = "Addy"
        self.ada.save()
        self.assertEqual(excerpt(text, 100, self.todo), "@Addy")
        # Without an item, the label as written
        self.assertEqual(excerpt(text, 100), "@Ada Example")

    def test_people_who_cant_see_the_item_keep_the_label(self):
        outsider = person("Dora")  # staff, but the project is limited
        limited = project("Limited", members=[self.ada], all_access=False)
        todolist = ops.create_list(project=limited, title="L", creator=self.ada)
        text = f"[@Old label](person:{outsider.pk})"
        self.assertEqual(excerpt(text, 100, todolist), "@Old label")

    def test_attachments_are_nothing_and_cost_no_query(self):
        attachment = upload(self.project, self.ada)
        text = f"See ![x](attachment:{attachment.key}) and [the file](attachment:{attachment.key})"
        with self.assertNumQueries(0):
            self.assertEqual(excerpt(text, 100), "See and the file")


class RowsTest(Fixture):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.ada)

    def commented(self, count):
        todo = ops.create_todo(todolist=self.shared, title="Busy", creator=self.ada)
        for n in range(count):
            ops.add_comment(todo, author=self.ada, content=f"Comment {n}")
        return todo

    def test_indicators(self):
        todo = self.commented(2)
        response = self.client.get(self.shared.get_absolute_url())
        self.assertContains(response, f'hx-get="/todos/{todo.pk}/peek/"')
        self.assertContains(response, 'title="2 comments"')
        # The notes' excerpt, rendered (mentions as written: no query per row)
        self.assertContains(response, 'title="Some notes for @Ada"')
        self.assertContains(response, f'hx-get="/todos/{self.todo.pk}/peek/"')

    def test_no_indicators_without_notes_and_comments(self):
        ops.create_todo(todolist=self.shared, title="Plain", creator=self.ada)
        self.todo.todo.notes = ""
        self.todo.todo.save()
        response = self.client.get(self.shared.get_absolute_url())
        self.assertNotContains(response, "/peek/")

    def test_attachments_indicator(self):
        todo = ops.create_todo(todolist=self.shared, title="Files", creator=self.ada)
        attachment = upload(self.project, self.ada)
        ops.update_todo(
            todo,
            actor=self.ada,
            title="Files",
            notes=f"![x](attachment:{attachment.key})",
            due_on=None,
            assignees=[],
        )
        response = self.client.get(self.shared.get_absolute_url())
        self.assertContains(response, 'title="1 attachment"')

    def count_queries(self, url):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as queries:
            self.assertEqual(self.client.get(url).status_code, 200)
        return len(queries)

    def test_fixed_number_of_queries(self):
        urls = [
            self.shared.get_absolute_url(),
            self.shared.get_absolute_url() + "?view=board",
            "/todos/",
            f"/projects/{self.project.pk}/todos/",
        ]
        before = {url: self.count_queries(url) for url in urls}
        for n in range(6):
            todo = ops.create_todo(
                todolist=self.shared,
                title=f"More {n}",
                creator=self.ada,
                notes="Notes",
                due_on=dt.date(2026, 1, 1),
            )
            ops.add_comment(todo, author=self.ada, content="Hi")
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.count_queries(url), before[url])

    def test_clients_see_indicators_on_visible_todos_only(self):
        self.client.force_login(self.cleo)
        response = self.client.get(self.shared.get_absolute_url())
        self.assertContains(response, f"/todos/{self.todo.pk}/peek/")
        self.assertEqual(
            self.client.get(self.internal.get_absolute_url()).status_code, 404
        )

    def test_by_due_date_rows(self):
        self.todo.todo.due_on = dt.date(2026, 1, 1)
        self.todo.todo.save()
        ops.add_comment(self.todo, author=self.ada, content="Hi")
        response = self.client.get("/todos/")
        self.assertContains(response, 'title="1 comment"')
        self.assertContains(response, f"/todos/{self.todo.pk}/peek/")


class PeekTest(Fixture):
    def test_staff_peek(self):
        for n in range(5):
            ops.add_comment(self.todo, author=self.ada, content=f"Comment number {n}")
        self.client.force_login(self.ada)
        response = self.client.get(f"/todos/{self.todo.pk}/peek/")
        self.assertContains(response, "<strong>notes</strong>")
        self.assertContains(response, "@Ada")
        # The latest three, newest first
        self.assertNotContains(response, "Comment number 1")
        self.assertContains(response, "Comment number 2")
        self.assertContains(response, "Comment number 4")
        self.assertLess(
            response.text.index("Comment number 4"),
            response.text.index("Comment number 2"),
        )
        self.assertContains(response, "The latest 3 of 5 comments")
        self.assertContains(response, f'href="/todos/{self.todo.pk}/"')
        self.assertNotContains(response, "<form")
        self.assertNotContains(response, "<html")

    def test_client_peeks_visible_todos(self):
        ops.add_comment(self.todo, author=self.ada, content="Hello client")
        self.client.force_login(self.cleo)
        self.assertContains(
            self.client.get(f"/todos/{self.todo.pk}/peek/"), "Hello client"
        )

    def test_client_gets_404_for_internal_todos(self):
        self.client.force_login(self.cleo)
        response = self.client.get(f"/todos/{self.secret.pk}/peek/")
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, "Internal notes", status_code=404)


class ListCountsTest(Fixture):
    @time_machine.travel("2026-11-20 12:00", tick=False)
    def test_counts(self):
        today = dt.date(2026, 11, 20)
        for due_on in [
            None,
            today,
            today - dt.timedelta(days=1),
            today - dt.timedelta(days=5),
        ]:
            ops.create_todo(
                todolist=self.shared, title="x", creator=self.ada, due_on=due_on
            )
        done = ops.create_todo(
            todolist=self.shared,
            title="done",
            creator=self.ada,
            due_on=today - dt.timedelta(days=9),
        )
        ops.complete(done, actor=self.ada)
        trashed = ops.create_todo(
            todolist=self.shared,
            title="gone",
            creator=self.ada,
            due_on=today - dt.timedelta(days=9),
        )
        ops.trash(trashed, actor=self.ada)
        ops.create_todo(todolist=self.internal, title="y", creator=self.ada)
        self.client.force_login(self.ada)
        url = f"/projects/{self.project.pk}/"
        response = self.client.get(url)
        # 4 + the one of the fixture open in "Shared"; 2 overdue
        self.assertContains(response, "5 open")
        self.assertContains(response, "2 overdue")
        self.assertContains(response, "2 open")  # Internal: Secret + y

    def test_clients_count_what_they_see(self):
        ops.create_todo(todolist=self.shared, title="x", creator=self.ada)
        self.client.force_login(self.cleo)
        response = self.client.get(f"/projects/{self.project.pk}/")
        self.assertContains(response, "2 open")
        self.assertNotContains(response, "Internal")
        self.assertNotContains(response, "overdue")

    def test_no_overdue_without_any(self):
        self.client.force_login(self.ada)
        self.assertNotContains(
            self.client.get(f"/projects/{self.project.pk}/"), "overdue"
        )

    def test_fixed_number_of_queries(self):
        self.client.force_login(self.ada)
        url = f"/projects/{self.project.pk}/"
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        def queries():
            with CaptureQueriesContext(connection) as q:
                self.client.get(url)
            return len(q)

        Event.objects.all().delete()
        before = queries()
        for n in range(4):
            todolist = ops.create_list(
                project=self.project, title=f"L{n}", creator=self.ada
            )
            ops.create_todo(todolist=todolist, title="t", creator=self.ada)
        # The feed beside the lists has its own queries per event
        Event.objects.all().delete()
        self.assertEqual(queries(), before)


class FeedExcerptsTest(Fixture):
    def setUp(self):
        super().setUp()
        self.comment = ops.add_comment(
            self.todo, author=self.ada, content="A **long** comment about it"
        )
        self.secret_comment = ops.add_comment(
            self.secret, author=self.ada, content="Internal remark"
        )

    def test_staff_feed_shows_excerpt(self):
        self.client.force_login(self.ada)
        for url in [
            "/feed/",
            f"/projects/{self.project.pk}/feed/",
            f"/projects/{self.project.pk}/",
        ]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertContains(
                    response, '<div class="wb-excerpt">A long comment about it</div>'
                )
                self.assertContains(response, "Internal remark")

    def test_excerpt_is_as_it_is_now(self):
        Comment.objects.filter(pk=self.comment.pk).update(content="Edited text")
        self.client.force_login(self.ada)
        response = self.client.get("/feed/")
        self.assertContains(response, "Edited text")
        self.assertNotContains(response, "A long comment")

    def test_client_feed(self):
        self.client.force_login(self.cleo)
        for url in [
            "/feed/",
            f"/projects/{self.project.pk}/feed/",
            f"/people/{self.ada.pk}/feed/",
        ]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertContains(response, "A long comment about it")
                self.assertNotContains(response, "Internal remark")

    def test_deleted_comment_has_no_excerpt(self):
        self.comment.delete()
        self.client.force_login(self.ada)
        response = self.client.get("/feed/")
        self.assertNotContains(response, 'wb-excerpt">A long')
        self.assertNotContains(response, "long comment")
        self.assertContains(response, "commented on")

    def test_other_events_have_none(self):
        ops.create_todo(todolist=self.shared, title="New one", creator=self.ada)
        self.client.force_login(self.ada)
        self.assertNotContains(self.client.get("/feed/?action=created"), "wb-excerpt")

    def test_comments_on_one_item_are_a_conversation_with_all_excerpts(self):
        ops.add_comment(self.todo, author=self.ada, content="Second comment")
        ops.add_comment(self.todo, author=self.ada, content="Third comment")
        self.client.force_login(self.ada)
        html = self.client.get(f"/projects/{self.project.pk}/feed/").text
        self.assertIn("Conversation on", html)
        self.assertNotIn("<details>", html)
        for text in ["A long comment about it", "Second comment", "Third comment"]:
            self.assertEqual(html.count(f'wb-excerpt">{text}'), 1)

    def test_mentions_show_current_names(self):
        ops.add_comment(self.todo, author=self.ada, content=mentions.syntax(self.ada))
        self.ada.short_name = "Addy"
        self.ada.save()
        self.client.force_login(self.ada)
        self.assertContains(
            self.client.get("/feed/"), '<div class="wb-excerpt">@Addy</div>'
        )

    def test_long_comments_are_cut(self):
        ops.add_comment(self.todo, author=self.ada, content="word " * 100)
        self.client.force_login(self.ada)
        self.assertContains(self.client.get("/feed/"), "word…</div>")

    def test_api(self):
        _token, secret = APIToken.create_for(user=self.cleo, title="T", access="read")
        response = self.client.get(
            "/api/v1/feed/", headers={"authorization": f"Bearer {secret}"}
        )
        results = response.json()["results"]
        self.assertEqual(
            [e["excerpt"] for e in results if e["action"] == "commented"],
            ["A long comment about it"],
        )
        self.assertTrue(
            all(not e["excerpt"] for e in results if e["action"] != "commented")
        )


class FeedMessageExcerptsTest(Fixture):
    def setUp(self):
        super().setUp()
        self.message = ops.create_message(
            project=self.project,
            title="Shared news",
            content="Hello **everybody** out there",
            creator=self.ada,
            visible=True,
        )
        self.hidden = ops.create_message(
            project=self.project,
            title="Hidden news",
            content="Internal wording",
            creator=self.ada,
        )

    def test_staff_feed_and_project_page(self):
        self.client.force_login(self.ada)
        for url in [
            "/feed/",
            f"/projects/{self.project.pk}/feed/",
            f"/projects/{self.project.pk}/",
        ]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertContains(
                    response, '<div class="wb-excerpt">Hello everybody out there</div>'
                )
                self.assertContains(response, "Internal wording")

    def test_excerpt_is_the_current_text(self):
        from biwak.files import operations as file_ops

        file_ops.update_message(self.message, actor=self.ada, content="Changed text")
        self.client.force_login(self.ada)
        response = self.client.get("/feed/")
        self.assertContains(response, '<div class="wb-excerpt">Changed text</div>')
        self.assertNotContains(response, "everybody")

    def test_client_feed(self):
        self.client.force_login(self.cleo)
        for url in ["/feed/", f"/projects/{self.project.pk}/feed/"]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertContains(response, "Hello everybody out there")
                self.assertNotContains(response, "Internal wording")

    def test_trashed_message_is_gone_from_the_feed(self):
        ops.trash(self.message, actor=self.ada)
        for user in (self.ada, self.cleo):
            self.client.force_login(user)
            for url in ["/feed/", f"/projects/{self.project.pk}/"]:
                with self.subTest(user=user.pk, url=url):
                    self.assertNotContains(
                        self.client.get(url), "Hello everybody out there"
                    )

    def test_every_action_of_a_message_has_it(self):
        from biwak.files import operations as file_ops

        file_ops.pin_message(self.message, actor=self.ada)
        self.client.force_login(self.ada)
        response = self.client.get("/feed/?action=pinned")
        self.assertContains(response, "pinned")
        self.assertContains(response, "wb-excerpt")

    def test_api(self):
        _token, secret = APIToken.create_for(user=self.cleo, title="T", access="read")
        response = self.client.get(
            "/api/v1/feed/", headers={"authorization": f"Bearer {secret}"}
        )
        self.assertEqual(
            [e["excerpt"] for e in response.json()["results"]],
            ["Hello everybody out there"],
        )

    def test_api_excerpts_cost_one_query_per_page(self):
        for n in range(5):
            ops.add_comment(self.todo, author=self.ada, content=f"Comment {n}")
        ops.create_message(
            project=self.project, title="Another", content="More", creator=self.ada
        )
        _token, secret = APIToken.create_for(user=self.ada, title="T", access="read")
        headers = {"authorization": f"Bearer {secret}"}
        self.client.get("/api/v1/feed/", headers=headers)  # warm caches
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get("/api/v1/feed/", headers=headers)
        self.assertEqual(len(response.json()["results"]), 8)
        self.assertEqual(
            len([q for q in queries if 'FROM "items_comment"' in q["sql"]]), 1
        )
        self.assertEqual(
            len([q for q in queries if 'FROM "items_message"' in q["sql"]]), 1
        )
