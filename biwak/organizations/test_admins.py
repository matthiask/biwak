"""Admins are always the installation's own staff (decided 2026-11-21):
every change that would make an admin a partner is refused, with what to
do first"""

from django.core.exceptions import ValidationError
from django.test import TestCase

from biwak.accounts.models import APIToken
from biwak.organizations import operations as org_ops
from biwak.organizations.models import Organization
from biwak.test_utils import organization, partner, person


class AdminsTest(TestCase):
    def setUp(self):
        self.own = organization("Example Team", is_own=True)
        self.root = person("Root", is_admin=True, organization=self.own)
        self.other_admin = person("Ora", is_admin=True)  # without one: own
        self.agency = organization("Example Agency")

    def test_no_admin_partners(self):
        pia = partner("Pia")
        pia.is_admin = True
        with self.assertRaisesMessage(ValidationError, "partner"):
            pia.full_clean()

    def test_the_django_admin_refuses_ticking_admin_on_a_partner(self):
        pia = partner("Pia")
        self.client.force_login(self.root)
        response = self.client.post(
            f"/admin/accounts/user/{pia.pk}/change/",
            {
                "email": pia.email,
                "full_name": pia.full_name,
                "short_name": "",
                "language": "",
                "organization": pia.organization_id,
                "is_active": "on",
                "is_admin": "on",
            },
        )
        self.assertEqual(response.status_code, 200)
        pia.refresh_from_db()
        self.assertFalse(pia.is_admin)

    def test_moving_an_admin_into_another_organization(self):
        with self.assertRaisesMessage(ValidationError, "no admin"):
            org_ops.set_organization(self.root, self.agency, actor=self.root)
        with self.assertRaisesMessage(ValidationError, "no admin"):
            org_ops.set_organization(self.other_admin, self.agency, actor=self.root)
        self.root.refresh_from_db()
        self.assertEqual(self.root.organization, self.own)
        # Into the own one is fine
        org_ops.set_organization(self.other_admin, self.own, actor=self.root)

    def test_through_the_api_and_the_page(self):
        _token, secret = APIToken.create_for(user=self.root, title="T", access="write")
        response = self.client.put(
            f"/api/v1/people/{self.other_admin.pk}/organization/",
            {"organization_id": self.agency.pk},
            content_type="application/json",
            headers={"authorization": f"Bearer {secret}"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("no admin", response.json()["detail"])
        self.client.force_login(self.root)
        response = self.client.post(
            f"/people/{self.other_admin.pk}/organization/",
            {"organization": "Example Agency"},
        )
        self.assertContains(response, "no admin")

    def test_merging_the_own_one_away(self):
        with self.assertRaisesMessage(ValidationError, "no admin"):
            org_ops.merge(self.own, self.agency, actor=self.root)
        self.assertTrue(Organization.objects.filter(pk=self.own.pk).exists())
        self.client.force_login(self.root)
        response = self.client.post(
            f"/organizations/{self.own.pk}/merge/", {"into": self.agency.pk}
        )
        self.assertContains(response, "no admin")

    def test_moving_or_removing_the_mark(self):
        for org in [self.agency, None]:
            with (
                self.subTest(org=org),
                self.assertRaisesMessage(ValidationError, "no admin"),
            ):
                org_ops.mark_own(org, actor=self.root)
        self.own.refresh_from_db()
        self.assertTrue(self.own.is_own)
        # In the Django admin too
        self.client.force_login(self.root)
        response = self.client.post(
            f"/admin/organizations/organization/{self.own.pk}/change/",
            {"name": "Example Team", "domains": ""},
        )
        self.assertEqual(response.status_code, 200)
        self.own.refresh_from_db()
        self.assertTrue(self.own.is_own)
        # Once the admins are in the other one, the mark moves
        org_ops.set_organization(self.root, None, actor=self.root)
        org_ops.mark_own(self.agency, actor=self.root)
        self.assertEqual(Organization.objects.get(is_own=True), self.agency)
