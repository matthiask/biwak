"""Findings of the review of single sign-on (specs/sso.md, 2026-11-21)"""

import datetime as dt
import io
from contextlib import redirect_stdout
from importlib import import_module

from allauth.mfa.models import Authenticator
from allauth.usersessions.models import UserSession
from django.conf import settings
from django.test import Client, override_settings
from django.utils import timezone

from biwak.accounts import sso
from biwak.accounts.models import User
from biwak.accounts.test_sso_required import RequiredTestCase, passkey
from biwak.accounts.test_sso_social import SocialTestCase, google_claims
from biwak.collab import live
from biwak.items import operations as ops
from biwak.organizations import operations as org_ops
from biwak.organizations.models import Organization
from biwak.test_utils import SSO_PROVIDERS, organization, project, sign_in_with


TENANT = "3f2504e0-4f89-11d3-9a0c-0305e82c3301"
OTHER_TENANT = "11111111-2222-3333-4444-555555555555"


class AddressesTest(RequiredTestCase):
    """Nobody changes their own address: one added could sign in elsewhere
    (a Gmail address with Google) after leaving the company"""

    def test_allauths_address_pages_dont_exist(self):
        for user in [self.ada, self.cleo]:
            sign_in_with(self.client, user)
            for url in ["/accounts/email/", "/accounts/confirm-email/"]:
                with self.subTest(user=user, url=url):
                    self.assertEqual(self.client.get(url).status_code, 404)
                    response = self.client.post(
                        url, {"email": "gus@gmail.com", "action_add": ""}
                    )
                    self.assertEqual(response.status_code, 404)
        self.assertEqual(
            sorted(
                User.objects.get(pk=self.cleo.pk).emailaddress_set.values_list(
                    "email", flat=True
                )
            ),
            ["cleo@acme.example"],
        )

    def test_reauthenticating_goes_through_the_provider(self):
        self.require()
        sign_in_with(self.client, self.cleo)
        for url in [
            "/accounts/reauthenticate/",
            "/accounts/reauthenticate/code/",
            "/accounts/reauthenticate/code/confirm/",
            "/accounts/2fa/reauthenticate/",
            "/accounts/2fa/webauthn/reauthenticate/",
        ]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(
                    response["Location"].startswith("/accounts/google/login/")
                )
        # No code is sent either
        response = self.client.post("/accounts/reauthenticate/code/")
        self.assertTrue(response["Location"].startswith("/accounts/google/login/"))

    def test_others_reauthenticate_by_code(self):
        self.client.force_login(self.ada)
        self.assertEqual(
            self.client.get("/accounts/reauthenticate/code/").status_code, 200
        )


class RedirectProcessTest(SocialTestCase):
    def test_checked_like_signing_in(self):
        """allauth's "redirect" process signs nobody in but updates the
        connected account"""
        request, response = self.sign_in(
            "google",
            google_claims("cleo@acme.example", hd="acme.example"),
            process="redirect",
        )
        self.assert_refused(request, response, "can't sign in with Google")


@override_settings(SOCIALACCOUNT_PROVIDERS=SSO_PROVIDERS)
class SessionClaimsTest(RequiredTestCase):
    """What counted when signing in has to count now"""

    def test_changing_the_domains_ends_the_session(self):
        self.require()
        sign_in_with(self.client, self.cleo)
        self.assertEqual(self.client.get("/").status_code, 200)
        org_ops.update_organization(self.acme, domains=["acme.test"], actor=self.root)
        self.assertEqual(self.client.get("/").status_code, 302)

    def test_moving_between_google_organizations(self):
        self.require()
        other = organization("Acme Group", domains=["acme.group"])
        org_ops.set_signin(other, signin="sso_required", idp="google", actor=self.root)
        # A session of Acme's Workspace (hd acme.example)
        sign_in_with(self.client, self.cleo)
        org_ops.set_organization(self.cleo, other, actor=self.root)
        self.assertEqual(self.client.get("/").status_code, 302)

    def test_stored_sessions_of_another_tenant_end(self):
        self.require(idp="microsoft", tenant_id=TENANT)
        client = Client()
        sign_in_with(client, self.cleo, "microsoft", claims={"tid": OTHER_TENANT})
        key = client.session.session_key
        UserSession.objects.create(
            user=self.cleo, session_key=key, ip="127.0.0.1", user_agent="Firefox"
        )
        sso.enforce_required([self.cleo])
        self.assertFalse(UserSession.objects.filter(session_key=key).exists())
        # The tenant's own one stays
        sign_in_with(client, self.cleo, "microsoft")
        key = client.session.session_key
        UserSession.objects.create(
            user=self.cleo, session_key=key, ip="127.0.0.1", user_agent="Firefox"
        )
        sso.enforce_required([self.cleo])
        self.assertTrue(UserSession.objects.filter(session_key=key).exists())


class AfterCommitTest(RequiredTestCase):
    def test_what_came_meanwhile_goes_too(self):
        """Passkeys added by a request that didn't see the switch yet"""
        with self.captureOnCommitCallbacks(execute=True):
            self.require()
            passkey(self.cleo)
        self.assertFalse(Authenticator.objects.filter(user=self.cleo).exists())

    def test_moving(self):
        self.require()
        dora = User.objects.create_user("dora@example.org", is_client=True)
        with self.captureOnCommitCallbacks(execute=True):
            org_ops.set_organization(dora, self.acme, actor=self.ada)
            passkey(dora)
        self.assertFalse(Authenticator.objects.filter(user=dora).exists())


class DjangoAdminTest(RequiredTestCase):
    def post(self, org, *, keep=False, **data):
        if not keep:
            self.client.force_login(self.root)
        return self.client.post(
            f"/admin/organizations/organization/{org.pk}/change/",
            {
                **({"is_own": "on"} if org.is_own else {}),
                "name": org.name,
                "domains": ",".join(org.domains),
                "signin": org.signin,
                "idp": org.idp,
                "tenant_id": org.tenant_id,
            }
            | data,
        )

    def test_own_organization_only_after_signing_in_through_it(self):
        own = Organization.objects.own()
        own.domains = ["example.org"]
        own.save()
        response = self.post(own, signin="sso_required", idp="google")
        self.assertContains(response, "Sign in with Google Workspace first")
        own.refresh_from_db()
        self.assertFalse(own.requires_sso)
        sign_in_with(self.client, self.root)
        response = self.post(own, signin="sso_required", idp="google", keep=True)
        self.assertEqual(response.status_code, 302)
        own.refresh_from_db()
        self.assertTrue(own.requires_sso)

    def test_domains_of_sso_organizations_stay(self):
        self.require()
        response = self.post(self.acme, domains="")
        self.assertContains(response, "needs its email domains")
        self.acme.refresh_from_db()
        self.assertEqual(self.acme.domains, ["acme.example"])


class WebsocketTest(RequiredTestCase):
    """Django's ``exists()`` doesn't look at the session's expiry"""

    def setUp(self):
        super().setUp()
        self.doc = ops.create_doc(
            project=project(members=[self.ada, self.cleo]),
            title="Minutes",
            creator=self.ada,
            visible=True,
        )

    def test_expired_sessions_dont_count(self):
        client = Client()
        client.force_login(self.ada)
        session = client.session
        key = session.session_key
        self.assertEqual(
            live.access(self.ada, self.doc.pk, session_key=key), live.WRITE
        )
        session.set_expiry(timezone.now() - dt.timedelta(seconds=1))
        session.save()
        store = import_module(settings.SESSION_ENGINE).SessionStore
        self.assertTrue(store().exists(key))
        self.assertIsNone(live.access(self.ada, self.doc.pk, session_key=key))

    def test_nor_sessions_no_longer_counting(self):
        client = Client()
        sign_in_with(client, self.cleo)
        key = client.session.session_key
        self.require()
        self.assertIsNotNone(live.access(self.cleo, self.doc.pk, session_key=key))
        org_ops.update_organization(self.acme, domains=["acme.test"], actor=self.root)
        self.assertIsNone(live.access(self.cleo, self.doc.pk, session_key=key))
        # Somebody else's session neither
        sign_in_with(client, self.ada)
        self.assertIsNone(
            live.access(self.cleo, self.doc.pk, session_key=client.session.session_key)
        )


class MigrationOutputTest(RequiredTestCase):
    def test_the_guessed_domains_are_shown(self):
        from django.apps import apps

        migration = import_module(
            "biwak.organizations.migrations.0005_own_organization_google"
        )
        own = Organization.objects.own()
        own.domains = []
        own.save()
        out = io.StringIO()
        with redirect_stdout(out):
            migration.own_organization_google(apps, None)
        self.assertIn("example.org", out.getvalue())
        self.assertIn("Check them", out.getvalue())
