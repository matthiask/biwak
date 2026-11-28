"""Resetting someone's sign-in (specs/two-factor.md): the operation,
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
from biwak.test_utils import assert_modal, external, person, project


class Base(TestCase):
    def setUp(self):
        self.root = person("Root", is_admin=True)
        self.ada = person("Ada")  # staff, no admin
        self.bob = person("Bob")
        self.pia = external("Pia")
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
        from biwak.accounts.models import APIToken

        passkey(self.cleo)
        APIToken.create_for(user=self.cleo, title="T", access="read")
        APIToken.create_for(user=self.bob, title="T", access="read")
        key = self.signed_in(self.cleo)
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            removed = activation.reset_sign_in(self.cleo, actor=self.ada)
        self.assertEqual(removed, activation.SignIn(app=True, passkeys=1, api_tokens=1))
        self.assertFalse(self.has_app(self.cleo))
        # Passkeys and API tokens go too (decided 2026-11-21): whoever
        # took over the account may have added them
        self.assertFalse(Authenticator.objects.filter(user=self.cleo).exists())
        self.assertFalse(APIToken.objects.filter(user=self.cleo).exists())
        self.assertTrue(APIToken.objects.filter(user=self.bob).exists())
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
        self.assertEqual(message.subject, "Ada Example reset your sign-in to Biwak")
        self.assertIn("signed you out everywhere", message.body)
        self.assertIn(
            "- your authenticator app\n- 1 passkey\n- 1 API token\n", message.body
        )
        self.assertIn("/accounts/settings/#sign-in", message.body)
        self.assertIn("Ada Example", message.from_email)
        # Others keep theirs
        self.assertTrue(self.has_app(self.bob))

    def test_removes_push_devices(self):
        # Decided 2026-11-28: "someone else may have had access"
        from biwak.accounts.models import PushSubscription

        for user in [self.cleo, self.bob]:
            PushSubscription.objects.create(
                user=user,
                endpoint=f"https://push.example.org/{user.pk}",
                p256dh="k",
                auth="a",
            )
        activation.reset_sign_in(self.cleo, actor=self.ada)
        self.assertEqual(
            set(PushSubscription.objects.values_list("user", flat=True)), {self.bob.pk}
        )

    def test_push_devices_alone(self):
        """Consistent (2026-11-28): push devices count like the rest, also
        alone: offered, removed, named in the question, the message, the
        mail and the API"""
        from biwak.accounts.models import PushSubscription

        Authenticator.objects.filter(user=self.cleo).delete()
        for number in [1, 2]:
            PushSubscription.objects.create(
                user=self.cleo,
                endpoint=f"https://push.example.org/{number}",
                p256dh="k",
                auth="a",
            )
        self.assertEqual(
            activation.sign_in(self.cleo),
            activation.SignIn(app=False, passkeys=0, api_tokens=0, push_devices=2),
        )
        self.client.force_login(self.ada)
        url = f"/people/{self.cleo.pk}/reset-sign-in/"
        self.assertContains(self.client.get(f"/people/{self.cleo.pk}/"), url)
        self.assertContains(
            self.client.get(url), "Removes 2 devices for push notifications"
        )
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url, follow=True)
        self.assertContains(
            response,
            f"Removed from {self.cleo.display_name}: 2 devices for push notifications.",
        )
        self.assertFalse(PushSubscription.objects.filter(user=self.cleo).exists())
        self.assertIn("- 2 devices for push notifications\n", mail.outbox[0].body)

    def test_staff_may_not_reset_staff_or_externals(self):
        for user in [self.bob, self.pia, self.root]:
            with self.subTest(user=user), self.assertRaises(PermissionError):
                activation.reset_sign_in(user, actor=self.ada)
            self.assertTrue(self.has_app(user))
        self.assertEqual(len(mail.outbox), 0)

    def test_admins_reset_everybody_else(self):
        for user in [self.bob, self.pia, self.cleo]:
            with self.subTest(user=user):
                self.assertTrue(activation.reset_sign_in(user, actor=self.root))
                self.assertFalse(self.has_app(user))

    def test_nobody_resets_themselves(self):
        for user in [self.root, self.ada]:
            with (
                self.subTest(user=user),
                self.assertRaises((activation.ActivationError, PermissionError)),
            ):
                activation.reset_sign_in(user, actor=user)
            self.assertTrue(self.has_app(user))

    def test_clients_and_externals_never(self):
        for actor in [self.cleo, self.pia]:
            with self.subTest(actor=actor), self.assertRaises(PermissionError):
                activation.reset_sign_in(self.ada, actor=actor)

    def test_passkeys_or_tokens_alone(self):
        """Decided 2026-11-21: one recovery and incident action, whatever the
        person has"""
        from biwak.accounts.models import APIToken

        Authenticator.objects.filter(user=self.cleo).delete()
        passkey(self.cleo)
        passkey(self.cleo)
        with self.captureOnCommitCallbacks(execute=True):
            removed = activation.reset_sign_in(self.cleo, actor=self.ada)
        self.assertEqual(
            removed, activation.SignIn(app=False, passkeys=2, api_tokens=0)
        )
        self.assertFalse(Authenticator.objects.filter(user=self.cleo).exists())
        self.assertIn("- 2 passkeys\n", mail.outbox[0].body)
        self.assertNotIn("authenticator app\n", mail.outbox[0].body)
        APIToken.create_for(user=self.cleo, title="T", access="read")
        key = self.signed_in(self.cleo)
        with self.captureOnCommitCallbacks(execute=True):
            removed = activation.reset_sign_in(self.cleo, actor=self.ada)
        self.assertEqual(
            removed, activation.SignIn(app=False, passkeys=0, api_tokens=1)
        )
        self.assertFalse(APIToken.objects.filter(user=self.cleo).exists())
        self.assertFalse(UserSession.objects.filter(session_key=key).exists())
        self.assertIn("- 1 API token\n", mail.outbox[1].body)

    def test_with_nothing_nothing_happens(self):
        activation.reset_sign_in(self.cleo, actor=self.ada)
        mail.outbox.clear()
        key = self.signed_in(self.cleo)
        with self.captureOnCommitCallbacks(execute=True):
            self.assertFalse(activation.reset_sign_in(self.cleo, actor=self.ada))
        self.assertTrue(UserSession.objects.filter(session_key=key).exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_the_audit_log_has_it(self):
        LoggedAction.objects.all().delete()
        activation.reset_sign_in(self.cleo, actor=self.ada)
        [action] = LoggedAction.objects.filter(table_name="mfa_authenticator")
        self.assertEqual(action.action, "D")
        self.assertEqual(action.row_data["type"], "totp")
        # Never the app's secret
        self.assertNotIn("data", action.row_data)


class PagesTest(Base):
    def test_staff_on_a_client(self):
        self.client.force_login(self.ada)
        url = f"/people/{self.cleo.pk}/reset-sign-in/"
        page = self.client.get(f"/people/{self.cleo.pk}/")
        self.assertContains(page, url)
        actions = palette_data(page)["actions"]
        self.assertIn(url, [a.get("url") for a in actions])
        assert_modal(
            self,
            self.client.get(url, headers={"HX-Modal": "true"}),
            title=f"Reset the sign-in of {self.cleo.display_name}?",
        )
        # About the person, not the admin reading it
        question = self.client.get(url)
        self.assertContains(question, "Removes their authenticator app and signs")
        self.assertContains(question, "They get a mail about it.")
        self.assertNotContains(question, "your authenticator")
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url, follow=True)
        self.assertRedirects(response, f"/people/{self.cleo.pk}/")
        self.assertContains(
            response,
            f"Removed from {self.cleo.display_name}: their authenticator app."
            " They have been signed out everywhere and got a mail about it.",
        )
        self.assertFalse(self.has_app(self.cleo))
        self.assertEqual(len(mail.outbox), 1)
        # With nothing left, not offered anymore
        page = self.client.get(f"/people/{self.cleo.pk}/")
        self.assertNotContains(page, url)
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_no_mail_no_promise(self):
        """A bounced address gets no mail, and neither the question nor the
        message says it does"""
        from django.utils import timezone

        self.cleo.mail_undeliverable_at = timezone.now()
        self.cleo.save()
        self.client.force_login(self.ada)
        url = f"/people/{self.cleo.pk}/reset-sign-in/"
        self.assertNotContains(self.client.get(url), "a mail about it")
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(url, follow=True)
        self.assertContains(response, "They have been signed out everywhere.")
        self.assertNotContains(response, "got a mail")
        self.assertEqual(len(mail.outbox), 0)

    def test_staff_on_staff_403(self):
        self.client.force_login(self.ada)
        url = f"/people/{self.bob.pk}/reset-sign-in/"
        self.assertNotContains(self.client.get(f"/people/{self.bob.pk}/"), url)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.assertTrue(self.has_app(self.bob))

    def test_admins_on_staff(self):
        self.client.force_login(self.root)
        url = f"/people/{self.bob.pk}/reset-sign-in/"
        self.assertContains(self.client.get(f"/people/{self.bob.pk}/"), url)
        self.client.post(url)
        self.assertFalse(self.has_app(self.bob))

    def test_not_oneself(self):
        self.client.force_login(self.root)
        url = f"/people/{self.root.pk}/reset-sign-in/"
        page = self.client.get(f"/people/{self.root.pk}/")
        self.assertNotContains(page, url)
        self.assertNotIn(url, [a.get("url") for a in palette_data(page)["actions"]])
        response = self.client.post(url, follow=True)
        self.assertContains(response, "in your settings")
        self.assertTrue(self.has_app(self.root))

    def test_clients_404(self):
        self.client.force_login(self.cleo)
        url = f"/people/{self.ada.pk}/reset-sign-in/"
        self.assertEqual(self.client.post(url).status_code, 404)
        self.assertTrue(self.has_app(self.ada))


class APITest(Base):
    def post(self, user, target, path="reset-sign-in"):
        client = Client()
        client.force_login(user)
        return client.post(
            f"/api/v1/people/{target.pk}/{path}/",
            {},
            content_type="application/json",
        )

    def test_reset(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.post(self.ada, self.cleo)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["reset"])
        self.assertEqual(
            response.json()["removed"],
            {"app": True, "passkeys": 0, "api_tokens": 0, "push_devices": 0},
        )
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

    def test_the_old_url(self):
        """``reset-two-factor/`` stays as an alias (renamed 2026-11-21)"""
        response = self.post(self.ada, self.cleo, "reset-two-factor")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["reset"])
        self.assertFalse(self.has_app(self.cleo))
