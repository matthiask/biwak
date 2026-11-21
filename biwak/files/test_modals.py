from django.test import TestCase

from biwak.items import operations as ops
from biwak.test_utils import (
    MODAL,
    assert_modal,
    assert_modal_redirect,
    assert_page,
    person,
    project,
)


class MoveItemModalTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.cleo])
        self.public = ops.create_folder(
            project=self.project, title="Public", creator=self.ada, visible=True
        )
        self.private = ops.create_folder(
            project=self.project, title="Private", creator=self.ada
        )
        self.doc = ops.create_doc(
            project=self.project, title="Notes", creator=self.ada, parent=self.private
        )
        self.url = f"/items/{self.doc.pk}/move/"
        self.client.force_login(self.ada)

    def test_modal_and_page(self):
        response = self.client.get(self.url, headers=MODAL)
        assert_modal(self, response, title="Move to…")
        self.assertContains(response, "Project root")
        self.assertContains(response, "Public (clients can see this)")
        assert_page(self, self.client.get(self.url), title="Move to…")

    def test_moving(self):
        response = self.client.post(self.url, {"folder": self.public.pk}, headers=MODAL)
        assert_modal_redirect(self, response, self.doc.get_absolute_url())
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.parent, self.public)

    def test_a_folder_into_itself_shows_the_error_in_the_dialog(self):
        # Not offered, but posted anyway
        url = f"/items/{self.private.pk}/move/"
        response = self.client.post(url, {"folder": self.private.pk}, headers=MODAL)
        assert_modal(self, response, title="Move to…")
        self.assertContains(response, "can&#x27;t be moved into itself")

    def test_the_page_has_the_menu_entry_not_the_form(self):
        response = self.client.get(self.doc.get_absolute_url())
        self.assertContains(response, f'href="{self.url}" data-modal')
        self.assertNotContains(response, "To the top")

    def test_clients_dont_move_what_staff_made(self):
        shared = ops.create_doc(
            project=self.project, title="Shared", creator=self.ada, parent=self.public
        )
        self.client.force_login(self.cleo)
        for headers in [{}, MODAL]:
            self.assertEqual(
                self.client.get(
                    f"/items/{shared.pk}/move/", headers=headers
                ).status_code,
                403,
            )
        self.assertNotContains(self.client.get(shared.get_absolute_url()), "/move/")
        self.assertEqual(self.client.get(self.url, headers=MODAL).status_code, 404)
