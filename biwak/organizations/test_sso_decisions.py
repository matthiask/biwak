"""Moving and merging with single sign-on (specs/sso.md, decided
2026-11-21)"""

from allauth.mfa.models import Authenticator
from django.test import TestCase, override_settings

from biwak.accounts.models import APIToken, User
from biwak.organizations import operations as org_ops
from biwak.organizations.models import Organization
from biwak.test_utils import MODAL, SSO_PROVIDERS, organization, person


TENANT = "3f2504e0-4f89-11d3-9a0c-0305e82c3301"


@override_settings(SOCIALACCOUNT_PROVIDERS=SSO_PROVIDERS)
class SSOTestCase(TestCase):
    def setUp(self):
        self.root = person("Root", is_admin=True)
        self.ada = person("Ada")
        self.acme = organization("Acme Ltd", domains=["acme.example"])
        self.other = organization("Acme Old", domains=["acme-old.example"])
        self.cleo = User.objects.create_user(
            "cleo@acme-old.example", is_client=True, organization=self.other
        )

    def set_signin(self, org, signin, idp="", tenant_id=""):
        org_ops.set_signin(
            org, signin=signin, idp=idp, tenant_id=tenant_id, actor=self.root
        )
        org.refresh_from_db()

    def api(self, user, path, data):
        _token, secret = APIToken.create_for(user=user, title="T", access="write")
        return self.client.post(
            f"/api/v1/{path}",
            data,
            content_type="application/json",
            headers={"authorization": f"Bearer {secret}"},
        )


class MovingOutTest(SSOTestCase):
    def test_out_of_required_is_for_admins(self):
        self.set_signin(self.other, "sso_required", "google")
        with self.assertRaises(PermissionError):
            org_ops.set_organization(self.cleo, self.acme, actor=self.ada)
        with self.assertRaises(PermissionError):
            org_ops.set_organization(self.cleo, None, actor=self.ada)
        self.client.force_login(self.ada)
        response = self.client.post(
            f"/people/{self.cleo.pk}/organization/",
            {"organization": "Acme Ltd"},
            headers=MODAL,
        )
        self.assertContains(response, "only admins move people out of it")
        response = self.client.put(
            f"/api/v1/people/{self.cleo.pk}/organization/",
            {"organization_id": self.acme.pk},
            content_type="application/json",
        )
        self.cleo.refresh_from_db()
        self.assertEqual(self.cleo.organization, self.other)
        org_ops.set_organization(self.cleo, self.acme, actor=self.root)
        self.cleo.refresh_from_db()
        self.assertEqual(self.cleo.organization, self.acme)

    def test_other_moves_unchanged(self):
        self.set_signin(self.other, "sso_allowed", "google")
        org_ops.set_organization(self.cleo, self.acme, actor=self.ada)
        self.cleo.refresh_from_db()
        self.assertEqual(self.cleo.organization, self.acme)


class MergingTest(SSOTestCase):
    def merge_page(self, user, data):
        self.client.force_login(user)
        return self.client.post(
            f"/organizations/{self.other.pk}/merge/", data, headers=MODAL
        )

    def test_the_same_setting_by_staff(self):
        for org in [self.other, self.acme]:
            self.set_signin(org, "sso_required", "microsoft", TENANT)
        org_ops.merge(self.other, self.acme, actor=self.ada)
        self.assertFalse(Organization.objects.filter(pk=self.other.pk).exists())

    def test_directions(self):
        cases = [
            # source, target: direction
            (("codes", ""), ("codes", ""), "same"),
            (("codes", ""), ("sso_allowed", "google"), "stricter"),
            (("codes", ""), ("sso_required", "google"), "stricter"),
            (("sso_allowed", "google"), ("sso_required", "google"), "stricter"),
            (("sso_allowed", "google"), ("sso_allowed", "microsoft"), "stricter"),
            (("sso_required", "google"), ("sso_allowed", "google"), "looser"),
            (("sso_allowed", "google"), ("codes", ""), "looser"),
        ]
        for source, target, direction in cases:
            with self.subTest(source=source, target=target):
                a = Organization(signin=source[0], idp=source[1], tenant_id=TENANT)
                b = Organization(signin=target[0], idp=target[1], tenant_id=TENANT)
                self.assertEqual(org_ops.merge_direction(a, b), direction)
        a = Organization(signin="sso_required", idp="microsoft", tenant_id=TENANT)
        b = Organization(
            signin="sso_required",
            idp="microsoft",
            tenant_id="11111111-2222-3333-4444-555555555555",
        )
        self.assertEqual(org_ops.merge_direction(a, b), "stricter")

    def test_stricter_is_for_admins_who_confirm(self):
        self.set_signin(self.acme, "sso_required", "google")
        Authenticator.objects.create(
            user=self.cleo, type=Authenticator.Type.WEBAUTHN, data={}
        )
        # Staff: no
        response = self.merge_page(self.ada, {"into": self.acme.pk, "confirm": "on"})
        self.assertContains(response, "only admins merge them")
        self.assertEqual(
            self.api(
                self.ada,
                f"organizations/{self.other.pk}/merge/",
                {"into_id": self.acme.pk, "confirm": True},
            ).status_code,
            403,
        )
        # Admins: the warning first, with the box
        response = self.merge_page(self.root, {"into": self.acme.pk})
        self.assertContains(response, "their passkeys are removed")
        self.assertContains(response, "sign-in codes are refused")
        self.assertContains(response, "calendar links are deleted")
        self.assertContains(response, 'type="checkbox" name="confirm"')
        self.assertTrue(Organization.objects.filter(pk=self.other.pk).exists())
        response = self.api(
            self.root,
            f"organizations/{self.other.pk}/merge/",
            {"into_id": self.acme.pk},
        )
        self.assertEqual(response.status_code, 400)
        # Confirmed
        response = self.merge_page(self.root, {"into": self.acme.pk, "confirm": "on"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("HX-Redirect", response.headers)
        self.cleo.refresh_from_db()
        self.assertEqual(self.cleo.organization, self.acme)
        self.assertFalse(Authenticator.objects.filter(user=self.cleo).exists())

    def test_looser_is_refused(self):
        self.set_signin(self.other, "sso_required", "google")
        response = self.merge_page(self.root, {"into": self.acme.pk, "confirm": "on"})
        self.assertContains(response, "change its sign-in first")
        response = self.api(
            self.root,
            f"organizations/{self.other.pk}/merge/",
            {"into_id": self.acme.pk, "confirm": True},
        )
        self.assertEqual(response.status_code, 400)
        self.assertTrue(Organization.objects.filter(pk=self.other.pk).exists())
