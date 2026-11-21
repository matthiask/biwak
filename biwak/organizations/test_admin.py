from django.test import TestCase

from biwak.organizations.models import Organization
from biwak.test_utils import organization, person


class AdminTest(TestCase):
    """The own organization is marked in the Django admin"""

    def setUp(self):
        self.root = person("Root", is_admin=True)
        self.own = organization("Example Team", is_own=True)
        self.other = organization("Example Agency")
        self.client.force_login(self.root)

    def test_marking_another_one_moves_the_mark(self):
        """Not while admins would be left out (here: Root)"""
        response = self.client.get("/admin/organizations/organization/")
        self.assertContains(response, "Example Agency")
        data = {
            "name": "Example Agency",
            "domains": "",
            "is_own": "on",
            "signin": "codes",
        }
        url = f"/admin/organizations/organization/{self.other.pk}/change/"
        self.assertContains(self.client.post(url, data), "no admin")
        new = person("Nia", is_admin=True, organization=self.other)
        self.root.is_admin = False
        self.root.save()
        self.client.force_login(new)
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(Organization.objects.get(is_own=True), self.other)

    def test_the_mark_isnt_removed(self):
        response = self.client.post(
            f"/admin/organizations/organization/{self.own.pk}/change/",
            {
                "name": "Example Team",
                "domains": "",
                "signin": "sso_allowed",
                "idp": "google",
            },
        )
        self.assertContains(response, "There is always your own organization")

    def test_people_pick_theirs(self):
        ada = person("Ada")
        response = self.client.get(f"/admin/accounts/user/{ada.pk}/change/")
        self.assertContains(response, 'name="organization"')
        response = self.client.get(
            "/admin/autocomplete/",
            {
                "term": "agency",
                "app_label": "accounts",
                "model_name": "user",
                "field_name": "organization",
            },
        )
        self.assertEqual(
            [r["text"] for r in response.json()["results"]], ["Example Agency"]
        )
