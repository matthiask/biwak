from django.test import TestCase
from django.urls import reverse

from biwak.items import operations as ops
from biwak.test_utils import MODAL, assert_modal_redirect, person, project


class ModalMiddlewareTest(TestCase):
    def test_a_redirect_of_a_modal_request_is_an_hx_redirect(self):
        """``fetch`` follows redirects itself, so the dialog's requests get
        the target in a header, also the login's"""
        response = self.client.get("/projects/1/lists/new/", headers=MODAL)
        assert_modal_redirect(self, response)
        self.assertIn("/accounts/login/", response.headers["HX-Redirect"])

    def test_other_requests_redirect_as_usual(self):
        response = self.client.get("/projects/1/lists/new/")
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("HX-Redirect", response.headers)

    def test_the_context_says_whether_it_is_a_modal(self):
        ada = person("Ada")
        camp = project(members=[ada])
        self.client.force_login(ada)
        url = f"/projects/{camp.pk}/lists/new/"
        self.assertTrue(self.client.get(url, headers=MODAL).context["modal"])
        self.assertFalse(self.client.get(url).context["modal"])

    def test_the_client_banner_in_the_dialog(self):
        """On visible items, as on the form's page"""
        ada = person("Ada")
        camp = project(members=[ada])
        shared = ops.create_list(
            project=camp, title="Shared", creator=ada, visible=True
        )
        internal = ops.create_list(project=camp, title="Internal", creator=ada)
        self.client.force_login(ada)
        for item, shown in [(shared, True), (internal, False)]:
            url = reverse("item_notifications", args=[item.pk])
            response = self.client.get(url, headers=MODAL)
            self.assertNotContains(response, "<html")
            self.assertEqual("wb-client-banner" in response.content.decode(), shown)
