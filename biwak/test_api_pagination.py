"""Cursor pagination (``paginated()`` in biwak/api_conventions.py): the
cursor is the position of the last row in the whole ordering, so rows
leaving or joining earlier pages neither skip nor repeat others"""

import datetime as dt

from django.test import TestCase

from biwak.accounts.models import APIToken
from biwak.files import operations as files_ops
from biwak.items import operations as ops
from biwak.test_utils import person, project


class PaginationTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.project = project(members=[self.ada])
        _token, secret = APIToken.create_for(user=self.ada, title="T", access="write")
        self.headers = {"authorization": f"Bearer {secret}"}
        self.list = ops.create_list(project=self.project, title="L", creator=self.ada)

    def get(self, url, **params):
        response = self.client.get(url, params, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def pages(self, path, after_first=None, **params):
        """The IDs of every page, following ``next``; ``after_first`` runs
        after the first page"""
        data = self.get(f"/api/v1/{path}", page_size=2, **params)
        self.assertIsNone(data["previous"])
        seen = [row["id"] for row in data["results"]]
        if after_first:
            after_first()
        while data["next"]:
            self.assertLess(len(seen), 20, seen)
            data = self.get(data["next"])
            seen += [row["id"] for row in data["results"]]
        return seen

    def todos(self, count, **kwargs):
        return [
            ops.create_todo(
                todolist=self.list, title=f"T{i}", creator=self.ada, **kwargs
            )
            for i in range(count)
        ]

    def test_messages_trashed_between_pages(self):
        messages = [
            ops.create_message(project=self.project, title=f"M{i}", creator=self.ada)
            for i in range(4)
        ]
        # Newest first, none pinned: M3, M2 | M1, M0
        seen = self.pages(
            f"projects/{self.project.pk}/messages/",
            lambda: ops.trash(messages[3], actor=self.ada),
        )
        self.assertEqual(seen, [m.pk for m in reversed(messages)])

    def test_messages_pinned_first(self):
        messages = [
            ops.create_message(project=self.project, title=f"M{i}", creator=self.ada)
            for i in range(5)
        ]
        files_ops.pin_message(messages[0], actor=self.ada)
        seen = self.pages(f"projects/{self.project.pk}/messages/")
        self.assertEqual(
            seen, [messages[0].pk] + [m.pk for m in reversed(messages[1:])]
        )

    def test_todos_by_project_completed_between_pages(self):
        todos = self.todos(4)
        # By project (the default): T0, T1 | T2, T3
        seen = self.pages("todos/", lambda: ops.complete(todos[0], actor=self.ada))
        self.assertEqual(seen, [t.pk for t in todos])

    def test_todos_by_project_added_on_an_earlier_page(self):
        """A to-do in a project before this one by name (reordering
        renumbers positions: rows moved by it may repeat or be skipped)"""
        todos = self.todos(4)
        earlier = project("Aardvark", members=[self.ada])
        earlier_list = ops.create_list(project=earlier, title="E", creator=self.ada)
        seen = self.pages(
            "todos/",
            lambda: ops.create_todo(
                todolist=earlier_list, title="New", creator=self.ada
            ),
        )
        self.assertEqual(seen, [t.pk for t in todos])

    def test_todos_by_project_with_groups(self):
        """Ungrouped to-dos first (no group: null in the ordering), then
        each group's"""
        group = ops.create_group(todolist=self.list.todolist, title="Later")
        grouped = self.todos(3, group=group)
        ungrouped = self.todos(3)
        seen = self.pages("todos/")
        self.assertEqual(seen, [t.pk for t in ungrouped + grouped])

    def test_todos_by_due_date_completed_between_pages(self):
        todos = self.todos(4, due_on=dt.date(2026, 12, 1))
        seen = self.pages(
            "todos/",
            lambda: ops.complete(todos[0], actor=self.ada),
            grouping="due",
        )
        self.assertEqual(seen, [t.pk for t in todos])

    def test_previous(self):
        todos = self.todos(5)
        first = self.get("/api/v1/todos/", page_size=2)
        second = self.get(first["next"])
        third = self.get(second["next"])
        self.assertEqual([r["id"] for r in third["results"]], [todos[4].pk])
        self.assertIsNone(third["next"])
        back = self.get(third["previous"])
        self.assertEqual(back["results"], second["results"])
        back = self.get(back["previous"])
        self.assertEqual(back["results"], first["results"])
        self.assertIsNone(back["previous"])
        self.assertEqual(self.get(back["next"])["results"], second["results"])

    def test_invalid_cursor(self):
        for cursor in ["nonsense", "cD0yMDI2LTExLTI4", "W10="]:
            response = self.client.get(
                "/api/v1/todos/", {"cursor": cursor}, headers=self.headers
            )
            self.assertEqual(response.status_code, 400, cursor)
