"""No clients, no switch (decided 2026-11-23, specs/access.md): the forms
creating things offer "Visible to clients" only in projects with clients,
invited ones too, and in templates; "Show to clients…" stays"""

from django.test import TestCase
from django.urls import reverse

from biwak.items.models import Item
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
        Membership.objects.create(
            project=self.project, user=person("Cleo", client=True, is_active=False)
        )
        self.assert_switch(shown=True)

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
