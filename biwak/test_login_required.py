"""Every page needs a login (``LoginRequired`` in biwak/accounts/middleware.py)
except the few which are public on purpose: a new public URL needs an entry
in ``PUBLIC``."""

import re
import uuid

from django.conf import settings
from django.shortcuts import resolve_url
from django.test import TestCase
from django.urls import URLPattern, URLResolver, get_resolver, resolve


# Our own views without a login, by route
PUBLIC = {
    "favicon.ico",
    "manifest.webmanifest",
    # The secret in the URL is the key
    "calendar/<str:token>.ics",
    "unsubscribe/<str:token>/",
    # Resend's webhook, signed
    "inbound/resend/",
    # allauth's password pages and managing one's addresses don't exist
    # (a 404, specs/sso.md)
    "^accounts/password/",
    "^accounts/email/",
    "^accounts/confirm-email/",
    # Django's, sending to the login
    "admin/login/",
    # The login pages, allauth's wrapped to send people of organizations
    # requiring single sign-on to their provider (specs/sso.md)
    "accounts/login/",
    "accounts/login/code/",
    # The two-factor step during a sign-in (allauth's, specs/two-factor.md)
    "accounts/2fa/authenticate/",
}

DUMMY = {"int": "1", "slug": "x", "str": "x", "path": "x", "uuid": str(uuid.uuid4())}


def patterns(resolvers, prefix=""):
    """``(route, pattern)`` of every URL"""
    for entry in resolvers:
        if isinstance(entry, URLResolver):
            yield from patterns(entry.url_patterns, prefix + str(entry.pattern))
        else:
            assert isinstance(entry, URLPattern)
            yield prefix + str(entry.pattern), entry


def is_public(pattern):
    return not getattr(pattern.callback, "login_required", True)


def url(route):
    """A path for ``route`` with made-up arguments, ``None`` for regular
    expressions"""
    if "^" in route or "(?P" in route:
        return None
    return "/" + re.sub(
        r"<(?:(\w+):)?\w+>", lambda m: DUMMY[m.group(1) or "str"], route
    )


class LoginRequiredTest(TestCase):
    def test_public_urls(self):
        """allauth's login pages and the list above, nothing else"""
        public = {
            route
            for route, pattern in patterns(get_resolver().url_patterns)
            if is_public(pattern)
            and not pattern.callback.__module__.startswith("allauth.")
        }
        self.assertEqual(public, PUBLIC)

    def test_anonymous_requests_go_to_the_login(self):
        login = resolve_url(settings.LOGIN_URL)
        checked = 0
        for route, pattern in patterns(get_resolver().url_patterns):
            # The API answers 401 itself (biwak/test_api.py)
            if is_public(pattern) or route.startswith("api/"):
                continue
            if (path := url(route)) is None:
                continue
            # allauth's password pages are behind our 404 (PUBLIC)
            if not getattr(resolve(path).func, "login_required", True):
                continue
            with self.subTest(route=route):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 302)
                # The admin's own views send to its login page
                targets = (
                    [login, "/admin/login/"] if route.startswith("admin/") else [login]
                )
                self.assertTrue(
                    any(
                        response["Location"].startswith(f"{target}?next=")
                        for target in targets
                    ),
                    response["Location"],
                )
                checked += 1
        self.assertGreater(checked, 100)

    def test_the_login_page_itself(self):
        login = resolve_url(settings.LOGIN_URL)
        self.assertEqual(self.client.get(login).status_code, 200)
