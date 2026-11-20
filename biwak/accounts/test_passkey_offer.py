"""The offer to add a passkey after logging in by code (specs/access.md):
until the person dismisses it or adds a passkey"""

import re

from allauth.mfa.models import Authenticator
from allauth.mfa.signals import authenticator_added
from django.core import mail
from django.core.cache import cache
from django.test import TestCase

from biwak.accounts import passkeys
from biwak.test_utils import person


OFFER = "/accounts/passkey-offer/"


class PasskeyOfferTest(TestCase):
    def setUp(self):
        cache.clear()  # the rate limits of login codes
        self.ada = person("Ada")

    def login_by_code(self):
        mail.outbox.clear()
        self.client.post("/accounts/login/code/", {"email": self.ada.email})
        code = re.search(r"\b([A-Z0-9]{4}-[A-Z0-9]{4})\b", mail.outbox[-1].body).group(
            1
        )
        response = self.client.post("/accounts/login/code/confirm/", {"code": code})
        self.assertEqual(response.status_code, 302, response.content)

    def test_offered_after_login_by_code(self):
        self.login_by_code()
        response = self.client.get("/")
        self.assertRedirects(response, f"{OFFER}?next=/", fetch_redirect_response=False)
        page = self.client.get(response["Location"])
        self.assertContains(page, "passkey")
        self.assertContains(page, "/accounts/2fa/webauthn/add/")
        # Once per login: the page is not offered again right away
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_dismissing_stops_it_for_good(self):
        self.login_by_code()
        response = self.client.post(f"{OFFER}?next=/")
        self.assertRedirects(response, "/", fetch_redirect_response=False)
        self.ada.refresh_from_db()
        self.assertTrue(self.ada.passkey_offer_done)
        self.client.logout()
        self.login_by_code()
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_not_dismissed_comes_back_with_the_next_login(self):
        self.login_by_code()
        self.client.get("/")
        self.client.logout()
        self.login_by_code()
        self.assertEqual(self.client.get("/").status_code, 302)

    def test_adding_a_passkey_stops_it(self):
        authenticator = Authenticator.objects.create(
            user=self.ada, type=Authenticator.Type.WEBAUTHN, data={}
        )
        authenticator_added.send(
            sender=Authenticator,
            request=None,
            user=self.ada,
            authenticator=authenticator,
        )
        self.ada.refresh_from_db()
        self.assertTrue(self.ada.passkey_offer_done)
        # Logging in by code later doesn't set the flag (and nobody checks)
        self.assertFalse(passkeys.offer_due(self.ada))

    def test_people_with_a_passkey_arent_asked(self):
        self.login_by_code()
        Authenticator.objects.create(
            user=self.ada, type=Authenticator.Type.WEBAUTHN, data={}
        )
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_only_for_pages_people_look_at(self):
        self.login_by_code()
        for url, headers in [
            ("/api/v1/me/", {}),
            ("/", {"hx-request": "true"}),
            ("/accounts/2fa/", {}),
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url, headers=headers).status_code, 200)

    def test_other_logins_arent_offered(self):
        self.client.force_login(self.ada)
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_clients_too(self):
        cleo = person("Cleo", client=True)
        self.ada = cleo
        self.login_by_code()
        self.assertEqual(self.client.get("/").status_code, 302)

    def test_next_must_stay_here(self):
        self.login_by_code()
        response = self.client.post(f"{OFFER}?next=https://evil.example/")
        self.assertRedirects(response, "/", fetch_redirect_response=False)
