"""A mail to the person when a passkey is added or removed and when the
authenticator app is turned on or off (specs/two-factor.md, decided
2026-11-21), so a change they didn't make is noticed"""

from types import SimpleNamespace
from unittest.mock import patch

from allauth.mfa.models import Authenticator
from django.core import mail
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from biwak.accounts.test_two_factor import app, code_for, passkey
from biwak.outbox.models import Kind, OutgoingMail
from biwak.test_utils import person


RECENT = "allauth.account.internal.flows.reauthentication.did_recently_reauthenticate"


class SecurityMailTest(TestCase):
    def setUp(self):
        cache.clear()
        self.ada = person("Ada", passkey_offer_done=True)
        self.client.force_login(self.ada)

    def assert_mailed(self, subject, text):
        self.assertEqual(len(mail.outbox), 1, [m.subject for m in mail.outbox])
        message = mail.outbox[0]
        self.assertEqual(message.to, [self.ada.email])
        self.assertEqual(message.subject, subject)
        self.assertIn(text, message.body)
        self.assertIn("tell an admin", message.body)
        self.assertIn(str(timezone.localtime().year), message.body)
        self.assertEqual(OutgoingMail.objects.get().kind, Kind.ACCOUNT)

    def test_a_passkey_added(self):
        from allauth.core.context import request_context
        from allauth.mfa.webauthn.internal import flows
        from django.test import RequestFactory

        request = RequestFactory().post("/accounts/2fa/webauthn/add/")
        request.user = self.ada
        request.session = self.client.session
        request._messages = SimpleNamespace(add=lambda *args, **kwargs: None)
        key = passkey(self.ada)
        with (
            patch(RECENT, return_value=True),
            patch(
                "allauth.mfa.webauthn.internal.auth.WebAuthn.add",
                return_value=SimpleNamespace(instance=key),
            ),
            request_context(request),
            self.captureOnCommitCallbacks(execute=True),
        ):
            flows.add_authenticator(request, "Laptop", {})
        self.assert_mailed(
            "A passkey was added to your Biwak account", "A passkey was added"
        )

    def test_a_passkey_removed(self):
        key = passkey(self.ada)
        with (
            patch(RECENT, return_value=True),
            self.captureOnCommitCallbacks(execute=True),
        ):
            self.client.post(f"/accounts/2fa/webauthn/keys/{key.pk}/remove/")
        self.assertFalse(Authenticator.objects.exists())
        self.assert_mailed(
            "A passkey was removed from your Biwak account", "A passkey was removed"
        )

    def test_the_app_turned_on(self):
        with patch(RECENT, return_value=True):
            secret = self.client.get("/accounts/2fa/totp/activate/").context["secret"]
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(
                    "/accounts/2fa/totp/activate/", {"code": code_for(secret)}
                )
        self.assertTrue(Authenticator.objects.exists())
        self.assert_mailed(
            "The authenticator app of your Biwak account was turned on",
            "An authenticator app was turned on",
        )

    def test_the_app_turned_off(self):
        secret = app(self.ada)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                "/accounts/2fa/totp/deactivate/", {"code": code_for(secret)}
            )
        self.assertFalse(Authenticator.objects.exists())
        self.assert_mailed(
            "The authenticator app of your Biwak account was turned off",
            "The authenticator app was turned off",
        )
