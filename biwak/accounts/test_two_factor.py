"""Passkeys as a way in, authenticator apps as an optional second factor
(specs/two-factor.md): every way in, with and without an app"""

import re
from types import SimpleNamespace
from unittest.mock import patch

from allauth.account.models import Login
from allauth.core.context import request_context
from allauth.mfa.models import Authenticator
from allauth.mfa.totp.internal.auth import (
    TOTP,
    format_hotp_value,
    generate_totp_secret,
    hotp_value,
    yield_hotp_counters_from_time,
)
from allauth.mfa.webauthn.internal.flows import perform_passwordless_login
from django.conf import settings
from django.contrib.auth import get_user
from django.contrib.auth.middleware import AuthenticationMiddleware
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.core import mail
from django.core.cache import cache
from django.test import RequestFactory, TestCase

from biwak.accounts.test_sso_social import SocialTestCase, google_claims
from biwak.test_utils import person


TWO_FACTOR = "/accounts/2fa/authenticate/"
RECENTLY = "allauth.account.internal.flows.reauthentication.did_recently_reauthenticate"


def passkey(user):
    return Authenticator.objects.create(
        user=user, type=Authenticator.Type.WEBAUTHN, data={"name": "Laptop"}
    )


def app(user):
    """An authenticator app, returning its secret"""
    secret = generate_totp_secret()
    TOTP.activate(user, secret)
    return secret


def code_for(secret):
    counter = next(iter(yield_hotp_counters_from_time()))
    return format_hotp_value(hotp_value(secret, counter))


def wrong_code(secret):
    """A code of the right shape the app doesn't show now"""
    right = code_for(secret)
    return next(c for c in ("000000", "111111") if c != right)


class SignInMixin:
    def login_by_code(self, user):
        """Asks for a code and enters it, returning the response"""
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post("/accounts/login/code/", {"email": user.email})
        code = re.search(r"\b([A-Z0-9]{4}-[A-Z0-9]{4})\b", mail.outbox[-1].body).group(
            1
        )
        return self.client.post("/accounts/login/code/confirm/", {"code": code})

    def login_by_passkey(self, user, authenticator):
        """allauth's passkey sign-in after the browser's assertion was
        verified (``perform_passwordless_login``)"""
        request = RequestFactory().get("/")
        for middleware in [
            SessionMiddleware,
            AuthenticationMiddleware,
            MessageMiddleware,
        ]:
            middleware(lambda r: None).process_request(request)
        with request_context(request):
            response = perform_passwordless_login(
                request, authenticator, Login(user=user)
            )
        request.user = get_user(request)
        return request, response

    def signed_in_as(self):
        return get_user(self.client)


class CodeAndPasskeyTest(SignInMixin, TestCase):
    def setUp(self):
        cache.clear()  # the rate limits, the codes used
        self.ada = person("Ada")

    def test_passkey_owners_sign_in_by_code_without_a_second_step(self):
        """The bug (2026-11-21): passkeys counted as a second factor"""
        passkey(self.ada)
        response = self.login_by_code(self.ada)
        self.assertEqual(response.status_code, 302)
        self.assertNotEqual(response["Location"], TWO_FACTOR)
        self.assertEqual(self.signed_in_as(), self.ada)
        # Nothing waits there either
        response = self.client.get(TWO_FACTOR)
        self.assertNotEqual(response.status_code, 200)

    def test_app_owners_are_asked_for_the_code_after_a_code(self):
        secret = app(self.ada)
        passkey(self.ada)
        response = self.login_by_code(self.ada)
        self.assertRedirects(response, TWO_FACTOR, fetch_redirect_response=False)
        self.assertFalse(self.signed_in_as().is_authenticated)
        page = self.client.get(TWO_FACTOR)
        self.assertContains(page, "authenticator app")
        self.assertContains(page, 'name="code"')
        # No passkey alternative there
        self.assertNotContains(page, "security key")
        self.assertNotContains(page, "webauthn")
        # Without the code, or a wrong one: not signed in
        response = self.client.post(TWO_FACTOR, {})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.signed_in_as().is_authenticated)
        response = self.client.post(TWO_FACTOR, {"code": wrong_code(secret)})
        self.assertContains(response, "Incorrect code.")
        self.assertFalse(self.signed_in_as().is_authenticated)
        response = self.client.post(TWO_FACTOR, {"code": code_for(secret)})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.signed_in_as(), self.ada)

    def test_a_code_works_once(self):
        secret = app(self.ada)
        code = code_for(secret)
        self.login_by_code(self.ada)
        self.client.post(TWO_FACTOR, {"code": code})
        self.assertEqual(self.signed_in_as(), self.ada)
        self.client.logout()
        self.login_by_code(self.ada)
        response = self.client.post(TWO_FACTOR, {"code": code})
        self.assertContains(response, "Incorrect code.")
        self.assertFalse(self.signed_in_as().is_authenticated)

    def test_a_passkey_is_enough_alone(self):
        app(self.ada)
        request, response = self.login_by_passkey(self.ada, passkey(self.ada))
        self.assertEqual(request.user, self.ada)
        self.assertNotEqual(response["Location"], TWO_FACTOR)

    def test_passkey_owners_without_an_app_too(self):
        request, _response = self.login_by_passkey(self.ada, passkey(self.ada))
        self.assertEqual(request.user, self.ada)

    def test_without_anything_no_second_step(self):
        response = self.login_by_code(self.ada)
        self.assertNotEqual(response["Location"], TWO_FACTOR)
        self.assertEqual(self.signed_in_as(), self.ada)


class GoogleTest(SignInMixin, SocialTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()

    def google(self):
        return self.sign_in(
            "google", google_claims("ada@example.org", hd="example.org")
        )

    def test_passkey_owners_sign_in_without_a_second_step(self):
        passkey(self.ada)
        request, response = self.google()
        self.assert_signed_in(request, self.ada)
        self.assertEqual(response["Location"], settings.LOGIN_REDIRECT_URL)

    def test_app_owners_are_asked_for_the_code(self):
        secret = app(self.ada)
        request, response = self.google()
        self.assertEqual(response["Location"], TWO_FACTOR)
        self.assertFalse(request.user.is_authenticated)
        # The browser goes on with the same session
        request.session.save()
        self.client.cookies[settings.SESSION_COOKIE_NAME] = request.session.session_key
        response = self.client.post(TWO_FACTOR, {"code": wrong_code(secret)})
        self.assertContains(response, "Incorrect code.")
        self.assertFalse(self.signed_in_as().is_authenticated)
        response = self.client.post(TWO_FACTOR, {"code": code_for(secret)})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.signed_in_as(), self.ada)


class SettingsTest(SignInMixin, TestCase):
    """Turning the app on and off in the settings' sign-in section"""

    def setUp(self):
        cache.clear()
        # Not the passkey offer after signing in by code
        self.ada = person("Ada", passkey_offer_done=True)

    def confirm_by_code(self, response):
        """allauth's reauthentication by a code by mail, then back"""
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/reauthenticate/code/", response["Location"])
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                response["Location"], {"recipient": self.ada.email}
            )
        code = re.search(r"\b([A-Z0-9]{4}-[A-Z0-9]{4})\b", mail.outbox[-1].body).group(
            1
        )
        self.assertIn("/accounts/reauthenticate/code/confirm/", response["Location"])
        return self.client.post(response["Location"], {"code": code}, follow=True)

    def test_turning_it_on(self):
        self.login_by_code(self.ada)
        page = self.client.get("/accounts/settings/")
        self.assertContains(page, 'id="authenticator-app"')
        self.assertContains(page, "/accounts/2fa/totp/activate/")
        # allauth confirms who it is first (by code or passkey)
        response = self.confirm_by_code(self.client.get("/accounts/2fa/totp/activate/"))
        self.assertContains(response, "data:image/svg+xml;base64,")
        response = self.client.get("/accounts/2fa/totp/activate/")
        self.assertContains(response, "data:image/svg+xml;base64,")
        secret = response.context["secret"]
        self.assertContains(response, secret)
        # A modal too
        modal = self.client.get(
            "/accounts/2fa/totp/activate/", headers={"HX-Modal": "true"}
        )
        self.assertNotContains(modal, "<html")
        secret = modal.context["secret"]
        response = self.client.post(
            "/accounts/2fa/totp/activate/", {"code": wrong_code(secret)}
        )
        self.assertContains(response, "Incorrect code.")
        self.assertFalse(Authenticator.objects.filter(user=self.ada).exists())
        response = self.client.post(
            "/accounts/2fa/totp/activate/", {"code": code_for(secret)}
        )
        self.assertRedirects(
            response, "/accounts/settings/#sign-in", fetch_redirect_response=False
        )
        authenticator = Authenticator.objects.get(user=self.ada)
        self.assertEqual(authenticator.type, Authenticator.Type.TOTP)
        # No recovery codes
        self.assertEqual(Authenticator.objects.filter(user=self.ada).count(), 1)
        self.assertContains(self.client.get("/accounts/settings/"), "Turn off…")
        # One app per person: the page leads back
        response = self.client.get("/accounts/2fa/totp/activate/")
        self.assertEqual(response.status_code, 302)
        # The next sign-in by code asks for it
        self.client.logout()
        cache.clear()
        response = self.login_by_code(self.ada)
        self.assertRedirects(response, TWO_FACTOR, fetch_redirect_response=False)

    def test_confirming_who_it_is_first(self):
        """allauth's reauthentication (by code or passkey), also right after
        signing in"""
        self.client.force_login(self.ada)
        response = self.client.get("/accounts/2fa/totp/activate/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/reauthenticate/", response["Location"])
        response = self.client.post("/accounts/2fa/totp/activate/", {"code": "1"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Authenticator.objects.filter(user=self.ada).exists())

    def test_turning_it_off_needs_its_code(self):
        secret = app(self.ada)
        passkey(self.ada)
        self.client.force_login(self.ada)
        url = "/accounts/2fa/totp/deactivate/"
        self.assertContains(self.client.get(url), 'name="code"')
        for data in [{}, {"code": wrong_code(secret)}]:
            with self.subTest(data=data):
                self.assertEqual(self.client.post(url, data).status_code, 200)
                self.assertTrue(
                    Authenticator.objects.filter(
                        user=self.ada, type=Authenticator.Type.TOTP
                    ).exists()
                )
        response = self.client.post(url, {"code": code_for(secret)})
        self.assertRedirects(
            response, "/accounts/settings/#sign-in", fetch_redirect_response=False
        )
        # The passkey stays
        self.assertEqual(
            list(
                Authenticator.objects.filter(user=self.ada).values_list(
                    "type", flat=True
                )
            ),
            [Authenticator.Type.WEBAUTHN],
        )
        self.assertContains(self.client.get("/accounts/settings/"), "Set up…")
        # Without an app, the page leads back
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_with_an_app_a_code_by_mail_doesnt_confirm(self):
        """Or a code by mail would turn the app off or add a passkey"""
        secret = app(self.ada)
        self.client.force_login(self.ada)
        response = self.client.get("/accounts/2fa/webauthn/add/")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            response["Location"].startswith("/accounts/2fa/reauthenticate/")
        )
        for url in [
            "/accounts/reauthenticate/code/",
            "/accounts/reauthenticate/code/confirm/",
        ]:
            with self.subTest(url=url):
                mail.outbox.clear()
                response = self.client.post(f"{url}?next=/accounts/settings/", {})
                self.assertRedirects(
                    response,
                    "/accounts/2fa/reauthenticate/?next=%2Faccounts%2Fsettings%2F",
                    fetch_redirect_response=False,
                )
                self.assertEqual(mail.outbox, [])
        page = self.client.get("/accounts/2fa/reauthenticate/")
        self.assertNotContains(page, "/accounts/reauthenticate/code/")
        response = self.client.post(
            "/accounts/2fa/reauthenticate/?next=/accounts/2fa/webauthn/add/",
            {"code": code_for(secret)},
        )
        self.assertRedirects(
            response, "/accounts/2fa/webauthn/add/", fetch_redirect_response=False
        )


class SSORequiredTest(SignInMixin, SocialTestCase):
    """Organizations requiring single sign-on: no authenticator apps (the
    identity provider does that)"""

    def setUp(self):
        super().setUp()
        cache.clear()

    def test_switching_deletes_apps_and_never_offers_them(self):
        app(self.cleo)
        self.set_signin(self.acme, "sso_required", "google")
        self.assertFalse(Authenticator.objects.filter(user=self.cleo).exists())
        request, response = self.sign_in(
            "google", google_claims("cleo@acme.example", hd="acme.example")
        )
        self.assert_signed_in(request, self.cleo)
        request.session.save()
        self.client.cookies[settings.SESSION_COOKIE_NAME] = request.session.session_key
        page = self.client.get("/accounts/settings/")
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, 'id="authenticator-app"')
        response = self.client.get("/accounts/2fa/totp/activate/")
        self.assertRedirects(
            response, "/accounts/settings/#sign-in", fetch_redirect_response=False
        )
        self.client.post("/accounts/2fa/totp/activate/", {"code": "123456"})
        self.assertFalse(Authenticator.objects.filter(user=self.cleo).exists())

    def test_no_second_step_for_them(self):
        """Should an app come through anyway (made before the switch, by a
        request that didn't see it yet), the identity provider is enough"""
        self.set_signin(self.acme, "sso_required", "google")
        app(self.cleo)
        request, response = self.sign_in(
            "google", google_claims("cleo@acme.example", hd="acme.example")
        )
        self.assert_signed_in(request, self.cleo)
        self.assertNotEqual(response["Location"], TWO_FACTOR)


class PasskeysArePasswordlessTest(TestCase):
    """ "Add a passkey" registers a passkey: discoverable, with the device's
    PIN or fingerprint (specs/two-factor.md); no "Passwordless" checkbox"""

    def setUp(self):
        self.ada = person("Ada", passkey_offer_done=True)
        self.client.force_login(self.ada)

    def test_the_page_asks_for_a_passkey(self):
        with patch(RECENTLY, return_value=True):
            response = self.client.get("/accounts/2fa/webauthn/add/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Passwordless")
        options = response.context["js_data"]["creation_options"]["publicKey"]
        selection = options["authenticatorSelection"]
        self.assertEqual(selection["residentKey"], "required")
        self.assertEqual(selection["userVerification"], "required")
        # allauth's script reads the box: always ticked, hidden
        self.assertInHTML(
            '<input type="checkbox" id="passkey-passwordless" checked hidden>',
            response.content.decode(),
        )

    def test_confirming_who_one_is_needs_the_pin_too(self):
        """Confirming who one is with a passkey asks for the PIN or
        fingerprint, as signing in does (decided 2026-11-22,
        ``MFA_WEBAUTHN_USER_VERIFICATION``)"""
        passkey(self.ada)
        # The made-up passkey has no key to offer
        with patch(
            "allauth.mfa.webauthn.internal.auth.get_credentials", return_value=[]
        ):
            response = self.client.get("/accounts/2fa/webauthn/reauthenticate/")
        self.assertEqual(response.status_code, 200)
        options = response.context["js_data"]["request_options"]["publicKey"]
        self.assertEqual(options["userVerification"], "required")

    def test_a_key_without_user_verification_is_refused(self):
        from biwak.accounts.signin import AddPasskeyForm

        binding = SimpleNamespace(is_user_verified=lambda: False)
        with (
            patch("allauth.mfa.webauthn.internal.auth.parse_registration_response"),
            patch(
                "allauth.mfa.webauthn.internal.auth.complete_registration",
                return_value=binding,
            ),
        ):
            form = AddPasskeyForm(
                user=self.ada, data={"name": "Key", "credential": '{"id": "x"}'}
            )
            self.assertFalse(form.is_valid())
            binding.is_user_verified = lambda: True
            form = AddPasskeyForm(
                user=self.ada, data={"name": "Key", "credential": '{"id": "x"}'}
            )
            self.assertTrue(form.is_valid(), form.errors)
