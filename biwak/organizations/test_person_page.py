"""The person's page (specs/people.md): visible to whoever may know the
person, with the projects both are in"""

from django.test import TestCase
from django.urls import reverse

from biwak.accounts import operations
from biwak.accounts.test_images import picture
from biwak.test_utils import organization, partner, person, project


class PersonPageTest(TestCase):
    def setUp(self):
        organization("Example Team", is_own=True)
        self.root = person("Root", is_admin=True)
        self.ada = person("Ada")
        self.ben = person("Ben")
        self.pia = partner("Pia", organization_name="Alpine Agency")
        self.paul = partner("Paul")
        self.cleo = person("Cleo", client=True, organization="Zebra Clients")
        self.dora = person("Dora", client=True, organization="Zebra Clients")
        self.camp = project("Camp", members=[self.ada, self.pia, self.cleo])
        self.lake = project("Lake", members=[self.ada, self.cleo, self.dora])
        self.secret = project("Secret", members=[self.ada], all_access=False)

    def get(self, viewer, who):
        self.client.force_login(viewer)
        return self.client.get(reverse("person", args=[who.pk]))

    def test_own_staff_see_anybody_with_the_projects_both_are_in(self):
        response = self.get(self.ada, self.cleo)
        self.assertContains(response, "Cleo Example")
        self.assertContains(response, "Zebra Clients")
        self.assertContains(response, "client</span>")
        self.assertContains(response, "cleo@example.org")
        self.assertContains(response, "Camp")
        self.assertContains(response, "Lake")
        self.assertNotContains(response, "Secret")
        self.assertContains(response, "wb-avatar wb-avatar-lg")
        self.assertContains(response, reverse("person_feed", args=[self.cleo.pk]))
        # Ben is in no project: no projects in common, still known
        response = self.get(self.ben, self.cleo)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No projects in common.")

    def test_a_partner_sees_the_members_of_their_projects_only(self):
        response = self.get(self.pia, self.cleo)
        self.assertContains(response, "Cleo Example")
        self.assertContains(response, "Camp")
        self.assertNotContains(response, "Lake")
        self.assertEqual(self.get(self.pia, self.ada).status_code, 200)
        self.assertEqual(self.get(self.pia, self.dora).status_code, 404)
        self.assertEqual(self.get(self.pia, self.ben).status_code, 404)
        self.assertEqual(self.get(self.paul, self.cleo).status_code, 404)

    def test_a_client_sees_the_members_of_their_projects_only(self):
        self.assertEqual(self.get(self.cleo, self.dora).status_code, 200)
        self.assertEqual(self.get(self.dora, self.pia).status_code, 404)
        self.assertEqual(self.get(self.cleo, self.ben).status_code, 404)
        self.assertEqual(self.get(self.dora, self.root).status_code, 404)

    def test_clients_see_addresses_of_their_own_organization_only(self):
        self.assertContains(self.get(self.cleo, self.dora), "dora@example.org")
        self.assertNotContains(self.get(self.cleo, self.ada), "ada@example.org")

    def test_everybody_sees_their_own(self):
        for user in [self.paul, self.ben, self.cleo]:
            self.assertEqual(self.get(user, user).status_code, 200)

    def test_no_feed_link_where_the_feed_is_a_404(self):
        # Own staff may know Ivy, but she's in no project: no feed
        ivy = person("Ivy", client=True)
        response = self.get(self.ben, ivy)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, reverse("person_feed", args=[ivy.pk]))

    def test_anonymous_is_sent_to_the_login(self):
        response = self.client.get(reverse("person", args=[self.ada.pk]))
        self.assertEqual(response.status_code, 302)

    def test_the_image_and_admins_removing_it(self):
        operations.set_image(self.cleo, picture(), actor=self.cleo)
        remove = reverse("person_image_remove", args=[self.cleo.pk])
        response = self.get(self.ada, self.cleo)
        self.assertContains(response, f"/accounts/people/{self.cleo.pk}/image/")
        self.assertNotContains(response, remove)  # not an admin
        self.assertContains(self.get(self.root, self.cleo), remove)
        # The question, then the removal, by an admin
        self.assertContains(self.client.get(remove), "Remove the profile image of")
        self.client.post(remove)
        self.cleo.refresh_from_db()
        self.assertEqual(self.cleo.image, "")

    def test_others_cannot_remove_it(self):
        operations.set_image(self.cleo, picture(), actor=self.cleo)
        remove = reverse("person_image_remove", args=[self.cleo.pk])
        for user in [self.ada, self.pia, self.dora]:
            self.client.force_login(user)
            self.assertEqual(self.client.post(remove).status_code, 404)
        self.cleo.refresh_from_db()
        self.assertNotEqual(self.cleo.image, "")
