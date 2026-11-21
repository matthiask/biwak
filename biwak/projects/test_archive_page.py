"""Archiving lives in the project's menu (specs/ui-round-2.md, part D): the
projects page has no archive buttons, says "Archived Camp." with an Undo
afterwards, and lists the archived projects to open them"""

from django.test import TestCase
from django.urls import reverse

from biwak.projects import operations as project_ops
from biwak.test_utils import person, project


class ArchivePageTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.cleo = person("Cleo", client=True)
        self.camp = project("Camp", members=[self.ada, self.cleo])
        self.tent = project("Tent", members=[self.ada, self.cleo])
        self.url = reverse("project_archive", args=[self.camp.pk])
        self.client.force_login(self.ada)

    def test_no_archive_buttons_on_the_projects_page(self):
        response = self.client.get(reverse("projects"))
        self.assertContains(response, self.camp.get_absolute_url())
        self.assertNotContains(response, self.url)
        project_ops.archive_project(self.camp, actor=self.ada)
        response = self.client.get(reverse("projects"), {"archived": 1})
        self.assertContains(response, self.camp.get_absolute_url())
        self.assertNotContains(response, self.url)
        self.assertNotContains(response, "Bring back")

    def test_the_projects_menu_archives_and_the_page_says_so_with_undo(self):
        self.assertContains(self.client.get(self.camp.get_absolute_url()), self.url)
        response = self.client.post(self.url, follow=True)
        self.assertRedirects(response, reverse("projects"))
        self.camp.refresh_from_db()
        self.assertIsNotNone(self.camp.archived_at)
        self.assertContains(response, "Archived Camp.")
        self.assertContains(response, 'name="undo"')
        self.assertNotContains(response, f'href="{self.camp.get_absolute_url()}"')
        # Said once
        self.assertNotContains(self.client.get(reverse("projects")), "Archived Camp.")

    def test_undo_restores_without_a_message(self):
        self.client.post(self.url)
        response = self.client.post(self.url, {"unarchive": 1, "undo": 1}, follow=True)
        self.assertRedirects(response, reverse("projects"))
        self.camp.refresh_from_db()
        self.assertIsNone(self.camp.archived_at)
        self.assertContains(response, f'href="{self.camp.get_absolute_url()}"')
        self.assertNotContains(response, "Archived Camp.")
        self.assertNotContains(response, 'name="undo"')

    def test_bringing_back_from_the_project_goes_to_the_project(self):
        project_ops.archive_project(self.camp, actor=self.ada)
        response = self.client.post(self.url, {"unarchive": 1})
        self.assertRedirects(response, self.camp.get_absolute_url())
        self.camp.refresh_from_db()
        self.assertIsNone(self.camp.archived_at)

    def test_clients_may_not_archive(self):
        self.client.force_login(self.cleo)
        self.assertEqual(self.client.post(self.url).status_code, 403)
        self.camp.refresh_from_db()
        self.assertIsNone(self.camp.archived_at)

    def test_a_limited_project_is_404_for_those_outside(self):
        secret = project("Secret", members=[self.cleo], all_access=False)
        response = self.client.post(reverse("project_archive", args=[secret.pk]))
        self.assertEqual(response.status_code, 404)
