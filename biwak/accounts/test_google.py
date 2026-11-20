"""Google sign-in is for staff only (specs/access.md)"""

from allauth.core.context import request_context
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import get_adapter
from allauth.socialaccount.helpers import complete_social_login
from allauth.socialaccount.models import SocialAccount
from django.conf import settings
from django.contrib.auth import get_user
from django.contrib.auth.middleware import AuthenticationMiddleware
from django.contrib.messages import get_messages
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase, override_settings

from biwak.test_utils import person


GOOGLE = {
    "google": {
        "APPS": [{"client_id": "id", "secret": "secret"}],
        "SCOPE": ["profile", "email"],
    }
}


@override_settings(SOCIALACCOUNT_PROVIDERS=GOOGLE)
class GoogleSignInTest(TestCase):
    def sign_in(self, email, uid="1234"):
        """What Google's callback does: completes a social login for the
        verified address"""
        request = RequestFactory().get("/accounts/google/login/callback/")
        for middleware in [
            SessionMiddleware,
            AuthenticationMiddleware,
            MessageMiddleware,
        ]:
            middleware(lambda r: None).process_request(request)
        with request_context(request):
            app = get_adapter().get_app(request, "google")
            provider = app.get_provider(request)
            sociallogin = provider.sociallogin_from_response(
                request,
                {
                    "id": uid,
                    "email": email,
                    "verified_email": True,
                    "name": "Somebody",
                },
            )
            try:
                response = complete_social_login(request, sociallogin)
            except ImmediateHttpResponse as exc:
                response = exc.response
        request.user = get_user(request)
        return request, response

    def test_staff_sign_in_with_a_matching_address(self):
        ada = person("Ada")
        request, response = self.sign_in("ada@example.org")
        self.assertEqual(request.user, ada)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], settings.LOGIN_REDIRECT_URL)

    def test_clients_cant_sign_in_with_google(self):
        cleo = person("Cleo", client=True)
        request, response = self.sign_in("cleo@example.org")
        self.assertFalse(request.user.is_authenticated)
        self.assertFalse(SocialAccount.objects.exists())
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])
        messages = [str(m) for m in get_messages(request)]
        self.assertEqual(len(messages), 1)
        self.assertIn("code", messages[0])
        self.assertIn("passkey", messages[0])
        self.assertTrue(cleo.is_client)

    def test_clients_with_a_connected_account_neither(self):
        cleo = person("Cleo", client=True)
        SocialAccount.objects.create(user=cleo, provider="google", uid="1234")
        request, _response = self.sign_in("other@example.org", uid="1234")
        self.assertFalse(request.user.is_authenticated)

    def test_unknown_addresses_dont_sign_up(self):
        request, _response = self.sign_in("nobody@example.org")
        self.assertFalse(request.user.is_authenticated)

    def test_deactivated_staff_cant(self):
        person("Ada", is_active=False)
        request, _response = self.sign_in("ada@example.org")
        self.assertFalse(request.user.is_authenticated)
