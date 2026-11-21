import json

from django.test import TestCase

from biwak import test_cli
from biwak.accounts.models import APIToken
from biwak.organizations.models import Organization
from biwak.test_utils import organization, partner, person


class APITest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.root = person("Root", is_admin=True)
        self.own = organization("Example Team", is_own=True)
        self.example = organization("Example Ltd", domains=["example.com"])
        self.cleo = person("Cleo", client=True, organization=self.example)

    def headers(self, user):
        _token, secret = APIToken.create_for(user=user, title="T", access="write")
        return {"authorization": f"Bearer {secret}"}

    def call(self, method, path, data=None, *, user=None):
        return getattr(self.client, method)(
            f"/api/v1/{path}",
            data,
            content_type="application/json",
            headers=self.headers(user or self.ada),
        )

    def test_only_own_staff(self):
        for user in [self.cleo, partner("Pia")]:
            with self.subTest(user=user):
                self.assertEqual(
                    self.call("get", "organizations/", user=user).status_code, 403
                )
                response = self.call("post", "organizations/", {"name": "X"}, user=user)
                self.assertEqual(response.status_code, 403)

    def test_list_and_detail(self):
        data = self.call("get", "organizations/").json()
        self.assertEqual(
            [(o["name"], o["people_count"], o["is_own"]) for o in data],
            [("Example Ltd", 1, False), ("Example Team", 2, True)],
        )
        data = self.call("get", f"organizations/{self.example.pk}/").json()
        self.assertEqual(data["domains"], ["example.com"])
        [cleo] = data["people"]
        self.assertEqual(cleo["organization_id"], self.example.pk)
        self.assertEqual(cleo["organization"], "Example Ltd")

    def test_create_rename_merge_delete(self):
        response = self.call(
            "post",
            "organizations/",
            {"name": "Exmaple Ltd", "domains": ["Example.net"]},
        )
        self.assertEqual(response.status_code, 201)
        typo = Organization.objects.get(pk=response.json()["id"])
        self.assertEqual(typo.domains, ["example.net"])
        response = self.call("post", "organizations/", {"name": "example ltd"})
        self.assertEqual(response.status_code, 400)
        response = self.call(
            "post", "organizations/", {"name": "Free", "domains": ["gmail.com"]}
        )
        self.assertEqual(response.status_code, 400)
        response = self.call(
            "patch", f"organizations/{typo.pk}/", {"name": "Exmaple Limited"}
        )
        self.assertEqual(response.json()["name"], "Exmaple Limited")
        self.assertEqual(response.json()["domains"], ["example.net"])
        dora = person("Dora", client=True, organization=typo)
        # Not with people
        self.assertEqual(
            self.call("delete", f"organizations/{typo.pk}/").status_code, 400
        )
        response = self.call(
            "post", f"organizations/{typo.pk}/merge/", {"into_id": self.example.pk}
        )
        self.assertEqual(response.json()["id"], self.example.pk)
        self.assertEqual(response.json()["domains"], ["example.com", "example.net"])
        dora.refresh_from_db()
        self.assertEqual(dora.organization, self.example)
        empty = organization("Empty Ltd")
        response = self.call("delete", f"organizations/{empty.pk}/")
        self.assertEqual(response.json()["name"], "Empty Ltd")
        self.assertFalse(Organization.objects.filter(pk=empty.pk).exists())

    def test_the_own_organization_is_for_admins(self):
        bob = person("Bob", organization=None)
        response = self.call(
            "put", f"people/{bob.pk}/organization/", {"organization_id": self.own.pk}
        )
        self.assertEqual(response.status_code, 403)
        response = self.call(
            "post", f"organizations/{self.example.pk}/merge/", {"into_id": self.own.pk}
        )
        self.assertEqual(response.status_code, 403)
        response = self.call(
            "put",
            f"people/{bob.pk}/organization/",
            {"organization_id": self.own.pk},
            user=self.root,
        )
        self.assertEqual(response.json()["organization_id"], self.own.pk)
        response = self.call(
            "put", f"people/{self.cleo.pk}/organization/", {"organization_id": None}
        )
        self.assertIsNone(response.json()["organization_id"])


class OrgsCLITest(test_cli.CLITest):
    def setUp(self):
        super().setUp()
        self.example = organization("Example Ltd", domains=["example.com"])
        self.cleo = person("Cleo", client=True, organization=self.example)

    def test_list_show_add_edit(self):
        output = self.biwak("orgs").output
        self.assertIn("Example Ltd", output)
        self.assertIn("example.com", output)
        data = json.loads(self.biwak("orgs", "--json").stdout)
        # The own organization always exists
        self.assertEqual([o["name"] for o in data], ["Example Ltd", "Our organization"])
        output = self.biwak("orgs", "show", self.example.pk).output
        self.assertIn("Cleo Example", output)
        output = self.biwak(
            "orgs", "add", "Other AG", "--domain", "other.ch", "--domain", "other.de"
        ).output
        self.assertIn("Created: Other AG", output)
        other = Organization.objects.get(name="Other AG")
        self.assertEqual(other.domains, ["other.ch", "other.de"])
        self.biwak("orgs", "edit", other.pk, "--name", "Other SA", "--no-domains")
        other.refresh_from_db()
        self.assertEqual((other.name, other.domains), ("Other SA", []))
        result = self.biwak("orgs", "add", "example ltd")
        self.assertEqual(result.exit_code, 1)

    def test_merge_move_delete(self):
        typo = organization("Exmaple Ltd")
        self.biwak("orgs", "move", self.cleo.pk, typo.pk)
        self.cleo.refresh_from_db()
        self.assertEqual(self.cleo.organization, typo)
        output = self.biwak("orgs", "merge", typo.pk, self.example.pk).output
        self.assertIn("Merged into Example Ltd", output)
        self.assertFalse(Organization.objects.filter(pk=typo.pk).exists())
        output = self.biwak("orgs", "move", self.cleo.pk).output
        self.assertIn("Cleo Example", output)
        self.assertIn("none", output)
        self.assertIn(
            "Deleted Example Ltd", self.biwak("orgs", "delete", self.example.pk).output
        )

    def test_invite_with_an_organization(self):
        data = json.loads(
            self.biwak(
                "member", "invite", self.project.pk, "dora@example.org",
                "--organization", "example ltd", "--json",
            ).stdout
        )  # fmt: skip
        self.assertEqual(data["organization_id"], self.example.pk)
        data = json.loads(
            self.biwak(
                "member", "invite", self.project.pk, "eve@example.org",
                "--organization-id", self.example.pk, "--json",
            ).stdout
        )  # fmt: skip
        self.assertEqual(data["organization"], "Example Ltd")
        output = self.biwak("members", self.project.pk).output
        self.assertIn("Example Ltd", output)
