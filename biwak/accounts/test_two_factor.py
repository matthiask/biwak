"""Passkeys as a way in, authenticator apps as an optional second factor
(specs/two-factor.md): every way in, with and without an app"""

import re

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
