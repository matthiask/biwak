"""Inviting people with organizations (specs/organizations.md): picking an
existing one, confirming a new one, the domain preselecting it"""

from django.test import TestCase

from biwak.accounts.models import APIToken, User
from biwak.organizations.models import Organization
from biwak.projects import operations as project_ops
from biwak.test_utils import organization, person, project


class InviteTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.root = person("Root", is_admin=True)
        self.project = project(members=[self.ada])
        self.url = f"/projects/{self.project.pk}/people/invite/"
        self.example = organization("Example Ltd", domains=["example.com"])
        self.own = organization("Example Team", is_own=True, domains=["example.net"])

    def post(self, **data):
        return self.client.post(self.url, {"notify": "default", **data})

    def test_the_field_completes_existing_names(self):
        self.client.force_login(self.ada)
        response = self.client.get(self.url)
        self.assertContains(response, 'list="id_organization-names"')
        self.assertContains(response, '<option value="Example Ltd">')

    def test_an_existing_one_ignoring_case_and_spaces(self):
        self.client.force_login(self.ada)
        response = self.post(email="dora@example.org", organization=" example  LTD")
        self.assertEqual(response.status_code, 302)
        dora = User.objects.get(email="dora@example.org")
        self.assertEqual(dora.organization, self.example)

    def test_a_new_one_after_confirming(self):
        self.client.force_login(self.ada)
        response = self.post(email="dora@example.org", organization="Exmaple Ltd")
        self.assertContains(response, "no organization called “Exmaple Ltd”")
        self.assertContains(response, "Create “Exmaple Ltd”?")
        self.assertFalse(User.objects.filter(email="dora@example.org").exists())
        self.assertFalse(Organization.objects.filter(name="Exmaple Ltd").exists())
        response = self.post(
            email="dora@example.org",
            organization="Exmaple Ltd",
            create_organization="on",
        )
        self.assertEqual(response.status_code, 302)
        dora = User.objects.get(email="dora@example.org")
        self.assertEqual(dora.organization.name, "Exmaple Ltd")

    def test_a_new_one_goes_with_a_failed_invitation(self):
        self.client.force_login(self.ada)
        self.post(
            email="dora@example.org",
            organization="Exmaple Ltd",
            create_organization="on",
            is_client="",  # staff: admins only (and the field isn't there)
        )
        deactivated = person("Eve", client=True, is_active=False)
        response = self.post(
            email=deactivated.email,
            organization="Another Ltd",
            create_organization="on",
        )
        self.assertContains(response, "deactivated")
        self.assertFalse(Organization.objects.filter(name="Another Ltd").exists())

    def test_the_domain_preselects(self):
        self.client.force_login(self.ada)
        self.post(email="dora@example.com")
        self.assertEqual(
            User.objects.get(email="dora@example.com").organization, self.example
        )
        # Free-mail domains never match, even if somebody added one
        Organization.objects.filter(pk=self.example.pk).update(domains=["gmail.com"])
        self.post(email="finn@gmail.com")
        self.assertIsNone(User.objects.get(email="finn@gmail.com").organization)
        # Given, it wins over the domain
        other = organization("Other Ltd")
        self.post(email="gus@example.net", organization="Other Ltd")
        self.assertEqual(User.objects.get(email="gus@example.net").organization, other)

    def test_the_own_organization_admins_only(self):
        self.client.force_login(self.ada)
        response = self.post(email="dora@example.org", organization="Example Team")
        self.assertContains(response, "Only admins add people")
        self.assertFalse(User.objects.filter(email="dora@example.org").exists())
        # Its domain doesn't preselect it for others than admins
        self.post(email="finn@example.net")
        self.assertIsNone(User.objects.get(email="finn@example.net").organization)
        self.client.force_login(self.root)
        self.post(email="gus@example.net", is_client="")
        gus = User.objects.get(email="gus@example.net")
        self.assertEqual(gus.organization, self.own)
        self.assertFalse(gus.is_partner)

    def test_existing_people_keep_theirs(self):
        cleo = person("Cleo", client=True)
        project_ops.invite(
            self.project, email=cleo.email, organization=self.example, actor=self.ada
        )
        cleo.refresh_from_db()
        self.assertEqual(cleo.organization.name, "Example Client Ltd")

    def test_api(self):
        _token, secret = APIToken.create_for(user=self.ada, title="T", access="write")
        headers = {"authorization": f"Bearer {secret}"}
        url = f"/api/v1/projects/{self.project.pk}/members/invite/"

        def invite(**data):
            return self.client.post(
                url, data, content_type="application/json", headers=headers
            )

        response = invite(email="dora@example.org", organization_id=self.example.pk)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["organization_id"], self.example.pk)
        self.assertEqual(response.json()["organization"], "Example Ltd")
        response = invite(email="finn@example.org", organization="example ltd")
        self.assertEqual(response.json()["organization_id"], self.example.pk)
        self.assertEqual(
            invite(email="gus@example.org", organization="Nope").status_code, 400
        )
        self.assertEqual(
            invite(email="gus@example.org", organization_id=0).status_code, 400
        )
        response = invite(email="gus@example.com")
        self.assertEqual(response.json()["organization_id"], self.example.pk)
        response = invite(email="hal@example.org", organization_id=self.own.pk)
        self.assertEqual(response.status_code, 400)
