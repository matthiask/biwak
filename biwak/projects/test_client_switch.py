"""No clients, no switch (decided 2026-11-23, specs/access.md): the forms
creating things offer "Visible to clients" only in projects with clients,
invited ones too, and in templates; "Show to clients…" stays"""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from biwak.accounts.models import APIToken
from biwak.items.models import Item
from biwak.items.visibility import clients_of
from biwak.projects.models import Membership
from biwak.test_utils import person, project


class ClientSwitchTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.project = project(members=[self.ada])
        self.client.force_login(self.ada)

    def urls(self):
        pk = self.project.pk
        return {
            "list": reverse("list_new", args=[pk]),
            "folder": reverse("folder_new", args=[pk]),
            "message": reverse("message_new", args=[pk]),
            "upload": reverse("file_new", args=[pk]),
            "check-in": reverse("question_new", args=[pk]),
            "link": reverse("project_link_new", args=[pk]),
        }

    def assert_switch(self, *, shown):
        for what, url in self.urls().items():
            with self.subTest(what):
                response = self.client.get(url, headers={"HX-Modal": "true"})
                self.assertEqual(response.status_code, 200)
                if shown:
                    self.assertContains(response, "Visible to clients")
                else:
                    self.assertNotContains(response, "Visible to clients")

    def test_no_clients_no_switch(self):
        self.assert_switch(shown=False)

    def test_a_client_member(self):
        Membership.objects.create(
            project=self.project, user=person("Cleo", client=True)
        )
        self.assert_switch(shown=True)

    def test_an_invited_client(self):
        cleo = person("Cleo", client=True)
        cleo.invited_at = timezone.now()
        cleo.save()
        Membership.objects.create(project=self.project, user=cleo)
        self.assert_switch(shown=True)

    def test_a_client_waiting_to_be_activated(self):
        """Imported, not activated yet: they'll see it once activated"""
        Membership.objects.create(
            project=self.project, user=person("Cleo", client=True, is_active=False)
        )
        self.assert_switch(shown=True)
        self.assertEqual(clients_of(self.project), 1)

    def test_a_deactivated_client(self):
        """Who left counts nowhere (decided 2026-11-28)"""
        Membership.objects.create(
            project=self.project,
            user=person(
                "Cleo", client=True, is_active=False, left_at=timezone.localdate()
            ),
        )
        self.assert_switch(shown=False)
        self.assertEqual(clients_of(self.project), 0)

    def test_templates(self):
        """Their visibility is copied into the projects made from them"""
        self.project.is_template = True
        self.project.save()
        self.assertTrue(self.project.offers_client_switch())

    def test_posting_without_the_switch_is_internal(self):
        response = self.client.post(
            reverse("list_new", args=[self.project.pk]),
            {"title": "Plan", "visible": "on"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Item.objects.get(title="Plan").is_client_visible)

    def test_show_to_clients_stays(self):
        """Staff prepare what a client will see before inviting them"""
        response = self.client.post(
            reverse("list_new", args=[self.project.pk]), {"title": "Plan"}
        )
        todolist = Item.objects.get(title="Plan")
        response = self.client.get(todolist.get_absolute_url())
        self.assertContains(response, "Show to clients")


class ClientSwitchAPITest(TestCase):
    """The API refuses what the pages don't offer (decided 2026-11-28,
    verification round 1); its visibility switch stays, like "Show to
    clients…" """

    def setUp(self):
        self.ada = person("Ada")
        self.project = project(members=[self.ada])
        _token, self.secret = APIToken.create_for(
            user=self.ada, title="T", access="write"
        )

    def post(self, path, data, **kwargs):
        return self.client.post(
            f"/api/v1/{path}",
            data,
            headers={"authorization": f"Bearer {self.secret}"},
            **kwargs,
        )

    def creating(self, *, visible):
        pk = self.project.pk
        json = {"content_type": "application/json"}
        return {
            "list": self.post(
                f"projects/{pk}/lists/",
                {"title": "Plan", "visible_to_clients": visible},
                **json,
            ),
            "folder": self.post(
                f"projects/{pk}/folders/",
                {"title": "Specs", "visible_to_clients": visible},
                **json,
            ),
            "message": self.post(
                f"projects/{pk}/messages/",
                {"title": "News", "visible_to_clients": visible},
                **json,
            ),
            "doc": self.post(
                f"projects/{pk}/docs/",
                {"title": "Notes", "visible_to_clients": visible},
                **json,
            ),
            "file": self.post(
                f"projects/{pk}/files/",
                {
                    "file": SimpleUploadedFile("plan.txt", b"Plan"),
                    "visible_to_clients": "true" if visible else "false",
                },
            ),
            "check-in": self.post(
                f"projects/{pk}/checkins/",
                {
                    "title": "What did you do?",
                    "schedule": "weekdays",
                    "time_of_day": "16:00",
                    "visible_to_clients": visible,
                },
                **json,
            ),
            "link": self.post(
                f"projects/{pk}/links/",
                {
                    "url": "https://example.org/",
                    "visible_to_clients": visible,
                },
                **json,
            ),
        }

    def test_no_clients_refused(self):
        for what, response in self.creating(visible=True).items():
            with self.subTest(what):
                self.assertEqual(response.status_code, 400, response.content)
                self.assertIn("no clients", response.json()["detail"])
        self.assertFalse(Item.objects.exists())
        for what, response in self.creating(visible=False).items():
            with self.subTest(what):
                self.assertEqual(response.status_code, 201, response.content)

    def test_with_a_client(self):
        Membership.objects.create(
            project=self.project, user=person("Cleo", client=True)
        )
        for what, response in self.creating(visible=True).items():
            with self.subTest(what):
                self.assertEqual(response.status_code, 201, response.content)
                self.assertTrue(response.json()["visible_to_clients"])

    def test_the_switch_stays(self):
        todolist = self.post(
            f"projects/{self.project.pk}/lists/",
            {"title": "Plan"},
            content_type="application/json",
        ).json()
        response = self.client.put(
            f"/api/v1/items/{todolist['id']}/visibility/",
            {"visible_to_clients": True},
            content_type="application/json",
            headers={"authorization": f"Bearer {self.secret}"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["visible_to_clients"])
