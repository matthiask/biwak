"""Organizations requiring a second factor (specs/two-factor.md): a passkey
or the organization's identity provider is enough, a code needs the app's
code, people with neither set one up before anything else"""

from allauth.mfa.models import Authenticator
from django.conf import settings
from django.core.cache import cache
from django.test import Client

from biwak.accounts import sso
from biwak.accounts.test_sso_social import SocialTestCase, google_claims
from biwak.accounts.test_two_factor import (
    TWO_FACTOR,
    SignInMixin,
    app,
    code_for,
    passkey,
)
from biwak.organizations import activation, operations as org_ops


SETUP = "/accounts/two-factor/"


class RequiredTest(SignInMixin, SocialTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        for user in [self.ada, self.cleo]:
            user.passkey_offer_done = True
            user.save()
        self.require()

    def require(self, signin="codes", idp="", *, two_factor=True):
        org_ops.set_signin(
            self.acme, signin=signin, idp=idp, two_factor=two_factor, actor=self.root
        )
        self.acme.refresh_from_db()

    def use_session(self, request):
        """The browser goes on with the session of a sign-in made by
        ``sign_in()`` or ``login_by_passkey()``"""
        request.session.save()
        self.client.cookies[settings.SESSION_COOKIE_NAME] = request.session.session_key

    def assert_setup_first(self):
        response = self.client.get("/projects/")
        self.assertRedirects(
            response, f"{SETUP}?next=%2Fprojects%2F", fetch_redirect_response=False
        )

    def assert_free(self):
        self.assertEqual(self.client.get("/projects/").status_code, 200)

    def test_the_setting(self):
        self.assertTrue(self.acme.two_factor_required)
        self.client.force_login(self.root)
        page = self.client.get(f"/organizations/{self.acme.pk}/")
        self.assertContains(page, "A second factor is required")
        response = self.client.get(f"/api/v1/organizations/{self.acme.pk}/")
        self.assertTrue(response.json()["requires_two_factor"])
        # Changed on the page, by admins
        self.client.post(f"/organizations/{self.acme.pk}/sign-in/", {"signin": "codes"})
        self.acme.refresh_from_db()
        self.assertFalse(self.acme.requires_two_factor)
        self.client.post(
            f"/organizations/{self.acme.pk}/sign-in/",
            {"signin": "codes", "two_factor": "on"},
        )
        self.acme.refresh_from_db()
        self.assertTrue(self.acme.requires_two_factor)
        self.client.force_login(self.ada)
        self.assertEqual(
            self.client.post(
                f"/organizations/{self.acme.pk}/sign-in/", {"signin": "codes"}
            ).status_code,
            403,
        )
        with self.assertRaises(PermissionError):
            org_ops.set_signin(
                self.acme, signin="codes", two_factor=False, actor=self.ada
            )

    def test_switching_it_on_tells_open_websockets(self):
        """They check ``sso.session_alive()`` again, as for "SSO required"
        (saving the organization tells its people, ``collab.signals``)"""
        from unittest.mock import patch

        self.require(two_factor=False)
        with patch("biwak.collab.live.check_access") as check:
            self.require()
        check.assert_any_call(user=self.cleo.pk)
        self.assertNotIn(((), {"user": self.ada.pk}), check.call_args_list)

    def test_neither_sets_one_up_first(self):
        response = self.login_by_code(self.cleo)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.signed_in_as(), self.cleo)
        self.assert_setup_first()
        page = self.client.get(SETUP)
        self.assertContains(page, "Add a passkey")
        self.assertContains(page, "/accounts/2fa/totp/activate/")
        # The API with this session, htmx, websockets: nothing either
        self.assertEqual(self.client.get("/api/v1/me/").status_code, 403)
        response = self.client.get("/projects/", headers={"HX-Request": "true"})
        self.assertEqual(response["HX-Redirect"], f"{SETUP}?next=%2Fprojects%2F")
        key = self.client.session.session_key
        self.assertFalse(sso.session_alive(key, self.cleo))
        # What setting one up needs works
        self.assertEqual(self.client.get("/help/sign-in/").status_code, 200)
        response = self.client.get("/accounts/2fa/totp/activate/")
        self.assertIn("/accounts/reauthenticate/code/", response["Location"])
        # Once there's one, everything is open
        passkey(self.cleo)
        self.assert_free()
        self.assertTrue(sso.session_alive(key, self.cleo))
        response = self.client.get(f"{SETUP}?next=/projects/")
        self.assertRedirects(response, "/projects/", fetch_redirect_response=False)

    def test_an_app_also_opens_everything(self):
        self.login_by_code(self.cleo)
        self.assert_setup_first()
        app(self.cleo)
        self.assert_free()

    def test_switching_it_on_with_people_who_have_neither(self):
        self.require(two_factor=False)
        self.client.force_login(self.cleo)
        self.assert_free()
        self.require()
        self.assert_setup_first()
        # Others aren't affected
        other = Client()
        other.force_login(self.ada)
        self.assertEqual(other.get("/projects/").status_code, 200)
        self.require(two_factor=False)
        self.assert_free()

    def test_app_owners_get_the_step_after_a_code(self):
        secret = app(self.cleo)
        response = self.login_by_code(self.cleo)
        self.assertRedirects(response, TWO_FACTOR, fetch_redirect_response=False)
        self.assertFalse(self.signed_in_as().is_authenticated)
        self.client.post(TWO_FACTOR, {"code": code_for(secret)})
        self.assertEqual(self.signed_in_as(), self.cleo)
        self.assert_free()

    def test_passkey_owners_cant_sign_in_by_code_alone(self):
        passkey(self.cleo)
        response = self.login_by_code(self.cleo)
        self.assertRedirects(
            response, "/accounts/login/", fetch_redirect_response=False
        )
        self.assertFalse(self.signed_in_as().is_authenticated)
        page = self.client.get("/accounts/login/")
        self.assertContains(page, "requires a second factor: sign in with your passkey")

    def test_a_passkey_is_enough(self):
        request, _response = self.login_by_passkey(self.cleo, passkey(self.cleo))
        self.assertEqual(request.user, self.cleo)
        self.use_session(request)
        self.assert_free()

    def test_the_identity_provider_is_enough(self):
        self.acme.signin = "sso_allowed"
        self.acme.idp = "google"
        self.acme.save()
        request, response = self.sign_in(
            "google", google_claims("cleo@acme.example", hd="acme.example")
        )
        self.assert_signed_in(request, self.cleo)
        self.assertNotEqual(response["Location"], TWO_FACTOR)
        self.use_session(request)
        self.assert_free()
        self.assertTrue(sso.session_alive(request.session.session_key, self.cleo))
        # Also for passkey owners
        passkey(self.cleo)
        request, _response = self.sign_in(
            "google", google_claims("cleo@acme.example", hd="acme.example")
        )
        self.assert_signed_in(request, self.cleo)

    def test_moot_where_single_sign_on_is_required(self):
        self.require("sso_required", "google", two_factor=True)
        self.assertTrue(self.acme.requires_two_factor)
        self.assertFalse(self.acme.two_factor_required)
        request, _response = self.sign_in(
            "google", google_claims("cleo@acme.example", hd="acme.example")
        )
        self.assert_signed_in(request, self.cleo)
        self.use_session(request)
        self.assert_free()

    def test_after_a_reset(self):
        app(self.cleo)
        activation.reset_two_factor(self.cleo, actor=self.ada)
        self.assertFalse(Authenticator.objects.filter(user=self.cleo).exists())
        response = self.login_by_code(self.cleo)
        self.assertNotEqual(response["Location"], TWO_FACTOR)
        self.assert_setup_first()

    def test_other_organizations_keep_codes(self):
        response = self.login_by_code(self.ada)
        self.assertEqual(self.signed_in_as(), self.ada)
        self.assertNotEqual(response["Location"], TWO_FACTOR)
        self.assert_free()

    def test_gmail_isnt_the_identity_provider(self):
        """A personal Gmail account signing in with Google where the
        organization allows Google isn't its Workspace: it doesn't meet the
        requirement"""
        self.require("sso_allowed", "google")
        gus = self.client_person("Gus", self.acme, "gus@gmail.com")
        gus.passkey_offer_done = True
        gus.save()
        request, response = self.sign_in("google", google_claims("gus@gmail.com"))
        self.assert_signed_in(request, gus)
        self.use_session(request)
        self.assert_setup_first()
        self.assertFalse(sso.session_alive(request.session.session_key, gus))
        # With only a passkey: refused, as by code
        passkey(gus)
        request, response = self.sign_in("google", google_claims("gus@gmail.com"))
        self.assert_refused(request, response, "sign in with your passkey")

    def test_the_identity_provider_counts_as_the_organization_is_now(self):
        self.require("sso_allowed", "google")
        request, _response = self.sign_in(
            "google", google_claims("cleo@acme.example", hd="acme.example")
        )
        self.assert_signed_in(request, self.cleo)
        self.use_session(request)
        self.assert_free()
        # The domain isn't the organization's any more
        self.acme.domains = ["acme.test"]
        self.acme.save()
        self.assert_setup_first()
