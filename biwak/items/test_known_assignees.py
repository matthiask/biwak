"""To-do assignees are shown only where the reader may know them
(``Project.people_known_to()``, specs/access.md): people removed from the
project stay assigned to completed to-dos (open ones drop them, decided
2026-11-21), but clients and externals don't learn their names, the way
history and the feed do it. Every entry point: the list, the
to-do's page, "By due date", the API, mails."""

import json

from django.test import TestCase

from biwak.accounts.models import APIToken
from biwak.activity import mails
from biwak.items import operations as ops
from biwak.projects.models import Membership
from biwak.test_utils import external, person, project


class KnownAssigneesTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.cleo = person("Cleo", client=True)
        self.dora = person("Dora", client=True)
        self.pia = external()
        self.project = project(members=[self.ada, self.cleo, self.dora, self.pia])
        self.list = ops.create_list(
            project=self.project, title="Launch", creator=self.ada, visible=True
        )
        self.todo = ops.create_todo(
            todolist=self.list,
            title="Copy",
            creator=self.ada,
            assignees=[self.cleo, self.dora],
            due_on="2026-12-01",
        )
        # Not in the project anymore but still assigned (as on a completed
        # to-do: removing takes them off open ones only)
        Membership.objects.filter(project=self.project, user=self.dora).delete()
        self.urls = [
            self.list.get_absolute_url(),
            self.todo.get_absolute_url(),
            f"/projects/{self.project.pk}/todos/",
        ]

    def test_pages(self):
        for user, sees_dora in [
            (self.ada, True),
            (self.cleo, False),
            (self.pia, False),
        ]:
            self.client.force_login(user)
            for url in self.urls:
                with self.subTest(user=user, url=url):
                    response = self.client.get(url)
                    self.assertContains(response, "Cleo")
                    if sees_dora:
                        self.assertContains(response, "Dora")
                    else:
                        self.assertNotContains(response, "Dora")

    def test_api(self):
        for user, sees_dora in [
            (self.ada, True),
            (self.cleo, False),
            (self.pia, False),
        ]:
            _token, secret = APIToken.create_for(user=user, title="T", access="read")
            response = self.client.get(
                f"/api/v1/todos/{self.todo.pk}/",
                headers={"authorization": f"Bearer {secret}"},
            )
            names = [a["name"] for a in response.json()["assignees"]]
            with self.subTest(user=user):
                self.assertIn("Cleo Example", names)
                self.assertEqual("Dora Example" in names, sees_dora)
                if not sees_dora:
                    self.assertNotIn(
                        f'"id": {self.dora.pk},', json.dumps(response.json())
                    )

    def test_mails(self):
        for user, sees_dora in [
            (self.ada, True),
            (self.cleo, False),
            (self.pia, False),
        ]:
            context = mails._item(self.todo, user)
            with self.subTest(user=user):
                self.assertIn("Cleo Example", context["assignees"])
                self.assertEqual("Dora Example" in context["assignees"], sees_dora)
