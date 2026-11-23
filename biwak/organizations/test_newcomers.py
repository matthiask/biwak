"""People without an organization moving along when an organization gets
new domains (decided 2026-11-23, specs/organizations.md, "Domains")"""

import datetime as dt
import json

from django.core.exceptions import ValidationError
from django.test import TestCase

from biwak import test_cli
from biwak.accounts.models import APIToken
from biwak.organizations import operations as org_ops
from biwak.organizations.models import Organization
from biwak.test_utils import (
    MODAL,
    assert_modal_redirect,
    external,
    organization,
    person,
)


def person_at(name, email, **kwargs):
    user = person(name, **kwargs)
    user.email = email
    user.save(update_fields=["email"])
    return user


class Case(TestCase):
    def setUp(self):
        self.own = organization("Example Team", is_own=True)
        self.ada = person("Ada")
        self.root = person("Root", is_admin=True)
        self.shop = organization("Example Shop", domains=["shop.example"])
        # Without an organization: a client, staff who left, an inactive
        # client, somebody with an organization and one elsewhere
        self.cleo = person_at(
            "Cleo", "cleo@shop.example", client=True, organization=None
        )
        self.finn = person_at(
            "Finn",
            "finn@team.example",
            organization=None,
            is_active=False,
            left_at=dt.date(2025, 3, 3),
        )
        self.gus = person_at(
            "Gus", "gus@Team.Example", client=True, organization=None, is_active=False
        )
        self.hal = person_at(
            "Hal", "hal@team.example", client=True, organization=self.shop
        )
        self.ivy = person_at("Ivy", "ivy@other.example", client=True, organization=None)

    def organization_of(self, user):
        user.refresh_from_db()
        return user.organization


class OperationsTest(Case):
    def test_newcomers(self):
        found = org_ops.newcomers(["team.example"], actor=self.root, org=self.own)
        self.assertEqual(found.movable, [self.finn, self.gus])
        self.assertEqual(found.refused, [])
        self.assertEqual(
            found.question("Example Team"),
            "2 people with addresses at team.example have no organization."
            " Move them to Example Team too?",
        )
        # Staff only move clients, and nobody into the own organization
        found = org_ops.newcomers(["team.example"], actor=self.ada, org=None)
        self.assertEqual(found.movable, [self.gus])
        self.assertEqual([user for user, _reason in found.refused], [self.finn])
        self.assertIn("Left out: Finn Example. Only admins", found.left_out())
        found = org_ops.newcomers(["team.example"], actor=self.ada, org=self.own)
        self.assertEqual(found.movable, [])
        self.assertEqual(org_ops.newcomers([], actor=self.root).movable, [])

    def test_create_moves_them(self):
        # Staff can't move staff
        with self.assertRaises(PermissionError):
            org_ops.create_organization(
                name="Example Lab",
                domains=["team.example"],
                actor=self.ada,
                move=[self.finn],
            )
        self.assertFalse(Organization.objects.filter(name="Example Lab").exists())
        org = org_ops.create_organization(
            name="Example Lab",
            domains=["team.example"],
            actor=self.ada,
            move=[self.gus],
        )
        self.assertEqual(self.organization_of(self.gus), org)
        self.assertIsNone(self.organization_of(self.finn))

    def test_update_moves_them(self):
        # Only people without an organization at a new domain
        for user in [self.cleo, self.hal]:
            with self.subTest(user=user), self.assertRaises(ValidationError):
                org_ops.update_organization(
                    self.shop,
                    domains=["shop.example", "other.example", "team.example"],
                    actor=self.root,
                    move=[user],
                )
            self.shop.refresh_from_db()
        org_ops.update_organization(
            self.shop,
            domains=["shop.example", "other.example"],
            actor=self.ada,
            move=[self.ivy],
        )
        self.assertEqual(self.organization_of(self.ivy), self.shop)
        self.assertIsNone(self.organization_of(self.cleo))
        # Staff who left, into the own organization by an admin
        org_ops.update_organization(
            self.own, domains=["team.example"], actor=self.root, move=[self.finn]
        )
        self.assertEqual(self.organization_of(self.finn), self.own)
        self.assertIsNone(self.organization_of(self.gus))


class PagesTest(Case):
    def edit(self, org, data, *, user=None):
        self.client.force_login(user or self.root)
        return self.client.post(
            f"/organizations/{org.pk}/edit/", {"name": org.name, **data}, headers=MODAL
        )

    def test_asks_once_all_ticked(self):
        response = self.edit(self.own, {"domains": "team.example"})
        self.assertContains(
            response,
            "2 people with addresses at team.example have no organization."
            " Move them to Example Team too?",
        )
        self.assertContains(response, "Finn Example (finn@team.example)")
        self.assertContains(response, "Gus Example (gus@Team.Example)")
        self.assertContains(
            response, f'name="offered" value="{self.finn.pk} {self.gus.pk}"'
        )
        self.assertEqual(response.content.decode().count("checked"), 2)
        self.own.refresh_from_db()
        self.assertEqual(self.own.domains, [])  # Not saved yet
        # Saved, with those ticked
        response = self.edit(
            self.own,
            {
                "domains": "team.example",
                "offered": f"{self.finn.pk} {self.gus.pk}",
                "move": [self.finn.pk],
            },
        )
        assert_modal_redirect(self, response, self.own.get_absolute_url())
        self.own.refresh_from_db()
        self.assertEqual(self.own.domains, ["team.example"])
        self.assertEqual(self.organization_of(self.finn), self.own)
        self.assertIsNone(self.organization_of(self.gus))
        self.assertEqual(self.organization_of(self.hal), self.shop)

    def test_unticked_nobody_moves(self):
        response = self.edit(
            self.own,
            {"domains": "team.example", "offered": f"{self.finn.pk} {self.gus.pk}"},
        )
        assert_modal_redirect(self, response)
        self.assertIsNone(self.organization_of(self.finn))
        self.assertIsNone(self.organization_of(self.gus))

    def test_asks_again_about_others(self):
        # The domains changed after the question: new ones are asked about,
        # ticked; those unticked stay so
        response = self.edit(
            self.own,
            {
                "domains": "team.example other.example",
                "offered": f"{self.finn.pk} {self.gus.pk}",
                "move": [self.finn.pk],
            },
        )
        self.assertContains(
            response, "3 people with addresses at team.example or other.example"
        )
        self.assertContains(response, f'value="{self.finn.pk}"')
        self.assertEqual(response.content.decode().count("checked"), 2)
        self.assertIsNone(self.organization_of(self.finn))

    def test_without_newcomers_or_unchanged_domains_no_question(self):
        response = self.edit(self.shop, {"domains": "shop.example"})
        assert_modal_redirect(self, response)
        response = self.edit(self.shop, {"domains": "shop.example nobody.example"})
        assert_modal_redirect(self, response)

    def test_create(self):
        self.client.force_login(self.ada)
        response = self.client.post(
            "/organizations/new/",
            {"name": "Example Lab", "domains": "team.example"},
            headers=MODAL,
        )
        # Staff: only the client, Finn is staff
        self.assertContains(
            response,
            "One person with an address at team.example has no organization."
            " Move them to Example Lab too?",
        )
        self.assertContains(response, "Left out: Finn Example. Only admins")
        self.assertNotContains(response, "finn@team.example")
        self.assertFalse(Organization.objects.filter(name="Example Lab").exists())
        response = self.client.post(
            "/organizations/new/",
            {
                "name": "Example Lab",
                "domains": "team.example",
                "offered": str(self.gus.pk),
                "move": [self.gus.pk],
            },
            headers=MODAL,
        )
        lab = Organization.objects.get(name="Example Lab")
        assert_modal_redirect(self, response, lab.get_absolute_url())
        self.assertEqual(self.organization_of(self.gus), lab)
        self.assertIsNone(self.organization_of(self.finn))

    def test_staff_not_into_the_own_organization(self):
        # Nobody to offer: saved without asking (staff may change the own
        # organization's domains without single sign-on)
        response = self.edit(self.own, {"domains": "team.example"}, user=self.ada)
        assert_modal_redirect(self, response)
        self.assertIsNone(self.organization_of(self.gus))
        # Not by sending the IDs either: they aren't offered
        self.own.domains = []
        self.own.save()
        response = self.edit(
            self.own,
            {
                "domains": "team.example",
                "offered": str(self.gus.pk),
                "move": [self.gus.pk],
            },
            user=self.ada,
        )
        assert_modal_redirect(self, response)
        self.assertIsNone(self.organization_of(self.gus))

    def test_clients_and_externals_cant(self):
        for user in [self.cleo, external("Pia")]:
            self.client.force_login(user)
            with self.subTest(user=user):
                response = self.client.post(
                    "/organizations/new/",
                    {"name": "Example Lab", "domains": "team.example"},
                )
                self.assertEqual(response.status_code, 403)
                response = self.client.post(
                    f"/organizations/{self.shop.pk}/edit/",
                    {
                        "name": "Example Shop",
                        "domains": "shop.example team.example",
                        "offered": str(self.gus.pk),
                        "move": [self.gus.pk],
                    },
                )
                self.assertEqual(response.status_code, 403)
        self.assertIsNone(self.organization_of(self.gus))


class APITest(Case):
    def call(self, method, path, data, *, user=None):
        _token, secret = APIToken.create_for(
            user=user or self.root, title="T", access="write"
        )
        return getattr(self.client, method)(
            f"/api/v1/{path}",
            data,
            content_type="application/json",
            headers={"authorization": f"Bearer {secret}"},
        )

    def test_asks_then_moves(self):
        path = f"organizations/{self.own.pk}/"
        response = self.call("patch", path, {"domains": ["team.example"]})
        self.assertEqual(response.status_code, 400)
        detail = response.json()["detail"]
        self.assertIn("2 people with addresses at team.example", detail)
        self.assertIn(f"Finn Example ({self.finn.pk})", detail)
        self.assertIn("move_ids", detail)
        self.own.refresh_from_db()
        self.assertEqual(self.own.domains, [])
        response = self.call(
            "patch", path, {"domains": ["team.example"], "move_ids": [self.finn.pk]}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [p["name"] for p in response.json()["people"]],
            ["Ada Example", "Finn Example", "Root Example"],
        )
        self.assertIsNone(self.organization_of(self.gus))

    def test_nobody(self):
        response = self.call(
            "post",
            "organizations/",
            {"name": "Example Lab", "domains": ["team.example"], "move_ids": []},
        )
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(self.organization_of(self.finn))

    def test_create_as_staff(self):
        response = self.call(
            "post",
            "organizations/",
            {"name": "Example Lab", "domains": ["team.example"]},
            user=self.ada,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Left out: Finn Example", response.json()["detail"])
        response = self.call(
            "post",
            "organizations/",
            {
                "name": "Example Lab",
                "domains": ["team.example"],
                "move_ids": [self.finn.pk],
            },
            user=self.ada,
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Organization.objects.filter(name="Example Lab").exists())
        response = self.call(
            "post",
            "organizations/",
            {
                "name": "Example Lab",
                "domains": ["team.example"],
                "move_ids": [self.gus.pk],
            },
            user=self.ada,
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.organization_of(self.gus).name, "Example Lab")
        # Somebody with an organization: refused
        response = self.call(
            "patch",
            f"organizations/{self.shop.pk}/",
            {"domains": ["shop.example", "team.example"], "move_ids": [self.hal.pk]},
            user=self.ada,
        )
        self.assertEqual(response.status_code, 400)

    def test_clients_and_externals_cant(self):
        for user in [self.cleo, external("Pia")]:
            with self.subTest(user=user):
                response = self.call(
                    "patch",
                    f"organizations/{self.shop.pk}/",
                    {"domains": ["team.example"], "move_ids": [self.gus.pk]},
                    user=user,
                )
                self.assertEqual(response.status_code, 403)
        self.assertIsNone(self.organization_of(self.gus))


class CLITest(test_cli.CLITest):
    def setUp(self):
        super().setUp()
        self.lab = organization("Example Lab")
        self.gus = person_at("Gus", "gus@lab.example", client=True, organization=None)

    def test_update_asks_then_moves(self):
        result = self.biwak("orgs", "update", self.lab.pk, "--domain", "lab.example")
        self.assertEqual(result.exit_code, 1)
        self.assertIn("One person with an address at lab.example", result.output)
        self.assertIn(f"Gus Example ({self.gus.pk})", result.output)
        output = self.biwak(
            "orgs", "update", self.lab.pk, "--domain", "lab.example",
            "--move", self.gus.pk,
        ).output  # fmt: skip
        self.assertIn("Gus Example", output)
        self.gus.refresh_from_db()
        self.assertEqual(self.gus.organization, self.lab)

    def test_create_moving_nobody(self):
        data = json.loads(
            self.biwak(
                "orgs", "create", "Example Bench", "--domain", "lab.example",
                "--move-nobody", "--json",
            ).stdout
        )  # fmt: skip
        self.assertEqual(data["people"], [])
        self.gus.refresh_from_db()
        self.assertIsNone(self.gus.organization)
