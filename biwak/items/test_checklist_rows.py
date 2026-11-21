"""The checklist count on rows (specs/editor.md): "1/3" wherever a text is
listed, stored with the text, and no query more for more rows"""

from django.core.files.base import ContentFile
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from biwak.items import operations as ops
from biwak.test_utils import person, project


TEXT = "Packing\n\n- [ ] tent\n- [x] stove\n- [ ] rope"
SIGNAL = "1/3"


class RowsTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.cleo])
        self.shared = ops.create_list(
            project=self.project, title="Shared", creator=self.ada, visible=True
        )
        self.add_all()

    def add_all(self, n=0):
        todo = ops.create_todo(
            todolist=self.shared,
            title=f"Pack {n}",
            creator=self.ada,
            notes=TEXT,
            assignees=[self.ada, self.cleo],
        )
        ops.create_message(
            project=self.project,
            title=f"Camp tent {n}",
            creator=self.ada,
            content=TEXT,
            visible=True,
        )
        ops.create_doc(
            project=self.project,
            title=f"Doc tent {n}",
            creator=self.ada,
            content=TEXT,
            visible=True,
        )
        ops.create_upload(
            project=self.project,
            file=ContentFile(b"x", name=f"tent{n}.txt"),
            creator=self.ada,
            description=TEXT,
            visible=True,
        )
        return todo

    def urls(self):
        return {
            "list": self.shared.get_absolute_url(),
            "board": self.shared.get_absolute_url() + "?view=board",
            "my to-dos": reverse("todos"),
            "project to-dos": reverse("project_todos", args=[self.project.pk]),
            "messages": reverse("project_messages", args=[self.project.pk]),
            "files": reverse("project_files", args=[self.project.pk]),
            "project": reverse("project", args=[self.project.pk]),
            "search": reverse("search") + "?q=tent+OR+pack",
        }

    def count(self, url):
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return response.content.decode(), len(queries)

    def test_shown_as_staff_and_as_client(self):
        # The search finds words, one per text
        for user in [self.ada, self.cleo]:
            self.client.force_login(user)
            for name, url in (self.urls() | {"search": "/search/?q=tent"}).items():
                html, _count = self.count(url)
                self.assertIn(f"<span>{SIGNAL}</span>", html, (user, name))

    def test_nothing_without_a_checklist(self):
        todo = self.shared.children.get()
        ops.update_todo(todo, actor=self.ada, notes="x")
        self.client.force_login(self.ada)
        html, _count = self.count(self.shared.get_absolute_url())
        self.assertNotIn(" done<", html)
        self.assertNotIn("/3<", html)

    def test_fixed_number_of_queries(self):
        self.client.force_login(self.ada)
        urls = self.urls() | {"search": reverse("search") + "?q=tent"}
        before = {name: self.count(url)[1] for name, url in urls.items()}
        for n in range(1, 5):
            self.add_all(n)
        after = {name: self.count(url)[1] for name, url in urls.items()}
        self.assertEqual(after, before)
