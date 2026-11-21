"""Archiving from the projects page (specs/ui-round-1.md, part 6): htmx gets
the page's content again with "Archived. Undo"; without htmx it still works"""

from django.test import TestCase
from django.urls import reverse

from biwak.projects import operations as project_ops
from biwak.test_utils import person, project


HTMX = {"HX-Request": "true"}


class ArchivePageTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.cleo = person("Cleo", client=True)
        self.camp = project("Camp", members=[self.ada, self.cleo])
        self.tent = project("Tent", members=[self.ada, self.cleo])
        self.url = reverse("project_archive", args=[self.camp.pk])
        self.client.force_login(self.ada)

    def post(self, **data):
        return self.client.post(self.url, data, headers=HTMX)

    def test_staff_get_the_archive_button_on_cards_clients_dont(self):
        self.assertContains(self.client.get(reverse("projects")), self.url)
        self.client.force_login(self.cleo)
        self.assertNotContains(self.client.get(reverse("projects")), self.url)

    def test_the_page_swaps_and_archiving_has_undo(self):
        response = self.post(list="active")
        self.camp.refresh_from_db()
        self.assertIsNotNone(self.camp.archived_at)
        self.assertTemplateUsed(response, "projects/_page.html")
        self.assertTemplateNotUsed(response, "base.html")
        self.assertContains(response, 'id="projects-page"')
        self.assertContains(response, "Archived.")
        # The card is gone, Tent stays, Undo brings Camp back
        self.assertNotContains(response, f'href="{self.camp.get_absolute_url()}"')
        self.assertContains(response, f'href="{self.tent.get_absolute_url()}"')
        self.assertContains(response, 'name="unarchive"')
        self.assertContains(response, 'name="undo"')

    def test_undo_restores_without_a_message(self):
        project_ops.archive_project(self.camp, actor=self.ada)
        response = self.post(list="active", unarchive=1, undo=1)
        self.camp.refresh_from_db()
        self.assertIsNone(self.camp.archived_at)
        self.assertContains(response, f'href="{self.camp.get_absolute_url()}"')
        self.assertNotContains(response, 'role="status"')

    def test_bringing_back_from_the_archived_list(self):
        project_ops.archive_project(self.camp, actor=self.ada)
        response = self.post(list="archived", unarchive=1)
        self.camp.refresh_from_db()
        self.assertIsNone(self.camp.archived_at)
        self.assertContains(response, "Brought back.")
        self.assertContains(response, "Archived projects")
        # Undo archives it again
        self.assertContains(response, 'name="undo"')
        self.assertNotContains(response, 'name="unarchive"')

    def test_switching_the_lists_is_a_page_swap(self):
        response = self.client.get(reverse("projects"))
        self.assertContains(response, 'hx-select="#projects-page"')
        url = reverse("projects")
        self.assertContains(response, f'href="{url}?archived=1"')
        archived = self.client.get(url, {"archived": 1})
        self.assertContains(archived, f'hx-get="{url}"')

    def test_without_htmx_the_projects_page_loads_again(self):
        response = self.client.post(self.url, {"list": "active"})
        self.assertRedirects(response, reverse("projects"))
        self.camp.refresh_from_db()
        self.assertIsNotNone(self.camp.archived_at)
        response = self.client.post(self.url, {"list": "archived", "unarchive": 1})
        self.assertRedirects(response, reverse("projects") + "?archived=1")

    def test_from_the_project_it_stays_a_redirect(self):
        response = self.client.post(self.url)
        self.assertRedirects(response, self.camp.get_absolute_url())

    def test_clients_may_not_archive(self):
        self.client.force_login(self.cleo)
        self.assertEqual(self.post(list="active").status_code, 403)
        self.camp.refresh_from_db()
        self.assertIsNone(self.camp.archived_at)

    def test_a_limited_project_is_404_for_those_outside(self):
        secret = project("Secret", members=[self.cleo], all_access=False)
        response = self.client.post(
            reverse("project_archive", args=[secret.pk]), {"list": "active"}
        )
        self.assertEqual(response.status_code, 404)
