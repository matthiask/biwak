"""The forms of items in a modal (biwak/modals.py) and as pages of their own"""

from django.test import TestCase

from biwak.items import operations as ops
from biwak.items.models import Item
from biwak.test_utils import (
    MODAL,
    assert_modal,
    assert_modal_redirect,
    assert_page,
    person,
    project,
)


class ItemModalBase(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.cleo])
        self.shared = ops.create_list(
            project=self.project, title="Shared", creator=self.ada, visible=True
        )
        self.internal = ops.create_list(
            project=self.project, title="Internal", creator=self.ada
        )
        self.client.force_login(self.ada)


class GroupModalTest(ItemModalBase):
    def setUp(self):
        super().setUp()
        self.group = ops.create_group(todolist=self.shared.todolist, title="Later")
        self.new = f"/lists/{self.shared.pk}/groups/"
        self.rename = f"/groups/{self.group.pk}/rename/"

    def test_the_list_has_buttons_not_forms(self):
        response = self.client.get(self.shared.get_absolute_url())
        self.assertContains(response, f'href="{self.new}"')
        self.assertContains(response, f'href="{self.rename}"')
        self.assertNotContains(response, 'placeholder="New group"')

    def test_new_group_as_a_modal_and_a_page(self):
        response = self.client.get(self.new, headers=MODAL)
        assert_modal(self, response, title="New group")
        # The list is visible to clients: the banner says so
        self.assertContains(response, "Clients can see this.")
        assert_page(self, self.client.get(self.new), title="New group")
        response = self.client.get(f"/lists/{self.internal.pk}/groups/", headers=MODAL)
        self.assertNotContains(response, "Clients can see this.")

    def test_saving(self):
        response = self.client.post(self.new, {"title": "Soon"}, headers=MODAL)
        assert_modal_redirect(self, response, self.shared.get_absolute_url())
        self.assertEqual(
            list(self.shared.todolist.groups.values_list("title", flat=True)),
            ["Later", "Soon"],
        )
        response = self.client.post(self.new, {"title": "Page"})
        self.assertRedirects(response, self.shared.get_absolute_url())

    def test_errors_show_the_form_in_the_dialog(self):
        response = self.client.post(self.new, {"title": " "}, headers=MODAL)
        assert_modal(self, response, title="New group")
        self.assertContains(response, "This field is required.")
        self.assertEqual(self.shared.todolist.groups.count(), 1)

    def test_rename(self):
        response = self.client.get(self.rename, headers=MODAL)
        assert_modal(self, response, title="Rename the group")
        self.assertContains(response, 'value="Later"')
        assert_page(self, self.client.get(self.rename), title="Rename the group")
        response = self.client.post(self.rename, {"title": "Maybe"}, headers=MODAL)
        assert_modal_redirect(self, response, self.shared.get_absolute_url())
        self.group.refresh_from_db()
        self.assertEqual(self.group.title, "Maybe")
        response = self.client.post(self.rename, {"title": ""}, headers=MODAL)
        assert_modal(self, response, title="Rename the group")
        self.assertContains(response, "This field is required.")

    def test_clients_dont_change_groups_of_lists_staff_created(self):
        self.client.force_login(self.cleo)
        for url in [self.new, self.rename]:
            for headers in [{}, MODAL]:
                with self.subTest(url=url, headers=headers):
                    self.assertEqual(
                        self.client.get(url, headers=headers).status_code, 403
                    )
                    self.assertEqual(
                        self.client.post(
                            url, {"title": "x"}, headers=headers
                        ).status_code,
                        403,
                    )
        response = self.client.get(self.shared.get_absolute_url())
        self.assertNotContains(response, "New group")

    def test_clients_change_the_groups_of_their_lists(self):
        mine = ops.create_list(
            project=self.project, title="Mine", creator=self.cleo, visible=True
        )
        self.client.force_login(self.cleo)
        response = self.client.post(
            f"/lists/{mine.pk}/groups/", {"title": "Wishes"}, headers=MODAL
        )
        assert_modal_redirect(self, response)
        self.assertTrue(Item.objects.filter(pk=mine.pk).exists())
        self.assertEqual(mine.todolist.groups.get().title, "Wishes")
