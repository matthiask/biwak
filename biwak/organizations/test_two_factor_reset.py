"""Resetting someone's second factor (specs/two-factor.md): the operation,
the page, the API and the palette, with the split of specs/activation.md;
the CLI in ``biwak/test_cli_people.py``"""

from allauth.mfa.models import Authenticator
from allauth.usersessions.models import UserSession
from django.core import mail
from django.test import Client, TestCase

from biwak.accounts import sso
from biwak.accounts.test_two_factor import app, passkey
from biwak.audit.models import LoggedAction
from biwak.organizations import activation
from biwak.outbox.models import OutgoingMail
from biwak.palette.test_actions import palette_data
from biwak.test_utils import assert_modal, partner, person, project


class Base(TestCase):
    def setUp(self):
        self.root = person("Root", is_admin=True)
        self.ada = person("Ada")  # staff, no admin
        self.bob = person("Bob")
        self.pia = partner("Pia")
        self.cleo = person("Cleo", client=True)
        project("Site", members=[self.cleo, self.ada, self.pia])
        for user in [self.root, self.ada, self.bob, self.pia, self.cleo]:
            app(user)

    def has_app(self, user):
        return Authenticator.objects.filter(
            user=user, type=Authenticator.Type.TOTP
        ).exists()

    def signed_in(self, user):
        """A session of the person, as allauth records them"""
        client = Client()
        client.force_login(user)
        key = client.session.session_key
        UserSession.objects.create(
            user=user, session_key=key, ip="127.0.0.1", user_agent="Firefox"
        )
        return key


class OperationTest(Base):
    def test_staff_reset_clients(self):
        passkey(self.cleo)
        key = self.signed_in(self.cleo)
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            self.assertTrue(activation.reset_two_factor(self.cleo, actor=self.ada))
        self.assertFalse(self.has_app(self.cleo))
        # The passkey stays: a way in, not a second factor
        self.assertTrue(
            Authenticator.objects.filter(
                user=self.cleo, type=Authenticator.Type.WEBAUTHN
            ).exists()
        )
        # Signed out everywhere
        self.assertFalse(UserSession.objects.filter(user=self.cleo).exists())
        self.assertFalse(sso.session_alive(key, self.cleo))
        # The mail through the outbox, after the commit
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(OutgoingMail.objects.count(), 1)
        for callback in callbacks:
            callback()
        [message] = mail.outbox
        self.assertEqual(message.to, [self.cleo.email])
        self.assertEqual(message.subject, "Ada Example removed your authenticator app")
        self.assertIn("signed you out everywhere", message.body)
        self.assertIn("/accounts/settings/#sign-in", message.body)
        self.assertIn("Ada Example", message.from_email)
        # Others keep theirs
        self.assertTrue(self.has_app(self.bob))

    def test_staff_may_not_reset_staff_or_partners(self):
        for user in [self.bob, self.pia, self.root]:
            with self.subTest(user=user), self.assertRaises(PermissionError):
                activation.reset_two_factor(user, actor=self.ada)
            self.assertTrue(self.has_app(user))
        self.assertEqual(len(mail.outbox), 0)

    def test_admins_reset_everybody_else(self):
        for user in [self.bob, self.pia, self.cleo]:
            with self.subTest(user=user):
                self.assertTrue(activation.reset_two_factor(user, actor=self.root))
                self.assertFalse(self.has_app(user))

    def test_nobody_resets_themselves(self):
        for user in [self.root, self.ada]:
            with (
                self.subTest(user=user),
                self.assertRaises((activation.ActivationError, PermissionError)),
            ):
                activation.reset_two_factor(user, actor=user)
            self.assertTrue(self.has_app(user))

    def test_clients_and_partners_never(self):
        for actor in [self.cleo, self.pia]:
            with self.subTest(actor=actor), self.assertRaises(PermissionError):
                activation.reset_two_factor(self.ada, actor=actor)

    def test_without_an_app_nothing_happens(self):
        activation.reset_two_factor(self.cleo, actor=self.ada)
        mail.outbox.clear()
        key = self.signed_in(self.cleo)
        with self.captureOnCommitCallbacks(execute=True):
            self.assertFalse(activation.reset_two_factor(self.cleo, actor=self.ada))
        self.assertTrue(UserSession.objects.filter(session_key=key).exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_the_audit_log_has_it(self):
        LoggedAction.objects.all().delete()
        activation.reset_two_factor(self.cleo, actor=self.ada)
        [action] = LoggedAction.objects.filter(table_name="mfa_authenticator")
        self.assertEqual(action.action, "D")
        self.assertEqual(action.row_data["type"], "totp")
        # Never the app's secret
        self.assertNotIn("data", action.row_data)


class PagesTest(Base):
    def test_staff_on_a_client(self):
        self.client.force_login(self.ada)
        url = f"/people/{self.cleo.pk}/reset-two-factor/"
        page = self.client.get(f"/people/{self.cleo.pk}/")
        self.assertContains(page, url)
        actions = palette_data(page)["actions"]
        self.assertIn(url, [a.get("url") for a in actions])
        assert_modal(
            self,
            self.client.get(url, headers={"HX-Modal": "true"}),
            title=f"Reset two-factor for {self.cleo.display_name}?",
        )
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url)
        self.assertRedirects(
            response, f"/people/{self.cleo.pk}/", fetch_redirect_response=False
        )
        self.assertFalse(self.has_app(self.cleo))
        self.assertEqual(len(mail.outbox), 1)
        # Without an app, not offered anymore
        page = self.client.get(f"/people/{self.cleo.pk}/")
        self.assertNotContains(page, url)
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_staff_on_staff_403(self):
        self.client.force_login(self.ada)
        url = f"/people/{self.bob.pk}/reset-two-factor/"
        self.assertNotContains(self.client.get(f"/people/{self.bob.pk}/"), url)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.assertTrue(self.has_app(self.bob))

    def test_admins_on_staff(self):
        self.client.force_login(self.root)
        url = f"/people/{self.bob.pk}/reset-two-factor/"
        self.assertContains(self.client.get(f"/people/{self.bob.pk}/"), url)
        self.client.post(url)
        self.assertFalse(self.has_app(self.bob))

    def test_not_oneself(self):
        self.client.force_login(self.root)
        url = f"/people/{self.root.pk}/reset-two-factor/"
        page = self.client.get(f"/people/{self.root.pk}/")
        self.assertNotContains(page, url)
        self.assertNotIn(url, [a.get("url") for a in palette_data(page)["actions"]])
        response = self.client.post(url, follow=True)
        self.assertContains(response, "in your settings")
        self.assertTrue(self.has_app(self.root))

    def test_clients_404(self):
        self.client.force_login(self.cleo)
        url = f"/people/{self.ada.pk}/reset-two-factor/"
        self.assertEqual(self.client.post(url).status_code, 404)
        self.assertTrue(self.has_app(self.ada))


class APITest(Base):
    def post(self, user, target):
        client = Client()
        client.force_login(user)
        return client.post(
            f"/api/v1/people/{target.pk}/reset-two-factor/",
            {},
            content_type="application/json",
        )

    def test_reset(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.post(self.ada, self.cleo)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["reset"])
        self.assertFalse(self.has_app(self.cleo))
        self.assertEqual(len(mail.outbox), 1)
        response = self.post(self.ada, self.cleo)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["reset"])

    def test_refused(self):
        for actor, target, status in [
            (self.ada, self.bob, 403),
            (self.cleo, self.ada, 403),
            (self.pia, self.cleo, 403),
            (self.root, self.root, 400),
        ]:
            with self.subTest(actor=actor, target=target):
                self.assertEqual(self.post(actor, target).status_code, status)
                self.assertTrue(self.has_app(target))
        self.assertEqual(self.post(self.root, self.bob).status_code, 200)
