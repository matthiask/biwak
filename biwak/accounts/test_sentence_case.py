"""allauth's pages we show say things in sentence case like the rest of
Biwak ("Sign in", "Remember me"), not in allauth's title case (fixed
2026-11-22)"""

import re
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.template.loader import render_to_string
from django.test import Client, RequestFactory, TestCase

from biwak.accounts.test_two_factor import app, passkey
from biwak.test_utils import person


# Two or more capitalized words in a row: "Sign In", "Remember Me",
# "Confirm Access", "Enter Sign-In Code"
TITLE_CASE = re.compile(r"\b[A-Z][a-z]+(?:[- ](?:[A-Z][a-z]*|In|Up|Out|Me))+\b")
# Names, not title case
NAMES = {"Ada Example"}


def title_case(html):
    """The title-case phrases of the page's ``<main>`` and ``<title>``"""
    title = re.search(r"<title>(.*?)</title>", html, re.DOTALL)
    main = html.split("<main", 1)[-1]
    text = re.sub(r"<[^>]+>", " ", (title[1] if title else "") + " " + main)
    return set(TITLE_CASE.findall(text)) - NAMES


class SentenceCaseTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")

    def assert_sentence_case(self, response, *expected):
        self.assertEqual(response.status_code, 200)
        html = response.content.decode() if hasattr(response, "content") else response
        self.assertEqual(title_case(html), set())
        for text in expected:
            self.assertIn(text, html)

    def test_signing_in(self):
        client = Client()
        self.assert_sentence_case(
            client.get("/accounts/login/"), "Sign in", "Remember me"
        )
        self.assert_sentence_case(client.get("/accounts/login/code/"), "Sign in")
        client.post("/accounts/login/code/", {"email": self.ada.email})
        self.assert_sentence_case(
            client.get("/accounts/login/code/confirm/"), "Enter the sign-in code"
        )
        self.assert_sentence_case(client.get("/accounts/inactive/"))
        self.assert_sentence_case(client.get("/accounts/3rdparty/login/cancelled/"))
        self.assert_sentence_case(client.get("/accounts/signup/"))

    def test_signed_in(self):
        client = Client()
        client.force_login(self.ada)
        self.assert_sentence_case(client.get("/accounts/logout/"), "Sign out")
        self.assert_sentence_case(
            client.get("/accounts/reauthenticate/code/"), "Confirm access"
        )
        passkey(self.ada)
        app(self.ada)
        self.assert_sentence_case(client.get("/accounts/2fa/reauthenticate/"))
        with patch(
            "allauth.mfa.webauthn.internal.auth.get_credentials", return_value=[]
        ):
            self.assert_sentence_case(
                client.get("/accounts/2fa/webauthn/reauthenticate/")
            )

    def test_the_two_factor_step(self):
        request = self.request()
        html = render_to_string(
            "mfa/authenticate.html", {"form": None}, request=request
        )
        self.assertEqual(title_case(html), set())

    def request(self):
        request = RequestFactory().get("/")
        SessionMiddleware(lambda r: None).process_request(request)
        request.user = AnonymousUser()
        request._messages = FallbackStorage(request)
        return request

    def test_through_an_identity_provider(self):
        provider = SimpleNamespace(name="Google", id="google")
        for template, context in [
            ("socialaccount/login.html", {"provider": provider, "process": "login"}),
            ("socialaccount/authentication_error.html", {}),
            (
                "socialaccount/login_redirect.html",
                {"provider": provider, "redirect_to": "/"},
            ),
        ]:
            with self.subTest(template=template):
                html = render_to_string(template, context, request=self.request())
                self.assertEqual(title_case(html), set())
