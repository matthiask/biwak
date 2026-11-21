"""The People page (specs/organizations.md, decided 2026-11-21)"""

import json
import re

from django.test import TestCase

from biwak.test_utils import organization, partner, person, project


class PeoplePageTest(TestCase):
    def setUp(self):
        self.own = organization("Example Team", is_own=True)
        self.root = person("Root", is_admin=True)
        self.ada = person("Ada")
        self.zed = person("Zed", is_active=False)
        self.cleo = person("Cleo", client=True, organization="Zebra Clients")
        self.dora = person("Dora", client=True, organization="Zebra Clients")
        self.pia = partner("Pia", organization_name="Alpine Agency")
        self.finn = person("Finn", organization=None)  # a freelancer
        self.ivy = person("Ivy", client=True, organization=None)
        self.camp = project("Camp", members=[self.ada, self.pia, self.cleo])

    def page(self, user):
        self.client.force_login(user)
        response = self.client.get("/people/")
        self.assertEqual(response.status_code, 200)
        return response

    def headings_and_names(self, response):
        """The groups' headings and names in the page's order"""
        html = response.content.decode()
        main = html.split("<main", 1)[1].split("</main>", 1)[0]
        return [
            (m[0] or m[1]).strip()
            for m in re.findall(
                r'<h2 class="h5">\s*(?:<a [^>]*>)?([^<]*)|data-kb-row\s*>\s*<div[^>]*>\s*<[^>]*>[^<]*(?:</span>|<img[^>]*>)\s*<div>\s*(?:<a [^>]*>)?([^<\n]*)',
                main,
            )
        ]

    def test_own_staff_see_everybody_in_order(self):
        response = self.page(self.ada)
        self.assertEqual(
            self.headings_and_names(response),
            [
                "Example Team",
                "Ada Example",
                "Root Example",
                "Zed Example",  # inactive: last in the group
                "Alpine Agency",
                "Pia Example",
                "Zebra Clients",
                "Cleo Example",
                "Dora Example",
                "Without an organization",
                "Finn Example",
                "Ivy Example",
            ],
        )
        self.assertContains(response, "Partner organization")
        self.assertContains(response, "Client organization")
        self.assertContains(response, "inactive")
        self.assertContains(response, f'href="{self.own.get_absolute_url()}"')
        self.assertContains(response, "cleo@example.org")
        self.assertContains(response, f'href="/people/{self.cleo.pk}/"')
        self.assertContains(response, f"/people/{self.cleo.pk}/organization/")
        # Roles
        for word in ["admin", "staff", "partner", "client"]:
            self.assertContains(response, f">{word}</span>")

    def test_a_partner_sees_the_people_of_their_projects(self):
        response = self.page(self.pia)
        self.assertEqual(
            self.headings_and_names(response),
            [
                # The own staff open the all-access Camp: its people too
                # (decided 2026-11-21); not Dora, Finn and Ivy
                "Example Team",
                "Ada Example",
                "Root Example",
                "Zed Example",
                "Alpine Agency",
                "Pia Example",
                "Zebra Clients",
                "Cleo Example",
            ],
        )
        # The same addresses as on a project's people page, no actions
        self.assertContains(response, "cleo@example.org")
        self.assertNotContains(response, "/organization/")
        self.assertNotContains(response, f'href="{self.own.get_absolute_url()}"')

    def test_a_client_sees_the_people_of_their_projects(self):
        dora_camp = project("Lake", members=[self.dora])
        self.assertTrue(dora_camp)
        response = self.page(self.cleo)
        names = self.headings_and_names(response)
        self.assertEqual(
            names,
            [
                "Example Team",
                "Ada Example",
                "Alpine Agency",
                "Pia Example",
                "Zebra Clients",
                "Cleo Example",
            ],
        )
        # Addresses of their own organization only
        self.assertContains(response, "cleo@example.org")
        self.assertNotContains(response, "ada@example.org")
        self.assertNotContains(response, "/organization/")

    def test_navigation_and_palette(self):
        response = self.page(self.cleo)
        self.assertContains(response, 'href="/people/"')
        html = response.content.decode()
        data = json.loads(
            html.split('<script id="wb-palette-data" type="application/json">')[
                1
            ].split("</script>")[0]
        )
        labels = {a["label"]: a for a in data["actions"]}
        self.assertEqual(labels["Go to people"]["url"], "/people/")
        self.assertNotIn("Go to organizations", labels)
