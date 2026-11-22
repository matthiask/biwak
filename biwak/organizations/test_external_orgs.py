"""Admins manage the internal team and externals, staff the clients
(decided 2026-11-21, specs/organizations.md): who belongs to an external
organization (one with staff), its domains, merging it and moving staff
are for admins; client organizations stay all staff's. Through the
operations, the pages, the invitations, the API and the CLI."""

import json

from django.db import transaction
from django.test import TestCase

from biwak import test_cli
from biwak.accounts.models import APIToken, User
from biwak.organizations import operations as org_ops
from biwak.organizations.models import Organization
from biwak.palette.test_actions import palette_data
from biwak.projects import operations as project_ops
from biwak.test_utils import external, invite_data, organization, person, project


class ExternalOrgsTestCase(TestCase):
    def setUp(self):
        self.own = organization("Example Team", is_own=True)
        self.ada = person("Ada")  # own staff, no admin
        self.root = person("Root", is_admin=True)
        self.agency = organization("Example Agency", domains=["agency.example"])
        self.pia = external("Pia", organization_name="Example Agency")
        self.clients = organization("Example Ltd", domains=["clients.example"])
        self.cleo = person("Cleo", client=True, organization=self.clients)
        self.others = organization("Other Ltd")
        self.project = project("Camp", members=[self.ada])


class OperationsTest(ExternalOrgsTestCase):
    def test_external_organization(self):
        self.assertTrue(org_ops.is_external_organization(self.agency))
        self.assertFalse(org_ops.is_external_organization(self.clients))
        self.assertFalse(org_ops.is_external_organization(self.own))
        self.assertEqual(set(org_ops.external_organizations()), {self.agency})

    def test_staff_change_client_organizations_only(self):
        refused = [
            lambda actor: org_ops.set_organization(self.cleo, self.agency, actor=actor),
            lambda actor: org_ops.set_organization(self.pia, self.others, actor=actor),
            lambda actor: org_ops.set_organization(self.pia, None, actor=actor),
            lambda actor: org_ops.merge(self.clients, self.agency, actor=actor),
            lambda actor: org_ops.merge(self.agency, self.others, actor=actor),
            lambda actor: org_ops.update_organization(
                self.agency, domains=["agency.example", "more.example"], actor=actor
            ),
        ]
        for change in refused:
            with self.assertRaises(PermissionError), transaction.atomic():
                change(self.ada)
        # A staff member without an organization (an external) too
        finn = person("Finn", organization=None)
        with self.assertRaises(PermissionError):
            org_ops.set_organization(finn, self.clients, actor=self.ada)
        # Renaming stays everybody's
        org_ops.update_organization(
            self.agency, name="Example Agency AG", actor=self.ada
        )
        # Clients between client organizations: staff
        org_ops.set_organization(self.cleo, self.others, actor=self.ada)
        org_ops.set_organization(self.cleo, None, actor=self.ada)
        org_ops.update_organization(
            self.clients, domains=["clients.example", "x.example"], actor=self.ada
        )
        org_ops.merge(self.clients, self.others, actor=self.ada)

    def test_admins_change_everything(self):
        org_ops.update_organization(
            self.agency, domains=["agency.example", "more.example"], actor=self.root
        )
        org_ops.set_organization(self.pia, self.others, actor=self.root)
        self.assertTrue(org_ops.is_external_organization(self.others))
        org_ops.merge(self.agency, self.others, actor=self.root)
        self.assertFalse(Organization.objects.filter(pk=self.agency.pk).exists())

    def test_inviting(self):
        def invite(email, actor, organization=None):
            return project_ops.invite_people(
                [self.project],
                [{"email": email, "full_name": "", "organization": organization}],
                actor=actor,
            )

        with self.assertRaisesMessage(
            project_ops.InvitationErrors, "or an external organization"
        ):
            invite("dora@example.org", self.ada, self.agency)
        # The domain's suggestion only counts for admins
        invite("dan@agency.example", self.ada)
        self.assertIsNone(User.objects.get(email="dan@agency.example").organization)
        invite("eve@clients.example", self.ada)
        self.assertEqual(
            User.objects.get(email="eve@clients.example").organization, self.clients
        )
        invite("gus@agency.example", self.root)
        self.assertEqual(
            User.objects.get(email="gus@agency.example").organization, self.agency
        )
        invite("hal@example.org", self.root, self.agency)


class PagesTest(ExternalOrgsTestCase):
    def test_moving_people(self):
        self.client.force_login(self.ada)
        url = f"/people/{self.cleo.pk}/organization/"
        response = self.client.post(url, {"organization": "Example Agency"})
        self.assertContains(response, "Only admins change who belongs")
        self.client.post(url, {"organization": "Other Ltd"})
        self.cleo.refresh_from_db()
        self.assertEqual(self.cleo.organization, self.others)
        response = self.client.post(
            f"/people/{self.pia.pk}/organization/", {"organization": "Other Ltd"}
        )
        self.assertContains(response, "Only admins change who belongs")
        self.client.force_login(self.root)
        self.client.post(
            f"/people/{self.pia.pk}/organization/", {"organization": "Other Ltd"}
        )
        self.pia.refresh_from_db()
        self.assertEqual(self.pia.organization, self.others)

    def test_buttons(self):
        self.client.force_login(self.ada)
        response = self.client.get(self.agency.get_absolute_url())
        self.assertNotContains(response, f"/organizations/{self.agency.pk}/merge/")
        self.assertNotContains(response, f"/people/{self.pia.pk}/organization/")
        response = self.client.get(self.clients.get_absolute_url())
        self.assertContains(response, f"/organizations/{self.clients.pk}/merge/")
        self.assertContains(response, f"/people/{self.cleo.pk}/organization/")
        # The People page: "Change organization" for clients of client
        # organizations only
        response = self.client.get("/people/")
        self.assertContains(response, f"/people/{self.cleo.pk}/organization/")
        self.assertNotContains(response, f"/people/{self.pia.pk}/organization/")
        # The palette offers what the buttons do
        response = self.client.get(self.agency.get_absolute_url())
        labels = {a["label"] for a in palette_data(response)["actions"]}
        self.assertNotIn("Merge…", labels)
        self.client.force_login(self.root)
        response = self.client.get(self.agency.get_absolute_url())
        self.assertIn("Merge…", {a["label"] for a in palette_data(response)["actions"]})
        self.assertContains(response, f"/organizations/{self.agency.pk}/merge/")
        self.assertContains(response, f"/people/{self.pia.pk}/organization/")

    def test_merging(self):
        self.client.force_login(self.ada)
        self.assertEqual(
            self.client.get(f"/organizations/{self.agency.pk}/merge/").status_code, 403
        )
        response = self.client.get(f"/organizations/{self.clients.pk}/merge/")
        self.assertContains(response, "Other Ltd")
        self.assertNotContains(response, "Example Agency")
        response = self.client.post(
            f"/organizations/{self.clients.pk}/merge/", {"into": self.agency.pk}
        )
        self.assertContains(response, "Select a valid choice")
        self.assertTrue(Organization.objects.filter(pk=self.clients.pk).exists())

    def test_domains(self):
        self.client.force_login(self.ada)
        url = f"/organizations/{self.agency.pk}/edit/"
        response = self.client.get(url)
        self.assertContains(response, "only admins change its domains")
        self.client.post(url, {"name": "Example Agency", "domains": "x.example"})
        self.agency.refresh_from_db()
        self.assertEqual(self.agency.domains, ["agency.example"])
        self.client.force_login(self.root)
        self.client.post(url, {"name": "Example Agency", "domains": "x.example"})
        self.agency.refresh_from_db()
        self.assertEqual(self.agency.domains, ["x.example"])

    def test_inviting_several_rows(self):
        self.client.force_login(self.ada)
        response = self.client.post(
            f"/projects/{self.project.pk}/people/invite/",
            invite_data(
                [self.project],
                {"email": "dora@example.org", "organization": "Example Agency"},
                {"email": "eve@example.org", "organization": "Example Ltd"},
            ),
        )
        self.assertContains(response, "or an external organization")
        self.assertFalse(User.objects.filter(email="eve@example.org").exists())
        response = self.client.post(
            f"/projects/{self.project.pk}/people/invite/",
            invite_data(
                [self.project],
                {"email": "eve@example.org", "organization": "Example Ltd"},
            ),
        )
        self.assertEqual(response.status_code, 302)


class APITest(ExternalOrgsTestCase):
    def call(self, method, path, data=None, *, user):
        _token, secret = APIToken.create_for(user=user, title="T", access="write")
        return getattr(self.client, method)(
            f"/api/v1/{path}",
            data,
            content_type="application/json",
            headers={"authorization": f"Bearer {secret}"},
        )

    def test_staff_refused_admins_allowed(self):
        changes = [
            ("put", f"people/{self.pia.pk}/organization/", {"organization_id": None}),
            (
                "put",
                f"people/{self.cleo.pk}/organization/",
                {"organization_id": self.agency.pk},
            ),
            (
                "post",
                f"organizations/{self.agency.pk}/merge/",
                {"into_id": self.others.pk},
            ),
            ("patch", f"organizations/{self.agency.pk}/", {"domains": ["x.example"]}),
        ]
        for method, path, data in changes:
            with self.subTest(path=path):
                response = self.call(method, path, data, user=self.ada)
                self.assertEqual(response.status_code, 403, response.content)
        response = self.call(
            "post",
            f"projects/{self.project.pk}/members/invite/",
            {"email": "dora@example.org", "organization_id": self.agency.pk},
            user=self.ada,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("external organization", response.json()["detail"])
        # Client organizations: staff
        response = self.call(
            "put",
            f"people/{self.cleo.pk}/organization/",
            {"organization_id": self.others.pk},
            user=self.ada,
        )
        self.assertEqual(response.status_code, 200)
        # The merge last: it deletes the agency
        for method, path, data in [changes[3], changes[0], changes[1], changes[2]]:
            with self.subTest(path=path, user="root"):
                response = self.call(method, path, data, user=self.root)
                self.assertEqual(response.status_code, 200, response.content)


class CLITest(test_cli.CLITest):
    def setUp(self):
        super().setUp()
        self.agency = organization("Example Agency")
        self.pia = external("Pia", organization_name="Example Agency")
        self.clients = organization("Example Ltd")
        self.cleo = person("Cleo", client=True, organization=self.clients)

    def test_staff_move_clients_only(self):
        result = self.biwak("orgs", "move", self.cleo.pk, self.agency.pk)
        self.assertEqual(result.exit_code, 1)
        self.assertIn("Only admins", result.output)
        result = self.biwak("orgs", "merge", self.agency.pk, self.clients.pk)
        self.assertEqual(result.exit_code, 1)
        result = self.biwak("orgs", "move", self.cleo.pk, "--json")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIsNone(json.loads(result.stdout)["organization_id"])
