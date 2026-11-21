"""Organizations requiring single sign-on (specs/sso.md): codes and passkeys
refused, passkeys removed, sessions and API tokens for 24 hours"""

import datetime as dt
import re
import time
from urllib.parse import parse_qs, urlparse

from allauth.account.internal.flows.login import perform_login, record_authentication
from allauth.account.models import Login
from allauth.core.context import request_context
from allauth.mfa.models import Authenticator
from allauth.socialaccount.models import SocialAccount
from allauth.usersessions.models import UserSession
from django.contrib.auth import get_user
from django.contrib.auth.middleware import AuthenticationMiddleware
from django.contrib.messages import get_messages
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from django.core import mail
from django.core.cache import cache
from django.test import Client, RequestFactory, TestCase, override_settings
from django.utils import timezone

from biwak.accounts import passkeys, sso
from biwak.accounts.models import APIToken, CalendarToken, User
from biwak.organizations import operations as org_ops
from biwak.test_utils import SSO_PROVIDERS, organization, person, sign_in_with


def passkey(user, name="Laptop"):
    return Authenticator.objects.create(
        user=user, type=Authenticator.Type.WEBAUTHN, data={"name": name}
    )


@override_settings(SOCIALACCOUNT_PROVIDERS=SSO_PROVIDERS)
class RequiredTestCase(TestCase):
    def setUp(self):
        cache.clear()  # the rate limits of login codes
        self.root = person("Root", is_admin=True)
        self.ada = person("Ada")
        self.acme = organization("Acme Ltd", domains=["acme.example"])
        self.cleo = User.objects.create_user(
            "cleo@acme.example",
            full_name="Cleo Example",
            is_client=True,
            organization=self.acme,
        )

    def require(self, org=None, idp="google", tenant_id=""):
        org_ops.set_signin(
            org or self.acme,
            signin="sso_required",
            idp=idp,
            tenant_id=tenant_id,
            actor=self.root,
        )
        self.cleo.refresh_from_db()

    def messages(self, response):
        return [str(m) for m in get_messages(response.wsgi_request)]


class CodesTest(RequiredTestCase):
    def request_code(self, email, url="/accounts/login/code/", field="email"):
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(url, {field: email, "next": "/projects/"})

    def test_sent_to_the_provider_instead(self):
        self.require()
        for url, field in [
            ("/accounts/login/code/", "email"),
            ("/accounts/login/", "login"),
        ]:
            with self.subTest(url=url):
                response = self.request_code("Cleo@acme.example", url, field)
                self.assertEqual(response.status_code, 302)
                location = urlparse(response["Location"])
                self.assertEqual(location.path, "/accounts/google/login/")
                query = parse_qs(location.query)
                self.assertEqual(query["process"], ["login"])
                self.assertEqual(query["next"], ["/projects/"])
                self.assertEqual(
                    parse_qs(query["auth_params"][0]),
                    {"login_hint": ["cleo@acme.example"]},
                )
                self.assertIn("Acme Ltd signs in with Google.", self.messages(response))
                self.assertEqual(mail.outbox, [])
        # The provider's page asks to continue there
        self.assertContains(self.client.get(response["Location"]), "Google")

    def test_others_get_codes(self):
        for user in [self.ada, self.cleo]:
            self.client = Client()
            response = self.request_code(user.email)
            self.assertTrue(
                response["Location"].startswith("/accounts/login/code/confirm/")
            )
            self.assertEqual(len(mail.outbox), 1)
        # Single sign-on allowed doesn't change that
        org_ops.set_signin(
            self.acme, signin="sso_allowed", idp="google", actor=self.root
        )
        self.client = Client()
        self.request_code(self.cleo.email)
        self.assertEqual(len(mail.outbox), 1)

    def test_a_code_from_before_switching_is_refused(self):
        self.request_code(self.cleo.email)
        code = re.search(r"\b([A-Z0-9]{4}-[A-Z0-9]{4})\b", mail.outbox[-1].body).group(
            1
        )
        self.require()
        response = self.client.post("/accounts/login/code/confirm/", {"code": code})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/accounts/google/login/"))
        self.assertIn("Acme Ltd signs in with Google.", self.messages(response))
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertNotIn("account_authentication_methods", self.client.session)

    def test_deactivated_people_get_no_hint(self):
        self.require()
        self.cleo.is_active = False
        self.cleo.save()
        response = self.request_code(self.cleo.email)
        self.assertIn("/accounts/login/code/confirm/", response["Location"])
        self.assertNotIn("Google", " ".join(self.messages(response)))


class AllauthLoginTest(RequiredTestCase):
    """allauth's login flow after a method was recorded, as its views do"""

    def login(self, user, method, **extra):
        request = RequestFactory().get("/")
        for middleware in [
            SessionMiddleware,
            AuthenticationMiddleware,
            MessageMiddleware,
        ]:
            middleware(lambda r: None).process_request(request)
        with request_context(request):
            record_authentication(request, user, method, **extra)
            response = perform_login(request, Login(user=user))
        request.user = get_user(request)
        return request, response

    def test_passkeys_are_refused(self):
        """As allauth's passkey login does (``perform_passwordless_login``)"""
        self.require()
        request, response = self.login(
            self.cleo, "mfa", type="webauthn", passwordless=True
        )
        self.assertFalse(request.user.is_authenticated)
        self.assertTrue(response["Location"].startswith("/accounts/google/login/"))
        self.assertEqual(
            [str(m) for m in get_messages(request)], ["Acme Ltd signs in with Google."]
        )

    def test_another_provider_is_refused(self):
        self.require()
        request, _response = self.login(
            self.cleo, "socialaccount", provider="microsoft", uid="1"
        )
        self.assertFalse(request.user.is_authenticated)

    def test_the_provider(self):
        self.require()
        request, _response = self.login(
            self.cleo, "socialaccount", provider="google", uid="1"
        )
        self.assertEqual(request.user, self.cleo)
        # Expires 24 hours after signing in, as a date
        self.assertLessEqual(request.session.get_expiry_age(), 24 * 3600)
        self.assertGreater(request.session.get_expiry_age(), 24 * 3600 - 60)

    def test_others_keep_codes_and_passkeys(self):
        request, _response = self.login(self.cleo, "code", email=self.cleo.email)
        self.assertEqual(request.user, self.cleo)
        request, _response = self.login(
            self.ada, "mfa", type="webauthn", passwordless=True
        )
        self.assertEqual(request.user, self.ada)
        self.assertGreater(request.session.get_expiry_age(), 7 * 86400)

    def test_deactivated_people_never(self):
        self.require()
        self.cleo.is_active = False
        self.cleo.save()
        request, _response = self.login(
            self.cleo, "socialaccount", provider="google", uid="1"
        )
        self.assertFalse(request.user.is_authenticated)


class SessionsTest(RequiredTestCase):
    def test_24_hours_after_signing_in(self):
        self.require()
        sign_in_with(self.client, self.cleo, "google", at=time.time() - 23 * 3600)
        self.assertEqual(self.client.get("/").status_code, 200)
        sign_in_with(self.client, self.cleo, "google", at=time.time() - 24 * 3600 - 1)
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])
        self.assertIn("Acme Ltd signs in with Google.", self.messages(response)[0])
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_remember_me_doesnt_extend_it(self):
        """The session's age as the browser keeps it doesn't matter"""
        self.require()
        sign_in_with(self.client, self.cleo, "google", at=time.time() - 25 * 3600)
        session = self.client.session
        session.set_expiry(30 * 86400)
        session.save()
        self.assertEqual(self.client.get("/").status_code, 302)

    def test_sessions_without_the_provider_end(self):
        """Signed in by code (before switching), or without allauth's record
        (another way in), or with another provider, or as somebody else"""
        self.require()
        self.client.force_login(self.cleo)
        self.assertEqual(self.client.get("/").status_code, 302)
        for provider in ["microsoft", None]:
            sign_in_with(self.client, self.cleo, provider)
            self.assertEqual(self.client.get("/").status_code, 302)
        sign_in_with(self.client, self.cleo)
        session = self.client.session
        session["account_authentication_methods_user"] = str(self.ada.pk)
        session.save()
        self.assertEqual(self.client.get("/").status_code, 302)
        # Records allauth can't read
        for records in [[{"method": "socialaccount", "provider": "google"}], "x"]:
            sign_in_with(self.client, self.cleo)
            session = self.client.session
            session["account_authentication_methods"] = records
            session.save()
            self.assertEqual(self.client.get("/").status_code, 302)

    def test_sessions_from_before_the_switch_expire_then(self):
        """Signed in with Google while it was allowed: the session's 30 days
        become 24 hours after signing in (websockets read the date)"""
        sign_in_with(self.client, self.cleo, at=time.time() - 3600)
        self.assertGreater(self.client.session.get_expiry_age(), 86400)
        self.require()
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertLess(self.client.session.get_expiry_age(), 23 * 3600 + 60)

    def test_the_api_answers_401(self):
        self.require()
        sign_in_with(self.client, self.cleo, at=time.time() - 25 * 3600)
        self.assertEqual(self.client.get("/api/v1/me/").status_code, 401)
        sign_in_with(self.client, self.cleo)
        self.assertEqual(self.client.get("/api/v1/me/").status_code, 200)

    def test_others_unchanged(self):
        self.client.force_login(self.cleo)
        self.assertEqual(self.client.get("/").status_code, 200)
        self.client.force_login(self.ada)
        self.assertEqual(self.client.get("/").status_code, 200)


class SwitchingTest(RequiredTestCase):
    def setUp(self):
        super().setUp()
        self.old_token, _secret = APIToken.create_for(
            user=self.cleo, title="Old", access="read"
        )
        APIToken.objects.filter(pk=self.old_token.pk).update(
            created_at=timezone.now() - dt.timedelta(days=3)
        )
        self.new_token, _secret = APIToken.create_for(
            user=self.cleo, title="New", access="read"
        )
        passkey(self.cleo)
        passkey(self.ada)
        CalendarToken.renew(self.cleo)

    def sessions(self, user, provider=None):
        """A browser's session of the person, seen once"""
        client = Client()
        if provider:
            sign_in_with(client, user, provider)
        else:
            client.force_login(user)
        key = client.session.session_key
        # As allauth records it on signing in
        UserSession.objects.create(
            user=user, session_key=key, ip="127.0.0.1", user_agent="Firefox"
        )
        return key

    def assert_enforced(self, user):
        self.assertFalse(Authenticator.objects.filter(user=user).exists())
        self.assertFalse(CalendarToken.objects.filter(user=user).exists())
        for token in APIToken.objects.filter(user=user):
            self.assertEqual(token.expires_at, token.created_at + sso.SSO_MAX_AGE)

    def test_switching_to_required(self):
        by_code = self.sessions(self.cleo)
        by_google = self.sessions(self.cleo, "google")
        ada_session = self.sessions(self.ada)
        self.assertEqual(UserSession.objects.filter(user=self.cleo).count(), 2)
        self.require()
        self.assert_enforced(self.cleo)
        self.old_token.refresh_from_db()
        self.assertLess(self.old_token.expires_at, timezone.now())
        self.assertEqual(
            set(UserSession.objects.values_list("session_key", flat=True)),
            {by_google, ada_session},
        )
        # Expiring 24 hours after signing in
        from importlib import import_module

        from django.conf import settings

        store = import_module(settings.SESSION_ENGINE).SessionStore(by_google)
        self.assertLessEqual(store.get_expiry_age(), 24 * 3600)
        self.assertNotEqual(by_code, by_google)
        # Other people keep theirs
        self.assertTrue(Authenticator.objects.filter(user=self.ada).exists())

    def test_switching_back_revives_nothing(self):
        self.require()
        org_ops.set_signin(self.acme, signin="codes", actor=self.root)
        self.assertFalse(Authenticator.objects.filter(user=self.cleo).exists())

    def test_allowed_removes_nothing(self):
        org_ops.set_signin(
            self.acme, signin="sso_allowed", idp="google", actor=self.root
        )
        self.assertTrue(Authenticator.objects.filter(user=self.cleo).exists())
        self.assertTrue(CalendarToken.objects.filter(user=self.cleo).exists())

    def test_moving_into_it(self):
        self.require()
        passkey(self.cleo)
        dora = User.objects.create_user(
            "dora@example.org", is_client=True, organization=organization("Other Ltd")
        )
        passkey(dora)
        CalendarToken.renew(dora)
        org_ops.set_organization(dora, self.acme, actor=self.ada)
        self.assert_enforced(dora)
        # Through the Django admin too
        eve = User.objects.create_user("eve@example.org", is_client=True)
        passkey(eve)
        self.client.force_login(self.root)
        response = self.client.post(
            f"/admin/accounts/user/{eve.pk}/change/",
            {
                "email": eve.email,
                "is_client": "on",
                "organization": self.acme.pk,
                "is_active": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assert_enforced(eve)

    def test_merging_into_it(self):
        self.require()
        other = organization("Acme Old Ltd")
        fred = User.objects.create_user(
            "fred@example.org", is_client=True, organization=other
        )
        passkey(fred)
        org_ops.merge(other, self.acme, actor=self.ada)
        self.assert_enforced(fred)

    def test_the_django_admin_setting(self):
        self.client.force_login(self.root)
        response = self.client.post(
            f"/admin/organizations/organization/{self.acme.pk}/change/",
            {
                "name": "Acme Ltd",
                "domains": "acme.example",
                "signin": "sso_required",
                "idp": "google",
                "tenant_id": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assert_enforced(self.cleo)


class PasskeysTest(RequiredTestCase):
    def test_not_offered_nor_added(self):
        self.require()
        sign_in_with(self.client, self.cleo)
        response = self.client.get("/accounts/settings/")
        self.assertNotContains(response, "Add a passkey")
        self.assertNotContains(response, "Passkeys")
        self.assertContains(response, "You sign in through Acme Ltd's Google Workspace")
        response = self.client.get("/accounts/2fa/webauthn/add/")
        self.assertRedirects(
            response, "/accounts/settings/#sign-in", fetch_redirect_response=False
        )
        self.assertIn("Passkeys aren't used there", self.messages(response)[0])
        self.assertEqual(
            self.client.post("/accounts/2fa/webauthn/add/").status_code, 302
        )
        self.assertFalse(passkeys.offer_due(self.cleo))

    def test_one_coming_through_anyway_is_removed(self):
        from allauth.mfa.signals import authenticator_added

        self.require()
        authenticator = passkey(self.cleo)
        authenticator_added.send(
            sender=Authenticator,
            request=None,
            user=self.cleo,
            authenticator=authenticator,
        )
        self.assertFalse(Authenticator.objects.filter(user=self.cleo).exists())

    def test_others_see_theirs(self):
        self.client.force_login(self.ada)
        response = self.client.get("/accounts/settings/")
        self.assertContains(response, "Add a passkey")
        self.assertNotContains(response, "You sign in through")
        # allauth's page (asking to confirm who one is first)
        response = self.client.get("/accounts/2fa/webauthn/add/")
        self.assertIn("/accounts/reauthenticate/", response["Location"])


class ConnectedAccountsTest(RequiredTestCase):
    def test_disconnecting(self):
        account = SocialAccount.objects.create(
            user=self.ada,
            provider="google",
            uid="1",
            extra_data={"email": "ada@example.org", "email_verified": True},
        )
        self.client.force_login(self.ada)
        response = self.client.get("/accounts/settings/")
        self.assertContains(response, "Connected accounts")
        self.assertContains(response, "ada@example.org")
        self.assertContains(response, "Disconnect")
        response = self.client.post(f"/accounts/connected/{account.pk}/disconnect/")
        self.assertRedirects(
            response, "/accounts/settings/#sign-in", fetch_redirect_response=False
        )
        self.assertFalse(SocialAccount.objects.exists())
        self.assertEqual(
            self.messages(response), ["The Google account has been disconnected."]
        )
        self.assertRedirects(
            self.client.get("/accounts/3rdparty/"),
            "/accounts/settings/#sign-in",
            fetch_redirect_response=False,
        )

    def test_not_where_required(self):
        self.require()
        account = SocialAccount.objects.create(
            user=self.cleo,
            provider="google",
            uid="1",
            extra_data={"email": "cleo@acme.example", "email_verified": True},
        )
        sign_in_with(self.client, self.cleo)
        response = self.client.get("/accounts/settings/")
        self.assertContains(response, "cleo@acme.example")
        self.assertNotContains(response, "Disconnect")
        response = self.client.post(f"/accounts/connected/{account.pk}/disconnect/")
        self.assertIn("stays connected", self.messages(response)[0])
        self.assertTrue(SocialAccount.objects.exists())
        # Nobody else's
        self.client.force_login(self.ada)
        response = self.client.post(f"/accounts/connected/{account.pk}/disconnect/")
        self.assertEqual(response.status_code, 404)

    def test_none_yet(self):
        self.require()
        sign_in_with(self.client, self.cleo)
        self.assertContains(
            self.client.get("/accounts/settings/"), "No connected accounts yet."
        )
        self.client.force_login(self.ada)
        self.assertNotContains(
            self.client.get("/accounts/settings/"), "Connected accounts"
        )


class APITokensTest(RequiredTestCase):
    def headers(self, secret):
        return {"authorization": f"Bearer {secret}"}

    def test_24_hours_after_creation(self):
        self.require()
        token, secret = APIToken.create_for(user=self.cleo, title="T", access="read")
        self.assertEqual(token.expires_at, token.created_at + sso.SSO_MAX_AGE)
        response = self.client.get("/api/v1/me/", headers=self.headers(secret))
        self.assertEqual(response.status_code, 200)
        # Using it doesn't extend it
        token.refresh_from_db()
        self.assertEqual(token.expires_at, token.created_at + sso.SSO_MAX_AGE)
        # Checked on authenticating, whatever expires_at says
        APIToken.objects.filter(pk=token.pk).update(
            created_at=timezone.now() - dt.timedelta(hours=24, seconds=1),
            expires_at=timezone.now() + dt.timedelta(days=10),
        )
        response = self.client.get("/api/v1/me/", headers=self.headers(secret))
        self.assertEqual(response.status_code, 401)

    def test_others_30_days_after_the_last_use(self):
        token, secret = APIToken.create_for(user=self.cleo, title="T", access="read")
        self.assertGreater(token.expires_at, timezone.now() + dt.timedelta(days=29))
        APIToken.objects.filter(pk=token.pk).update(
            created_at=timezone.now() - dt.timedelta(days=3)
        )
        response = self.client.get("/api/v1/me/", headers=self.headers(secret))
        self.assertEqual(response.status_code, 200)

    def test_the_pages_say_so(self):
        self.require()
        sign_in_with(self.client, self.cleo)
        self.assertContains(
            self.client.get("/accounts/api-tokens/"), "24 hours after they were created"
        )
        response = self.client.get(
            "/accounts/cli-login/",
            {"port": 8123, "state": "a" * 20, "access": "read"},
        )
        self.assertContains(response, "24 hours from now")
        response = self.client.post(
            "/accounts/cli-login/?port=8123&state=" + "a" * 20 + "&access=read"
        )
        token = APIToken.objects.get(user=self.cleo)
        self.assertEqual(token.expires_at, token.created_at + sso.SSO_MAX_AGE)


class CalendarTest(RequiredTestCase):
    def test_no_calendar_links(self):
        link = CalendarToken.renew(self.cleo)
        feed = f"/calendar/{link.token}.ics"
        self.assertEqual(self.client.get(feed).status_code, 200)
        self.require()
        # Removed on switching; and refused should one exist
        self.assertEqual(self.client.get(feed).status_code, 404)
        link = CalendarToken.objects.create(user=self.cleo, token="made-up-token")
        self.assertEqual(
            self.client.get("/calendar/made-up-token.ics").status_code, 404
        )
        sign_in_with(self.client, self.cleo)
        response = self.client.get("/accounts/calendar/")
        self.assertContains(response, "there is none")
        self.client.post("/accounts/calendar/")
        self.assertEqual(CalendarToken.objects.filter(user=self.cleo).count(), 1)
