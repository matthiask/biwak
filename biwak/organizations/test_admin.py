from django.test import TestCase

from biwak.organizations.models import Organization
from biwak.test_utils import organization, person


class AdminTest(TestCase):
    """The installation's own organization is marked in the Django admin"""

    def setUp(self):
        self.root = person("Root", is_admin=True)
        self.own = organization("Example Team", is_own=True)
        self.other = organization("Example Agency")
        self.client.force_login(self.root)

    def test_marking_another_one_moves_the_mark(self):
        response = self.client.get("/admin/organizations/organization/")
        self.assertContains(response, "Example Agency")
        response = self.client.post(
            f"/admin/organizations/organization/{self.other.pk}/change/",
            {"name": "Example Agency", "domains": "", "is_own": "on"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Organization.objects.get(is_own=True), self.other)

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
