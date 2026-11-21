"""The sign-in setting per organization (specs/sso.md): admins only, with
the identity provider's details"""

import json

from django.test import TestCase, override_settings

from biwak.organizations import operations as org_ops
from biwak.organizations.models import Organization, SignIn
from biwak.test_utils import (
    MODAL,
    SSO_PROVIDERS,
    assert_modal,
    assert_modal_redirect,
    organization,
    person,
    sign_in_with,
)


TENANT = "3f2504e0-4f89-11d3-9a0c-0305e82c3301"


@override_settings(SOCIALACCOUNT_PROVIDERS=SSO_PROVIDERS)
class SignInSettingTest(TestCase):
    def setUp(self):
        self.root = person("Root", is_admin=True)
        self.ada = person("Ada")
        self.example = organization("Example Ltd", domains=["example.com"])
        self.url = f"/organizations/{self.example.pk}/sign-in/"

    def test_codes_by_default(self):
        self.assertEqual(self.example.signin, SignIn.CODES)
        self.assertEqual(self.example.sso, "")

    def test_the_own_organization_allows_google(self):
        """Today's Google sign-in for staff (decided 2026-11-21)"""
        own = Organization.objects.own()
        self.assertEqual(own.signin, SignIn.SSO_ALLOWED)
        self.assertEqual(own.sso, "google")

    def test_admins_only(self):
        self.client.force_login(self.ada)
        page = self.client.get(f"/organizations/{self.example.pk}/")
        self.assertContains(page, "Sign-in: codes and passkeys.")
        self.assertNotContains(page, self.url)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(
            self.client.post(
                self.url, {"signin": "sso_allowed", "idp": "google"}
            ).status_code,
            403,
        )
        with self.assertRaises(PermissionError):
            org_ops.set_signin(
                self.example, signin="sso_allowed", idp="google", actor=self.ada
            )
        self.example.refresh_from_db()
        self.assertEqual(self.example.signin, SignIn.CODES)

    def test_google_allowed(self):
        self.client.force_login(self.root)
        self.assertContains(
            self.client.get(f"/organizations/{self.example.pk}/"), self.url
        )
        assert_modal(
            self,
            self.client.get(self.url, headers=MODAL),
            title="Sign-in of Example Ltd",
        )
        response = self.client.post(
            self.url, {"signin": "sso_allowed", "idp": "google"}, headers=MODAL
        )
        assert_modal_redirect(self, response, f"/organizations/{self.example.pk}/")
        self.example.refresh_from_db()
        self.assertEqual(self.example.sso, "google")
        self.assertContains(
            self.client.get(f"/organizations/{self.example.pk}/"),
            "Sign-in: Google Workspace, codes and passkeys.",
        )

    def test_google_needs_domains(self):
        self.example.domains = []
        self.example.save()
        self.client.force_login(self.root)
        response = self.client.post(
            self.url, {"signin": "sso_required", "idp": "google"}, headers=MODAL
        )
        self.assertContains(response, "Workspace domains first")
        self.example.refresh_from_db()
        self.assertEqual(self.example.signin, SignIn.CODES)

    def test_microsoft_needs_its_tenant(self):
        self.client.force_login(self.root)
        for tenant, error in [
            ("", "tenant ID"),
            ("not-a-tenant", "looks like"),
            ("9188040d-6c67-4c5b-b112-36a304b66dad", "personal Microsoft accounts"),
        ]:
            with self.subTest(tenant=tenant):
                response = self.client.post(
                    self.url,
                    {"signin": "sso_allowed", "idp": "microsoft", "tenant_id": tenant},
                    headers=MODAL,
                )
                self.assertContains(response, error)
        response = self.client.post(
            self.url,
            {
                "signin": "sso_allowed",
                "idp": "microsoft",
                "tenant_id": TENANT.upper(),
            },
            headers=MODAL,
        )
        assert_modal_redirect(self, response)
        self.example.refresh_from_db()
        self.assertEqual(self.example.tenant_id, TENANT)
        self.assertEqual(self.example.sso, "microsoft")

    def test_sso_needs_a_provider(self):
        self.client.force_login(self.root)
        response = self.client.post(self.url, {"signin": "sso_allowed"}, headers=MODAL)
        self.assertContains(response, "Choose the identity provider")

    @override_settings(SOCIALACCOUNT_PROVIDERS={"google": {"APPS": []}})
    def test_only_providers_set_up(self):
        self.client.force_login(self.root)
        response = self.client.post(
            self.url, {"signin": "sso_allowed", "idp": "google"}, headers=MODAL
        )
        self.assertContains(response, "set up on this installation")

    def test_requiring_it_for_ones_own_organization(self):
        """Only after signing in through it: nobody locks themselves out"""
        own = Organization.objects.own()
        own.domains = ["example.org"]
        own.save()
        url = f"/organizations/{own.pk}/sign-in/"
        self.client.force_login(self.root)
        data = {"signin": "sso_required", "idp": "google"}
        self.assertContains(
            self.client.post(url, data, headers=MODAL),
            "Sign in with Google Workspace first",
        )
        sign_in_with(self.client, self.root, "microsoft")
        self.assertContains(
            self.client.post(url, data, headers=MODAL),
            "Sign in with Google Workspace first",
        )
        sign_in_with(self.client, self.root, "google")
        assert_modal_redirect(self, self.client.post(url, data, headers=MODAL))
        own.refresh_from_db()
        self.assertTrue(own.requires_sso)

    def test_domains_of_google_organizations_are_for_admins(self):
        org_ops.set_signin(
            self.example, signin="sso_allowed", idp="google", actor=self.root
        )
        edit = f"/organizations/{self.example.pk}/edit/"
        self.client.force_login(self.ada)
        self.assertContains(self.client.get(edit), "only admins change its domains")
        self.client.post(edit, {"name": "Example Ltd", "domains": "evil.example"})
        self.example.refresh_from_db()
        self.assertEqual(self.example.domains, ["example.com"])
        with self.assertRaises(PermissionError):
            org_ops.update_organization(
                self.example, domains=["evil.example"], actor=self.ada
            )
        # Merging adds domains too
        other = organization("Exmaple Ltd", domains=["evil.example"])
        response = self.client.post(
            f"/organizations/{other.pk}/merge/", {"into": self.example.pk}
        )
        self.assertContains(response, "Only admins change the domains")
        self.assertTrue(Organization.objects.filter(pk=other.pk).exists())
        # Admins do, but not to none
        self.client.force_login(self.root)
        self.client.post(
            edit, {"name": "Example Ltd", "domains": "example.com example.net"}
        )
        self.example.refresh_from_db()
        self.assertEqual(self.example.domains, ["example.com", "example.net"])
        response = self.client.post(edit, {"name": "Example Ltd", "domains": ""})
        self.assertContains(response, "needs its Google Workspace domains")

    def test_other_organizations_domains_stay_staffs(self):
        edit = f"/organizations/{self.example.pk}/edit/"
        self.client.force_login(self.ada)
        self.client.post(edit, {"name": "Example Ltd", "domains": "example.net"})
        self.example.refresh_from_db()
        self.assertEqual(self.example.domains, ["example.net"])

    def test_the_django_admin(self):
        self.client.force_login(self.root)
        url = f"/admin/organizations/organization/{self.example.pk}/change/"
        data = {
            "name": "Example Ltd",
            "domains": "example.com",
            "signin": "sso_required",
            "idp": "microsoft",
            "tenant_id": "",
        }
        self.assertContains(self.client.post(url, data), "tenant ID")
        data["tenant_id"] = TENANT
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.example.refresh_from_db()
        self.assertTrue(self.example.requires_sso)
        self.assertEqual(self.example.sso, "microsoft")

    def test_the_api_shows_it(self):
        org_ops.set_signin(
            self.example, signin="sso_required", idp="google", actor=self.root
        )
        self.client.force_login(self.ada)
        data = json.loads(
            self.client.get(f"/api/v1/organizations/{self.example.pk}/").content
        )
        self.assertEqual((data["signin"], data["idp"]), ("sso_required", "google"))


class MigrationTest(TestCase):
    def test_google_for_staff_becomes_the_own_organizations_setting(self):
        """Without domains, those of its active staff's addresses, not
        free-mail domains or other organizations'"""
        from importlib import import_module

        from django.apps import apps

        from biwak.accounts.models import User

        migration = import_module(
            "biwak.organizations.migrations.0005_own_organization_google"
        )
        own = Organization.objects.own()
        own.signin, own.idp, own.domains = SignIn.CODES, "", []
        own.save()
        person("Ada")
        person("Ben", is_active=False, organization=own)
        User.objects.create_user("gus@gmail.com", organization=own)
        User.objects.create_user("ines@example.net", organization=own)
        organization("Example Ltd", domains=["example.net"])
        migration.own_organization_google(apps, None)
        own.refresh_from_db()
        self.assertEqual((own.signin, own.idp), (SignIn.SSO_ALLOWED, "google"))
        self.assertEqual(own.domains, ["example.org"])
        # Domains it has stay
        own.domains = ["example.com"]
        own.save()
        migration.own_organization_google(apps, None)
        own.refresh_from_db()
        self.assertEqual(own.domains, ["example.com"])
