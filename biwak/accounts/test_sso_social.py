"""Google and Microsoft sign-in per organization (specs/sso.md): the claims
checks, through allauth's flows and its views, with made-up providers'
answers (never Google or Microsoft)"""

import time
from contextlib import contextmanager
from unittest import mock
from urllib.parse import parse_qs, urlparse

import jwt
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

from biwak.accounts.microsoft.views import EntraOAuth2Adapter
from biwak.organizations import operations as org_ops
from biwak.organizations.models import Organization
from biwak.test_utils import SSO_PROVIDERS, organization, person


TENANT = "3f2504e0-4f89-11d3-9a0c-0305e82c3301"
OTHER_TENANT = "11111111-2222-3333-4444-555555555555"


def google_claims(email, *, hd=None, verified=True, sub="1234"):
    """What Google's ID token says"""
    claims = {
        "iss": "https://accounts.google.com",
        "aud": "google-id",
        "sub": sub,
        "email": email,
        "email_verified": verified,
        "name": "Somebody",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    if hd is not None:
        claims["hd"] = hd
    return claims


def microsoft_token(*, tid=TENANT, oid="oid-1", aud="microsoft-id", iss=None):
    """Microsoft's ID token, signed with a made-up key: the code exchange
    over TLS doesn't need the signature checked"""
    return jwt.encode(
        {
            "iss": iss or f"https://login.microsoftonline.com/{tid}/v2.0",
            "aud": aud,
            "tid": tid,
            "oid": oid,
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        },
        "made-up-key-of-at-least-32-bytes!",
        algorithm="HS256",
    )


def graph_profile(email, *, oid="oid-1"):
    return {"id": oid, "mail": email, "userPrincipalName": email, "displayName": "X"}


class FakeResponse:
    def __init__(self, data):
        self.data = data
        self.status_code = 200
        self.ok = True
        self.headers = {"content-type": "application/json"}
        self.text = "{}"
        self.content = b"{}"

    def json(self):
        return self.data


class FakeSession:
    """The providers' token endpoint (any request) and user info (``get``)"""

    def __init__(self, token, profile):
        self.token = token
        self.profile = profile
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def request(self, method, url, **kwargs):
        self.calls.append(url)
        return FakeResponse(self.token)

    def get(self, url, **kwargs):
        self.calls.append(url)
        return FakeResponse(self.profile)


@contextmanager
def fake_provider(token, profile=None):
    session = FakeSession(token, profile)
    with mock.patch(
        "allauth.socialaccount.adapter.DefaultSocialAccountAdapter.get_requests_session",
        return_value=session,
    ):
        yield session


@override_settings(SOCIALACCOUNT_PROVIDERS=SSO_PROVIDERS)
class SocialTestCase(TestCase):
    def setUp(self):
        self.root = person("Root", is_admin=True)
        self.own = Organization.objects.own()
        self.own.domains = ["example.org"]
        self.own.save()
        self.ada = person("Ada")
        self.acme = organization("Acme Ltd", domains=["acme.example", "acme.test"])
        self.cleo = self.client_person("Cleo", self.acme)

    def client_person(self, name, org, email=None):
        from biwak.accounts.models import User

        return User.objects.create_user(
            email or f"{name.lower()}@acme.example",
            full_name=f"{name} Example",
            is_client=True,
            organization=org,
        )

    def set_signin(self, org, signin, idp="", tenant_id=""):
        org_ops.set_signin(
            org, signin=signin, idp=idp, tenant_id=tenant_id, actor=self.root
        )

    def sign_in(self, provider, data, *, process="login", user=None):
        """What the provider's callback does after the code exchange:
        completes a social login with the claims"""
        request = RequestFactory().get(f"/accounts/{provider}/login/callback/")
        for middleware in [
            SessionMiddleware,
            AuthenticationMiddleware,
            MessageMiddleware,
        ]:
            middleware(lambda r: None).process_request(request)
        if user is not None:
            request.user = user
        with request_context(request):
            app = get_adapter().get_app(request, provider)
            sociallogin = app.get_provider(request).sociallogin_from_response(
                request, data
            )
            sociallogin.state = {"process": process}
            try:
                response = complete_social_login(request, sociallogin)
            except ImmediateHttpResponse as exc:
                response = exc.response
        if user is None:
            request.user = get_user(request)
        request.messages_ = [str(m) for m in get_messages(request)]
        return request, response

    def assert_signed_in(self, request, user):
        self.assertEqual(request.user, user, request.messages_)

    def assert_refused(self, request, response, message=None):
        self.assertFalse(request.user.is_authenticated)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])
        self.assertEqual(len(request.messages_), 1, request.messages_)
        if message:
            self.assertIn(message, request.messages_[0])


class GoogleTest(SocialTestCase):
    def test_staff_with_their_workspace(self):
        """The own organization allows Google for its domains (unchanged
        for staff)"""
        request, response = self.sign_in(
            "google", google_claims("ada@example.org", hd="example.org")
        )
        self.assert_signed_in(request, self.ada)
        self.assertEqual(response["Location"], settings.LOGIN_REDIRECT_URL)
        self.assertTrue(SocialAccount.objects.filter(user=self.ada).exists())

    def test_hd_has_to_be_one_of_the_domains_exactly(self):
        """Case doesn't matter; suffixes, subdomains, spaces do"""
        request, _response = self.sign_in(
            "google", google_claims("ada@example.org", hd="EXAMPLE.org")
        )
        self.assert_signed_in(request, self.ada)
        for hd in [
            "evil.example",
            "example.org.evil.example",
            "evilexample.org",
            "sub.example.org",
            "example.or",
            " example.org",
            "example.org.",
            "",
            ["example.org"],
            True,
        ]:
            with self.subTest(hd=hd):
                request, response = self.sign_in(
                    "google", google_claims("ada@example.org", hd=hd)
                )
                self.assert_refused(request, response, "Google Workspace of")

    def test_personal_accounts_with_a_company_address_dont_count(self):
        """No hd: the stale-account risk"""
        request, response = self.sign_in("google", google_claims("ada@example.org"))
        self.assert_refused(request, response, "isn't managed by")

    def test_never_an_unverified_address(self):
        for verified in [False, "false", None, "yes", 1]:
            with self.subTest(verified=verified):
                request, response = self.sign_in(
                    "google",
                    google_claims(
                        "ada@example.org", hd="example.org", verified=verified
                    ),
                )
                self.assert_refused(request, response, "no active account")
        # The user info's spelling
        request, _response = self.sign_in(
            "google",
            {
                "id": "1",
                "email": "ada@example.org",
                "verified_email": True,
                "hd": "example.org",
            },
        )
        self.assert_signed_in(request, self.ada)

    def test_clients_of_organizations_with_codes(self):
        request, response = self.sign_in(
            "google", google_claims("cleo@acme.example", hd="acme.example")
        )
        self.assert_refused(request, response, "can't sign in with Google")
        self.assertFalse(SocialAccount.objects.exists())

    def test_clients_where_google_is_allowed(self):
        self.set_signin(self.acme, "sso_allowed", "google")
        for hd in ["acme.example", "acme.test"]:
            request, _response = self.sign_in(
                "google", google_claims("cleo@acme.example", hd=hd)
            )
            self.assert_signed_in(request, self.cleo)
        # Not another organization's Workspace, not the own one's
        for hd in ["example.org", "other.example", None]:
            request, response = self.sign_in(
                "google", google_claims("cleo@acme.example", hd=hd)
            )
            self.assert_refused(request, response, "Acme Ltd")

    def test_required(self):
        self.set_signin(self.acme, "sso_required", "google")
        request, _response = self.sign_in(
            "google", google_claims("cleo@acme.example", hd="acme.example")
        )
        self.assert_signed_in(request, self.cleo)

    def test_not_where_another_provider_is_required(self):
        self.set_signin(self.acme, "sso_required", "microsoft", TENANT)
        request, response = self.sign_in(
            "google", google_claims("cleo@acme.example", hd="acme.example")
        )
        self.assert_refused(request, response, "Acme Ltd signs in with Microsoft.")

    def test_gmail(self):
        """Google owns the mailbox: where single sign-on is allowed or off,
        not where it's required, also Google (decided 2026-11-21: its
        Workspace accounts only)"""
        gus = self.client_person("Gus", self.acme, "gus@gmail.com")
        request, _response = self.sign_in("google", google_claims("gus@gmail.com"))
        self.assert_signed_in(request, gus)
        self.set_signin(self.acme, "sso_allowed", "microsoft", TENANT)
        request, _response = self.sign_in("google", google_claims("gus@gmail.com"))
        self.assert_signed_in(request, gus)
        self.set_signin(self.acme, "sso_required", "google")
        request, response = self.sign_in("google", google_claims("gus@gmail.com"))
        self.assert_refused(request, response, "Google Workspace of Acme Ltd")
        self.set_signin(self.acme, "sso_required", "microsoft", TENANT)
        request, response = self.sign_in("google", google_claims("gus@gmail.com"))
        self.assert_refused(request, response, "signs in with Microsoft")
        # Without an organization too
        from biwak.accounts.models import User

        ida = User.objects.create_user("ida@googlemail.com", is_client=True)
        request, _response = self.sign_in(
            "google", google_claims("ida@googlemail.com", sub="5678")
        )
        self.assert_signed_in(request, ida)
        # Unverified, never
        request, response = self.sign_in(
            "google", google_claims("ida@googlemail.com", verified=False, sub="5678")
        )
        self.assert_refused(request, response)

    def test_matched_by_the_person_not_the_domain(self):
        """Somebody with an Acme address in the own organization counts
        with the own organization's rules (here: hd of the own Workspace)"""
        from biwak.accounts.models import User

        ben = User.objects.create_user(
            "ben@acme.example", organization=self.own, full_name="Ben"
        )
        self.set_signin(self.acme, "sso_allowed", "google")
        request, response = self.sign_in(
            "google", google_claims("ben@acme.example", hd="acme.example")
        )
        self.assert_refused(request, response, "Our organization")
        request, _response = self.sign_in(
            "google", google_claims("ben@acme.example", hd="example.org")
        )
        self.assert_signed_in(request, ben)

    def test_unknown_and_deactivated_people(self):
        request, response = self.sign_in(
            "google", google_claims("nobody@example.org", hd="example.org")
        )
        self.assert_refused(request, response, "no active account")
        self.ada.is_active = False
        self.ada.save()
        request, response = self.sign_in(
            "google", google_claims("ada@example.org", hd="example.org")
        )
        self.assert_refused(request, response, "no active account")

    def test_deactivated_with_a_connected_account(self):
        SocialAccount.objects.create(user=self.ada, provider="google", uid="1234")
        self.ada.is_active = False
        self.ada.save()
        request, _response = self.sign_in(
            "google", google_claims("ada@example.org", hd="example.org")
        )
        self.assertFalse(request.user.is_authenticated)

    def test_a_connected_account_counts_only_with_the_persons_address(self):
        """The connected account (by Google's ID) leads to Ada, but its
        address isn't hers (anymore): refused"""
        SocialAccount.objects.create(user=self.ada, provider="google", uid="1234")
        request, response = self.sign_in(
            "google", google_claims("other@example.org", hd="example.org")
        )
        self.assert_refused(request, response, "no active account")
        # And a connected client account doesn't get around the rules
        SocialAccount.objects.create(user=self.cleo, provider="google", uid="5678")
        request, response = self.sign_in(
            "google", google_claims("cleo@acme.example", hd="acme.example", sub="5678")
        )
        self.assert_refused(request, response)

    def test_connecting_checks_the_same(self):
        request, response = self.sign_in(
            "google",
            google_claims("ada@example.org"),
            process="connect",
            user=self.ada,
        )
        self.assertIn("isn't managed by", request.messages_[0])
        self.assertIn("/accounts/settings/", response["Location"])
        self.assertFalse(SocialAccount.objects.exists())
        # Somebody else's address
        request, response = self.sign_in(
            "google",
            google_claims("root@example.org", hd="example.org"),
            process="connect",
            user=self.ada,
        )
        self.assertIn("no active account", request.messages_[0])
        self.assertFalse(SocialAccount.objects.exists())


class MicrosoftTest(SocialTestCase):
    def setUp(self):
        super().setUp()
        self.set_signin(self.acme, "sso_allowed", "microsoft", TENANT)

    def complete(self, token_response, profile):
        """Through allauth's Microsoft adapter (the code exchange done)"""
        request = RequestFactory().get("/accounts/microsoft/login/callback/")
        for middleware in [
            SessionMiddleware,
            AuthenticationMiddleware,
            MessageMiddleware,
        ]:
            middleware(lambda r: None).process_request(request)
        with request_context(request), fake_provider(token_response, profile):
            adapter = EntraOAuth2Adapter(request)
            adapter.did_fetch_access_token = True
            app = get_adapter().get_app(request, "microsoft")
            token = adapter.parse_token(token_response)
            login = adapter.complete_login(request, app, token, response=token_response)
            login.state = {"process": "login"}
            try:
                response = complete_social_login(request, login)
            except ImmediateHttpResponse as exc:
                response = exc.response
        request.user = get_user(request)
        request.messages_ = [str(m) for m in get_messages(request)]
        return request, response

    def test_the_organizations_tenant(self):
        request, _response = self.complete(
            {"access_token": "a", "id_token": microsoft_token()},
            graph_profile("Cleo@acme.example"),
        )
        self.assert_signed_in(request, self.cleo)
        account = SocialAccount.objects.get(user=self.cleo)
        self.assertEqual(account.extra_data["tid"], TENANT)

    def test_another_tenant(self):
        request, response = self.complete(
            {"access_token": "a", "id_token": microsoft_token(tid=OTHER_TENANT)},
            graph_profile("cleo@acme.example"),
        )
        self.assert_refused(request, response, "doesn't belong to the organization")

    def test_only_addresses_of_the_organizations_domains(self):
        """Entra ID doesn't verify addresses: the tenant's administrators
        could give anybody's to one of their accounts, so a tenant counts
        only for its organization's domains (somebody moved into the
        organization with another address uses codes)"""
        from biwak.accounts.models import User

        ida = User.objects.create_user(
            "ida@example.net", is_client=True, organization=self.acme
        )
        request, response = self.complete(
            {"access_token": "a", "id_token": microsoft_token()},
            graph_profile("ida@example.net"),
        )
        self.assert_refused(request, response, "doesn't belong to the organization")
        self.assertEqual(ida.organization, self.acme)

    def test_not_for_organizations_without_microsoft(self):
        request, response = self.complete(
            {"access_token": "a", "id_token": microsoft_token()},
            graph_profile("ada@example.org"),
        )
        self.assert_refused(request, response, "can't sign in with Microsoft")

    def test_the_id_token_is_checked(self):
        from allauth.socialaccount.providers.oauth2.client import OAuth2Error

        for token in [
            None,
            "not-a-token",
            microsoft_token(aud="another-app"),
            microsoft_token(
                iss=f"https://login.microsoftonline.com/{OTHER_TENANT}/v2.0"
            ),
            microsoft_token(oid="somebody-else"),
        ]:
            with self.subTest(token=token), self.assertRaises(OAuth2Error):
                self.complete(
                    {"access_token": "a", "id_token": token},
                    graph_profile("cleo@acme.example"),
                )

    def test_only_tokens_from_the_code_exchange(self):
        from allauth.socialaccount.providers.oauth2.client import OAuth2Error

        request = RequestFactory().get("/")
        with request_context(request), self.assertRaises(OAuth2Error):
            adapter = EntraOAuth2Adapter(request)
            app = get_adapter().get_app(request, "microsoft")
            response = {"access_token": "a", "id_token": microsoft_token()}
            adapter.complete_login(
                request, app, adapter.parse_token(response), response=response
            )


class ThroughTheViewsTest(SocialTestCase):
    """The whole round trip: the button, the provider, the callback"""

    def round_trip(self, provider, token, profile=None):
        response = self.client.post(
            f"/accounts/{provider}/login/", {"process": "login"}
        )
        self.assertEqual(response.status_code, 302)
        location = urlparse(response["Location"])
        query = parse_qs(location.query)
        state = query["state"][0]
        with fake_provider(token, profile) as session:
            response = self.client.get(
                f"/accounts/{provider}/login/callback/",
                {"code": "made-up-code", "state": state},
            )
        return location, query, response, session

    def test_google(self):
        token = {
            "access_token": "a",
            "id_token": jwt.encode(
                google_claims("ada@example.org", hd="example.org"),
                "made-up-key-of-at-least-32-bytes!",
            ),
        }
        location, query, response, session = self.round_trip("google", token)
        self.assertEqual(location.netloc, "accounts.google.com")
        self.assertIn("openid", query["scope"][0])
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], settings.LOGIN_REDIRECT_URL)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.ada.pk)
        self.assertEqual(session.calls, ["https://oauth2.googleapis.com/token"])
        self.assertEqual(self.client.session["biwak_sso"]["hd"], "example.org")

    def test_google_without_hd(self):
        token = {
            "access_token": "a",
            "id_token": jwt.encode(
                google_claims("ada@example.org"), "made-up-key-of-at-least-32-bytes!"
            ),
        }
        _location, _query, response, _session = self.round_trip("google", token)
        self.assertRedirects(
            response, "/accounts/login/", fetch_redirect_response=False
        )
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_microsoft(self):
        self.set_signin(self.acme, "sso_required", "microsoft", TENANT)
        location, query, response, session = self.round_trip(
            "microsoft",
            {"access_token": "a", "id_token": microsoft_token()},
            graph_profile("cleo@acme.example"),
        )
        self.assertEqual(location.netloc, "login.microsoftonline.com")
        self.assertTrue(location.path.startswith("/organizations/"))
        self.assertEqual(
            set(query["scope"][0].split()), {"openid", "email", "profile", "User.Read"}
        )
        self.assertEqual(response["Location"], settings.LOGIN_REDIRECT_URL)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.cleo.pk)
        # What counted is kept in the session and counts on the next request
        record = self.client.session["biwak_sso"]
        self.assertEqual(
            (record["provider"], record["tid"], record["org"], record["user"]),
            ("microsoft", TENANT, self.acme.pk, self.cleo.pk),
        )
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(
            session.calls[0],
            "https://login.microsoftonline.com/organizations/oauth2/v2.0/token",
        )

    def test_microsoft_of_another_tenant(self):
        _location, _query, response, _session = self.round_trip(
            "microsoft",
            {"access_token": "a", "id_token": microsoft_token(tid=OTHER_TENANT)},
            graph_profile("cleo@acme.example"),
        )
        self.assertRedirects(
            response, "/accounts/login/", fetch_redirect_response=False
        )
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_the_login_page_offers_whats_set_up(self):
        response = self.client.get("/accounts/login/")
        self.assertContains(response, "/accounts/google/login/")
        self.assertContains(response, "/accounts/microsoft/login/")
