"""``biwak people`` (specs/activation.md)"""

import json

from django.core import mail
from django.utils import timezone

from biwak import test_cli
from biwak.accounts.models import User
from biwak.test_utils import external, person


class PeopleCLITest(test_cli.CLITest):
    def setUp(self):
        super().setUp()
        self.cleo = person("Cleo", client=True, is_active=False)
        self.dora = person("Dora", client=True, is_active=False)
        self.pia = external("Pia", is_active=False)

    def active(self, user):
        user.refresh_from_db()
        return user.is_active

    def test_list_inactive(self):
        output = self.biwak("people", "--inactive").output
        self.assertIn("cleo@example.org", output)
        self.assertNotIn("ada@example.org", output)
        data = json.loads(self.biwak("people", "--inactive", "--json").stdout)
        self.assertEqual(
            {p["id"] for p in data}, {self.cleo.pk, self.dora.pk, self.pia.pk}
        )
        self.assertIn("ada@example.org", self.biwak("people").output)

    def test_activate_with_the_mail(self):
        with self.captureOnCommitCallbacks(execute=True):
            output = self.biwak(
                "people", "activate", self.cleo.pk, self.dora.pk, "--mail"
            ).output
        self.assertIn(f"Activated: Cleo Example ({self.cleo.pk}) (mailed)", output)
        self.assertTrue(self.active(self.dora))
        self.assertEqual(len(mail.outbox), 2)

    def test_activate_without_the_mail(self):
        self.biwak("people", "activate", self.cleo.pk)
        self.assertTrue(self.active(self.cleo))
        self.assertEqual(len(mail.outbox), 0)

    def test_staff_may_not_activate_externals_and_nothing_changes(self):
        result = self.biwak("people", "activate", self.cleo.pk, self.pia.pk)
        self.assertEqual(result.exit_code, 1)
        self.assertIn("only admins change staff", result.output)
        self.assertFalse(self.active(self.cleo))

    def test_admins_and_deactivate(self):
        User.objects.filter(pk=self.ada.pk).update(is_admin=True)
        self.biwak("people", "activate", self.pia.pk)
        self.assertTrue(self.active(self.pia))
        output = self.biwak("people", "deactivate", self.pia.pk).output
        self.assertIn("Deactivated: Pia Example", output)
        self.assertFalse(self.active(self.pia))
        result = self.biwak("people", "deactivate", self.ada.pk)
        self.assertEqual(result.exit_code, 1)
        self.assertIn("yourself", result.output)

    def test_bounced_is_not_mailed(self):
        User.objects.filter(pk=self.cleo.pk).update(
            mail_undeliverable_at=timezone.now()
        )
        with self.captureOnCommitCallbacks(execute=True):
            self.biwak("people", "activate", self.cleo.pk, "--mail")
        self.assertTrue(self.active(self.cleo))
        self.assertEqual(len(mail.outbox), 0)

    def test_reset_sign_in(self):
        """specs/two-factor.md"""
        from allauth.mfa.models import Authenticator

        from biwak.accounts.test_two_factor import app, passkey

        User.objects.filter(pk=self.cleo.pk).update(is_active=True)
        app(self.cleo)
        passkey(self.cleo)
        with self.captureOnCommitCallbacks(execute=True):
            output = self.biwak("people", "reset-sign-in", self.cleo.pk).output
        self.assertIn(
            f"Reset: Cleo Example ({self.cleo.pk}), removed authenticator app,"
            " 1 passkey(s), signed out everywhere",
            output,
        )
        self.assertFalse(Authenticator.objects.filter(user=self.cleo).exists())
        self.assertEqual(len(mail.outbox), 1)
        data = json.loads(
            self.biwak("people", "reset-sign-in", self.cleo.pk, "--json").stdout
        )
        self.assertFalse(data["reset"])
        result = self.biwak("people", "reset-sign-in", self.ada.pk)
        self.assertEqual(result.exit_code, 1)

    def test_reset_two_factor_is_an_alias(self):
        from biwak.accounts.test_two_factor import app

        User.objects.filter(pk=self.cleo.pk).update(is_active=True)
        app(self.cleo)
        output = self.biwak("people", "reset-two-factor", self.cleo.pk).output
        self.assertIn(f"Reset: Cleo Example ({self.cleo.pk})", output)
        self.assertNotIn("reset-two-factor", self.biwak("people", "--help").output)
