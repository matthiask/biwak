from django.test import TestCase

from biwak.items.models import Item, Kind
from biwak.test_utils import (
    MODAL,
    assert_modal,
    assert_modal_redirect,
    assert_page,
    person,
    project,
)


class NewListTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.cleo])
        self.url = f"/projects/{self.project.pk}/lists/new/"
        self.client.force_login(self.ada)

    def test_the_project_page_has_a_button_not_a_form(self):
        response = self.client.get(self.project.get_absolute_url())
        self.assertContains(response, f'href="{self.url}"')
        self.assertContains(response, "data-modal")
        self.assertNotContains(response, 'placeholder="New list"')

    def test_as_a_modal(self):
        response = self.client.get(self.url, headers=MODAL)
        assert_modal(self, response, title="New list")
        self.assertContains(response, 'name="title"')
        self.assertContains(response, "data-modal-close")

    def test_as_a_page(self):
        assert_page(self, self.client.get(self.url), title="New list")

    def test_saving_redirects_the_modal(self):
        response = self.client.post(
            self.url, {"title": "Plan", "visible": "on"}, headers=MODAL
        )
        item = Item.objects.get(title="Plan")
        assert_modal_redirect(self, response, item.get_absolute_url())
        self.assertTrue(item.is_client_visible)

    def test_saving_the_page_redirects(self):
        response = self.client.post(self.url, {"title": "Plan"})
        item = Item.objects.get(title="Plan")
        self.assertRedirects(response, item.get_absolute_url())

    def test_errors_show_the_form_again_in_the_dialog(self):
        response = self.client.post(self.url, {"title": ""}, headers=MODAL)
        assert_modal(self, response, title="New list")
        self.assertContains(response, "This field is required.")
        self.assertFalse(Item.objects.filter(kind=Kind.LIST).exists())

    def test_clients_dont_create_lists(self):
        """Clients create to-dos, comments and messages, not lists
        (specs/access.md)"""
        self.client.force_login(self.cleo)
        for headers in [{}, MODAL]:
            self.assertEqual(
                self.client.get(self.url, headers=headers).status_code, 403
            )
            response = self.client.post(
                self.url, {"title": "Our wishes"}, headers=headers
            )
            self.assertEqual(response.status_code, 403)
        self.assertFalse(Item.objects.filter(title="Our wishes").exists())
        self.assertNotContains(
            self.client.get(self.project.get_absolute_url()), "New list"
        )

    def test_not_for_people_who_cant_open_the_project(self):
        bob = person("Bob")
        limited = project("Limited", members=[self.ada], all_access=False)
        self.client.force_login(bob)
        response = self.client.get(f"/projects/{limited.pk}/lists/new/", headers=MODAL)
        self.assertEqual(response.status_code, 404)
