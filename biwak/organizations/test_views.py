import json

from django.core import mail
from django.test import TestCase

from biwak.accounts.models import User
from biwak.organizations.models import Organization
from biwak.projects.models import Project
from biwak.test_utils import (
    MODAL,
    assert_modal,
    assert_modal_redirect,
    assert_page,
    organization,
    partner,
    person,
)


class PagesTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.root = person("Root", is_admin=True)
        self.own = organization("Example Team", is_own=True)
        self.example = organization("Example Ltd", domains=["example.com"])
        self.cleo = person("Cleo", client=True, organization=self.example)
        self.client.force_login(self.ada)

    def test_only_the_installations_own_staff(self):
        urls = [
            "/organizations/",
            "/organizations/new/",
            f"/organizations/{self.example.pk}/",
            f"/organizations/{self.example.pk}/edit/",
            f"/organizations/{self.example.pk}/merge/",
            f"/organizations/{self.example.pk}/delete/",
            f"/people/{self.cleo.pk}/organization/",
        ]
        for user in [self.cleo, partner("Pia")]:
            self.client.force_login(user)
            for url in urls:
                with self.subTest(user=user, url=url):
                    self.assertEqual(self.client.get(url).status_code, 403)

    def test_list_and_detail(self):
        response = self.client.get("/organizations/")
        self.assertContains(response, "Example Ltd")
        self.assertContains(response, "example.com")
        self.assertContains(response, "Cleo Example")
        self.assertContains(response, "Ours")
        response = self.client.get(self.example.get_absolute_url())
        self.assertContains(response, "cleo@example.org")
        self.assertContains(response, "Change organization")
        self.assertContains(response, "Merge…")
        self.assertNotContains(response, "/delete/")  # Cleo belongs to it
        # The own one: only admins move people or merge
        response = self.client.get(self.own.get_absolute_url())
        self.assertNotContains(response, "Merge…")
        self.client.force_login(self.root)
        response = self.client.get(self.own.get_absolute_url())
        self.assertContains(response, "Merge…")
        self.assertNotContains(response, "/delete/")  # it always exists

    def test_create_as_modal_and_page(self):
        assert_modal(
            self,
            self.client.get("/organizations/new/", headers=MODAL),
            title="New organization",
        )
        assert_page(
            self, self.client.get("/organizations/new/"), title="New organization"
        )
        response = self.client.post(
            "/organizations/new/",
            {"name": "example  ltd", "domains": ""},
            headers=MODAL,
        )
        self.assertContains(response, "There is an organization called")
        response = self.client.post(
            "/organizations/new/",
            {"name": "Other Ltd", "domains": "other.org gmail.com"},
            headers=MODAL,
        )
        self.assertContains(response, "free-mail domain")
        response = self.client.post(
            "/organizations/new/",
            {"name": " Other   Ltd", "domains": "Other.org, other.net"},
            headers=MODAL,
        )
        other = Organization.objects.get(name="Other Ltd")
        assert_modal_redirect(self, response, other.get_absolute_url())
        self.assertEqual(other.domains, ["other.org", "other.net"])

    def test_edit(self):
        response = self.client.get(f"/organizations/{self.example.pk}/edit/")
        self.assertContains(response, 'value="example.com"')
        self.client.post(
            f"/organizations/{self.example.pk}/edit/",
            {"name": "Example Limited", "domains": "example.com example.org"},
        )
        self.example.refresh_from_db()
        self.assertEqual(self.example.name, "Example Limited")
        self.assertEqual(self.example.domains, ["example.com", "example.org"])
        # Shown everywhere with the current name
        self.cleo.refresh_from_db()
        self.assertEqual(self.cleo.display_name, "Cleo Example, Example Limited")

    def test_merge(self):
        typo = organization("Exmaple Ltd")
        dora = person("Dora", client=True, organization=typo)
        response = self.client.get(f"/organizations/{typo.pk}/merge/")
        self.assertContains(response, "Example Ltd")
        self.assertNotContains(response, "Example Team")  # admins only
        response = self.client.post(
            f"/organizations/{typo.pk}/merge/", {"into": self.own.pk}
        )
        self.assertEqual(response.status_code, 200)  # not offered
        response = self.client.post(
            f"/organizations/{typo.pk}/merge/", {"into": self.example.pk}
        )
        self.assertRedirects(response, self.example.get_absolute_url())
        dora.refresh_from_db()
        self.assertEqual(dora.organization, self.example)
        self.assertFalse(Organization.objects.filter(pk=typo.pk).exists())
        self.assertEqual(
            self.client.get(f"/organizations/{self.own.pk}/merge/").status_code, 403
        )

    def test_delete(self):
        empty = organization("Empty Ltd")
        response = self.client.get(f"/organizations/{empty.pk}/delete/", headers=MODAL)
        assert_modal(self, response, title="Delete Empty Ltd?")
        response = self.client.post(f"/organizations/{empty.pk}/delete/")
        self.assertRedirects(response, "/organizations/")
        self.assertFalse(Organization.objects.filter(pk=empty.pk).exists())
        # Not with people
        response = self.client.post(f"/organizations/{self.example.pk}/delete/")
        self.assertRedirects(response, self.example.get_absolute_url())
        self.assertTrue(Organization.objects.filter(pk=self.example.pk).exists())

    def test_person_organization(self):
        url = f"/people/{self.cleo.pk}/organization/"
        response = self.client.get(url)
        self.assertContains(response, 'value="Example Ltd"')
        response = self.client.post(url, {"organization": "Newco"})
        self.assertContains(response, "Create “Newco”?")
        response = self.client.post(
            url, {"organization": "Newco", "create_organization": "on"}
        )
        self.cleo.refresh_from_db()
        self.assertEqual(self.cleo.organization.name, "Newco")
        self.assertRedirects(response, self.cleo.organization.get_absolute_url())
        # Into the installation's own: admins only
        bob = person("Bob", organization=None)
        response = self.client.post(
            f"/people/{bob.pk}/organization/", {"organization": "Example Team"}
        )
        self.assertContains(response, "Only admins move people")
        bob.refresh_from_db()
        self.assertIsNone(bob.organization)
        self.client.force_login(self.root)
        self.client.post(
            f"/people/{bob.pk}/organization/", {"organization": "Example Team"}
        )
        bob.refresh_from_db()
        self.assertEqual(bob.organization, self.own)
        # Out of it too
        self.client.force_login(self.ada)
        response = self.client.post(
            f"/people/{bob.pk}/organization/", {"organization": ""}
        )
        self.assertContains(response, "Only admins move people")

    def test_palette(self):
        page = self.client.get(self.example.get_absolute_url()).content.decode()
        data = json.loads(
            page.split('<script id="wb-palette-data" type="application/json">')[
                1
            ].split("</script>")[0]
        )
        labels = {(a["label"], a["group"]) for a in data["actions"]}
        self.assertIn(("Go to organizations", "everywhere"), labels)
        self.assertIn(("New organization", "page"), labels)
        self.assertIn(("Edit", "page"), labels)
        self.assertIn(("Merge…", "page"), labels)


class NewProjectTest(TestCase):
    """Starting a project from organizations (specs/organizations.md)"""

    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.own = organization("Example Team", is_own=True)
        self.example = organization("Example Ltd", domains=["example.com"])
        self.other = organization("Other AG", domains=["other.ch"])
        self.cleo = person("Cleo", client=True, organization=self.example)
        self.dora = person("Dora", client=True, organization=self.example)
        self.eve = person("Eve", client=True, organization=self.other)
        self.pia = partner("Pia")
        self.client.force_login(self.ada)
        self.project_data = {"name": "Camp", "is_all_access": "on", "color": ""}

    def people_step(self, *organizations, **headers):
        return self.client.post(
            "/projects/new/",
            {
                **self.project_data,
                "step": "organizations",
                "organizations": [org.pk for org in organizations],
            },
            headers=headers,
        )

    def rows(self, *rows):
        data = {
            "invite-TOTAL_FORMS": "3",
            "invite-INITIAL_FORMS": "0",
            "invite-MIN_NUM_FORMS": "0",
            "invite-MAX_NUM_FORMS": "1000",
        }
        for index, row in enumerate(rows):
            data.update({f"invite-{index}-{key}": value for key, value in row.items()})
        return data

    def test_without_organizations_at_once(self):
        response = self.client.get("/projects/new/")
        self.assertContains(response, "Organizations involved")
        self.assertContains(response, "Example Ltd")
        self.assertNotContains(response, "Example Team")  # staff come later
        response = self.client.post("/projects/new/", self.project_data)
        project = Project.objects.get(name="Camp")
        self.assertRedirects(response, project.get_absolute_url())
        self.assertEqual(
            set(project.memberships.values_list("user", flat=True)), {self.ada.pk}
        )

    def test_their_people_all_or_some_plus_staff(self):
        response = self.people_step(self.example, **MODAL)
        assert_modal(self, response, title="New project")
        self.assertContains(response, "People of Example Ltd")
        self.assertContains(response, "Cleo Example, Example Ltd")
        self.assertNotContains(response, "Eve Example")  # Other AG's
        # All checked at first
        self.assertContains(response, 'id="id_people_0" checked')
        self.assertContains(response, 'id="id_people_1" checked')
        self.assertContains(response, "Bob Example")  # staff
        self.assertNotContains(response, "Pia Example")  # a partner, not involved
        self.assertContains(response, "Add project")
        self.assertFalse(Project.objects.exists())
        response = self.client.post(
            "/projects/new/",
            {
                **self.project_data,
                "step": "people",
                "organizations": [self.example.pk],
                "people": [self.cleo.pk],
                "staff": [self.bob.pk],
                **self.rows(),
            },
        )
        project = Project.objects.get(name="Camp")
        self.assertRedirects(response, project.get_absolute_url())
        self.assertEqual(
            set(project.memberships.values_list("user", flat=True)),
            {self.ada.pk, self.cleo.pk, self.bob.pk},
        )

    def test_partners_by_their_organization(self):
        response = self.people_step(self.pia.organization)
        self.assertContains(response, "Pia Example, Example Partner Agency")

    def test_inviting_people_without_an_account(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                "/projects/new/",
                {
                    **self.project_data,
                    "step": "people",
                    "organizations": [self.example.pk, self.other.pk],
                    "people": [],
                    **self.rows(
                        {"email": "finn@other.ch", "full_name": "Finn Example"},
                        {"email": "gus@gmail.com", "organization": self.example.pk},
                        {"email": "hal@nowhere.org"},
                    ),
                },
            )
        project = Project.objects.get(name="Camp")
        self.assertRedirects(response, project.get_absolute_url())
        finn = User.objects.get(email="finn@other.ch")
        self.assertEqual(finn.organization, self.other)  # by the domain
        self.assertTrue(finn.is_client)
        self.assertEqual(
            User.objects.get(email="gus@gmail.com").organization, self.example
        )
        # Two involved, no domain matching: none
        self.assertIsNone(User.objects.get(email="hal@nowhere.org").organization)
        self.assertEqual(project.memberships.count(), 4)
        self.assertEqual(len(mail.outbox), 3)

    def test_one_organization_involved_is_theirs(self):
        self.client.post(
            "/projects/new/",
            {
                **self.project_data,
                "step": "people",
                "organizations": [self.example.pk],
                **self.rows({"email": "hal@nowhere.org"}),
            },
        )
        self.assertEqual(
            User.objects.get(email="hal@nowhere.org").organization, self.example
        )

    def test_errors_keep_everything(self):
        deactivated = person("Ivy", client=True, is_active=False)
        response = self.client.post(
            "/projects/new/",
            {
                **self.project_data,
                "step": "people",
                "organizations": [self.example.pk],
                **self.rows({"email": "nope"}, {"email": deactivated.email}),
            },
        )
        self.assertContains(response, "Enter a valid email address")
        self.assertFalse(Project.objects.exists())
        response = self.client.post(
            "/projects/new/",
            {
                **self.project_data,
                "step": "people",
                "organizations": [self.example.pk],
                **self.rows({"email": deactivated.email}),
            },
        )
        self.assertContains(response, "deactivated")
        self.assertFalse(Project.objects.exists())
