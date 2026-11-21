"""``biwak invite`` and ``biwak invitations`` (specs/activation.md, "Inviting")"""

import json

from django.core import mail

from biwak import test_cli
from biwak.accounts.models import User
from biwak.projects import operations as project_ops
from biwak.test_utils import person, project


class InvitationsCLITest(test_cli.CLITest):
    def setUp(self):
        super().setUp()
        self.shop = project("Shop", members=[self.ada])

    def test_invite_several_to_several_projects(self):
        bob = person("Bob")
        with self.captureOnCommitCallbacks(execute=True):
            output = self.biwak(
                "invite",
                "dora@example.net",
                bob.email,
                "--project",
                self.project.pk,
                "--project",
                self.shop.pk,
                "--only-tagged",
            ).output
        self.assertIn("Invited: dora@example.net", output)
        self.assertIn("Added: Bob Example", output)
        dora = User.objects.get(email="dora@example.net")
        self.assertTrue(self.shop.is_member(dora))
        self.assertEqual(project_ops.notify_choice(bob, self.shop), "tagged")
        self.assertEqual([m.to for m in mail.outbox], [["dora@example.net"]])

    def test_errors_invite_nobody(self):
        result = self.biwak(
            "invite",
            "dora@example.net",
            "eve@example.net",
            "--staff",
            "--project",
            self.project.pk,
        )
        self.assertEqual(result.exit_code, 1)
        self.assertIn("dora@example.net: Only admins can invite staff.", result.output)
        self.assertFalse(User.objects.filter(email="dora@example.net").exists())

    def test_list_resend_withdraw(self):
        with self.captureOnCommitCallbacks(execute=True):
            dora, _created = project_ops.invite(
                self.project, email="dora@example.net", actor=self.ada
            )
        output = self.biwak("invitations").output
        self.assertIn("dora@example.net", output)
        self.assertIn("Ada Example", output)
        data = json.loads(self.biwak("invitations", "--json").stdout)
        self.assertEqual(data[0]["person"]["id"], dora.pk)
        with self.captureOnCommitCallbacks(execute=True):
            output = self.biwak("invitations", "resend", dora.pk).output
        self.assertIn("Sent again to dora@example.net.", output)
        self.assertEqual(len(mail.outbox), 2)
        output = self.biwak("invitations", "withdraw", dora.pk).output
        self.assertIn(
            f"removed from {self.project.pk}; the account is deleted.", output
        )
        self.assertFalse(User.objects.filter(pk=dora.pk).exists())

    def test_clients_cant(self):
        cleo = person("Cleo", client=True)
        self.ada = cleo  # The CLI's token is the test case's person
        result = self.biwak("invite", "x@example.net", "--project", self.project.pk)
        self.assertEqual(result.exit_code, 1)
        self.assertIn("403", result.output)
        self.assertEqual(self.biwak("invitations").exit_code, 1)
