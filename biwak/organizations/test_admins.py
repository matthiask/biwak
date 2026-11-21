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
        self.other_admin = person("Ora", is_admin=True)  # the own one too
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
        """It always exists, and with it the admins' place"""
        with self.assertRaisesMessage(ValidationError, "always exists"):
            org_ops.merge(self.own, self.agency, actor=self.root)
        self.assertTrue(Organization.objects.filter(pk=self.own.pk).exists())
        self.client.force_login(self.root)
        response = self.client.post(
            f"/organizations/{self.own.pk}/merge/", {"into": self.agency.pk}
        )
        self.assertContains(response, "always exists")

    def test_moving_or_removing_the_mark(self):
        with self.assertRaisesMessage(ValidationError, "no admin"):
            org_ops.mark_own(self.agency, actor=self.root)
        with self.assertRaisesMessage(ValidationError, "always"):
            org_ops.mark_own(None, actor=self.root)
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
        response = self.client.post(
            f"/admin/organizations/organization/{self.agency.pk}/change/",
            {"name": "Example Agency", "domains": "", "is_own": "on"},
        )
        self.assertContains(response, "no admin")
        self.assertEqual(Organization.objects.get(is_own=True), self.own)


class IndividualsTest(TestCase):
    """Staff without an organization are individuals, partners (decided
    2026-11-21); the installation's own organization always exists"""

    def test_staff_without_an_organization_are_partners(self):
        gus = person("Gus", organization=None)
        self.assertTrue(gus.is_partner)
        self.assertFalse(gus.sees_all_access)
        cleo = person("Cleo", client=True, organization=None)
        self.assertFalse(cleo.is_partner)

    def test_superusers_are_the_own_staff(self):
        from biwak.accounts.models import User

        root = User.objects.create_superuser("root@example.org")
        self.assertTrue(root.organization.is_own)
        self.assertEqual(Organization.objects.get(is_own=True).name, "Our organization")

    def test_inviting_staff_without_a_choice(self):
        from biwak.projects import operations as project_ops
        from biwak.test_utils import project

        root = person("Root", is_admin=True)
        camp = project("Camp", members=[root])
        gus, _created = project_ops.invite(
            camp, email="gus@example.net", is_client=False, actor=root
        )
        self.assertIsNone(gus.organization)
        self.assertTrue(gus.is_partner)
        own = Organization.objects.own()
        hal, _created = project_ops.invite(
            camp, email="hal@example.net", is_client=False, organization=own, actor=root
        )
        self.assertFalse(hal.is_partner)

    def test_the_migration(self):
        from importlib import import_module

        from django.apps import apps

        from biwak.accounts.models import User

        Organization.objects.filter(is_own=True).delete()
        bob = person("Bob", organization=None)
        cleo = person("Cleo", client=True, organization=None)
        migration = import_module(
            "biwak.organizations.migrations.0003_own_organization"
        )
        migration.own_organization(apps, None)
        own = Organization.objects.get(is_own=True)
        self.assertEqual(own.name, "Our organization")
        self.assertEqual(User.objects.get(pk=bob.pk).organization, own)
        self.assertIsNone(User.objects.get(pk=cleo.pk).organization)
