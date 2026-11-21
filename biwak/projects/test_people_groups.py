"""A project's people page grouped by organization (specs/organizations.md,
decided 2026-11-21): own staff, client organizations, partner
organizations, people without one; "Add people from …" for staff"""

import re

from django.test import TestCase

from biwak.test_utils import MODAL, assert_modal, organization, partner, person, project


class PeopleGroupsTest(TestCase):
    def setUp(self):
        self.own = organization("Example Team", is_own=True)
        self.ada = person("Ada")
        self.bob = person("Bob")  # own staff, not a member
        self.zoe = person("Zoe", client=True, organization="Zebra Clients")
        self.cleo = person("Cleo", client=True, organization="Alpine Clients")
        self.carl = person("Carl", client=True, organization="Alpine Clients")
        self.pia = partner("Pia", organization_name="Beta Agency")
        self.ivy = person("Ivy", client=True, organization=None)
        self.gone = person(
            "Gil", client=True, organization="Alpine Clients", is_active=False
        )
        self.dora = person("Dora", client=True, organization="Other Clients")
        self.camp = project(
            "Camp", members=[self.zoe, self.pia, self.ivy, self.cleo, self.ada]
        )
        self.url = f"/projects/{self.camp.pk}/people/"

    def page(self, user):
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def groups(self, html):
        """``[(kind, [names])]`` in the page's order"""
        return [
            (kind, re.findall(r'wb-avatar[^>]*title="([^"]*)"', section))
            for kind, section in re.findall(
                r'data-people-group="(\w+)"(.*?)</section>', html, re.DOTALL
            )
        ]

    def test_staff_see_the_groups_in_order(self):
        html = self.page(self.ada)
        self.assertEqual(
            self.groups(html),
            [
                ("own", ["Ada Example"]),
                ("client", ["Cleo Example"]),
                ("client", ["Zoe Example"]),
                ("partner", ["Pia Example"]),
                ("none", ["Ivy Example"]),
            ],
        )
        self.assertIn("Client organization", html)
        self.assertIn("Partner organization", html)
        self.assertIn("Without an organization", html)
        self.assertIn(f'href="{self.own.get_absolute_url()}"', html)

    def test_add_people_from_an_organization(self):
        html = self.page(self.ada)
        add = f"/projects/{self.camp.pk}/people/add/?organization="
        # Bob for the own staff, Carl for Alpine (not Gil, inactive);
        # nobody left at Zebra and Beta, nothing for people without one
        self.assertIn(f"{add}{self.own.pk}", html)
        self.assertIn(f"{add}{self.cleo.organization_id}", html)
        self.assertIn("Add people from Alpine Clients", html)
        self.assertNotIn(f"{add}{self.zoe.organization_id}", html)
        self.assertNotIn(f"{add}{self.pia.organization_id}", html)
        self.assertEqual(html.count(add), 2)

    def test_the_modal_offers_that_organization_s_people(self):
        self.client.force_login(self.ada)
        url = f"/projects/{self.camp.pk}/people/add/"
        alpine = self.cleo.organization
        response = self.client.get(f"{url}?organization={alpine.pk}", headers=MODAL)
        assert_modal(self, response, title="Add people from Alpine Clients")
        # Carl alone: preselected
        self.assertContains(response, f'value="{self.carl.pk}" selected')
        self.assertNotContains(response, "Bob Example")
        self.assertNotContains(response, "Dora Example")
        response = self.client.post(
            f"{url}?organization={alpine.pk}",
            {"user": self.dora.pk, "notify": "default"},
            headers=MODAL,
        )
        self.assertContains(response, "Select a valid choice")
        response = self.client.post(
            f"{url}?organization={alpine.pk}",
            {"user": self.carl.pk, "notify": "default"},
            headers=MODAL,
        )
        self.assertEqual(response["HX-Redirect"], self.url)
        self.assertTrue(self.camp.is_member(self.carl))
        self.assertEqual(self.client.get(f"{url}?organization=x").status_code, 404)
        self.assertEqual(self.client.get(f"{url}?organization=999999").status_code, 404)

    def test_clients_and_partners_see_the_groups_without_actions(self):
        for viewer in [self.zoe, self.pia]:
            with self.subTest(viewer=viewer):
                html = self.page(viewer)
                self.assertEqual(
                    [kind for kind, _names in self.groups(html)],
                    ["own", "client", "client", "partner", "none"],
                )
                self.assertNotIn("Add people from", html)
                self.assertNotIn("/organizations/", html)
                self.assertNotIn("Bob Example", html)
                self.assertNotIn("Dora Example", html)
                self.assertNotIn("Carl Example", html)
        self.client.force_login(self.zoe)
        response = self.client.get(
            f"/projects/{self.camp.pk}/people/add/?organization={self.own.pk}"
        )
        self.assertEqual(response.status_code, 403)
        # Clients see no addresses
        self.assertNotIn("ada@example.org", self.page(self.zoe))
        self.assertIn("ada@example.org", self.page(self.pia))

    def test_empty(self):
        empty = project("Empty")
        self.client.force_login(self.ada)
        response = self.client.get(f"/projects/{empty.pk}/people/")
        self.assertContains(response, "No members yet.")
