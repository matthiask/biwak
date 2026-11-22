"""The person's page (specs/people.md): visible to whoever may know the
person, with the projects both are in"""

import datetime as dt

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from biwak.accounts import operations
from biwak.accounts.test_images import picture
from biwak.activity.models import Action, Event
from biwak.activity.operations import record
from biwak.activity.test_feed import page_text
from biwak.items import operations as ops
from biwak.palette.test_actions import palette_data
from biwak.test_utils import external, organization, person, project


class PersonPageTest(TestCase):
    def setUp(self):
        organization("Example Team", is_own=True)
        self.root = person("Root", is_admin=True)
        self.ada = person("Ada")
        self.ben = person("Ben")
        self.pia = external("Pia", organization_name="Alpine Agency")
        self.paul = external("Paul")
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
        # Ben is in no project: no projects in common, still known
        response = self.get(self.ben, self.cleo)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No projects in common.")

    def test_an_external_sees_the_people_of_their_projects_only(self):
        response = self.get(self.pia, self.cleo)
        self.assertContains(response, "Cleo Example")
        self.assertContains(response, "Camp")
        self.assertNotContains(response, "Lake")
        self.assertEqual(self.get(self.pia, self.ada).status_code, 200)
        self.assertEqual(self.get(self.pia, self.dora).status_code, 404)
        # Ben opens the all-access Camp: one of its people (decided
        # 2026-11-21), with no projects in common as members
        response = self.get(self.pia, self.ben)
        self.assertContains(response, "No projects in common.")
        self.assertEqual(self.get(self.paul, self.cleo).status_code, 404)
        self.assertEqual(self.get(self.paul, self.ben).status_code, 404)
        # Only all-access projects bring the own staff
        self.camp.is_all_access = False
        self.camp.save()
        self.assertEqual(self.get(self.pia, self.ben).status_code, 404)

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


class PersonActivityTest(TestCase):
    """The person's last entries on their page (decided 2026-11-22): as the
    activity shows them, only what the viewer sees, with "All activity"
    """

    def setUp(self):
        self.ada = person("Ada")
        self.ben = person("Ben")
        self.pia = external("Pia")
        self.cleo = person("Cleo", client=True)
        self.camp = project("Camp", members=[self.ada, self.ben, self.pia, self.cleo])
        self.internal = ops.create_list(
            project=self.camp, title="Internal plans", creator=self.ada
        )
        self.shared = ops.create_list(
            project=self.camp, title="Shared plans", creator=self.ada, visible=True
        )
        Event.objects.all().delete()

    def get(self, viewer, who):
        self.client.force_login(viewer)
        return self.client.get(reverse("person", args=[who.pk]))

    def all_activity(self, who):
        return f'href="/feed/?person={who.pk}"'

    def test_the_last_five_entries_merged_as_the_activity(self):
        for n in range(3):
            ops.create_todo(todolist=self.shared, title=f"Tent {n}", creator=self.ada)
        # Completions in six lists, later: entries of their own
        for title in ["Rope", "Map", "Stove", "Lamp", "Boots", "Snacks"]:
            todolist = ops.create_list(
                project=self.camp, title=f"{title} list", creator=self.ben, visible=True
            )
            todo = ops.create_todo(todolist=todolist, title=title, creator=self.ben)
            record(
                actor=self.ada, action=Action.COMPLETED, project=self.camp, item=todo
            )
        completed = Event.objects.filter(actor=self.ada, action=Action.COMPLETED)
        completed.update(created_at=timezone.now() + dt.timedelta(minutes=1))
        response = self.get(self.ben, self.ada)
        text = page_text(response)
        self.assertIn("Recent activity", text)
        self.assertEqual(text.count("Ada completed"), 5)
        self.assertNotIn("Tent", text)
        self.assertContains(response, self.all_activity(self.ada))
        # Two completions left: the to-dos created are one entry, as in the
        # activity
        completed.filter(
            pk__in=list(completed.values_list("pk", flat=True)[:4])
        ).delete()
        text = page_text(self.get(self.ben, self.ada))
        self.assertEqual(text.count("Ada completed"), 2)
        self.assertIn("created 3 to-dos in Shared plans", text)
        # Nothing of Pia's yet: no section
        response = self.get(self.ada, self.pia)
        self.assertNotContains(response, "Recent activity")
        self.assertNotContains(response, self.all_activity(self.pia))

    def test_only_what_the_viewer_sees(self):
        ops.create_todo(todolist=self.internal, title="Secret tent", creator=self.ada)
        # Staff and the external see the internal to-do
        for viewer in [self.ben, self.pia]:
            with self.subTest(viewer=viewer):
                response = self.get(viewer, self.ada)
                self.assertContains(response, "Secret tent")
                self.assertContains(response, self.all_activity(self.ada))
        # The client sees nothing of Ada's: no section, no link
        response = self.get(self.cleo, self.ada)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Secret tent")
        self.assertNotContains(response, "Recent activity")
        self.assertNotContains(response, self.all_activity(self.ada))
        ops.create_todo(todolist=self.shared, title="Open tent", creator=self.ada)
        response = self.get(self.cleo, self.ada)
        self.assertContains(response, "Open tent")
        self.assertNotContains(response, "Secret tent")
        self.assertContains(response, self.all_activity(self.ada))
        # The link is the palette's too
        labels = {a["label"]: a for a in palette_data(response)["actions"]}
        self.assertEqual(labels["All activity"]["url"], f"/feed/?person={self.ada.pk}")
        self.assertNotIn("All activity", self.labels(self.cleo, self.ben))

    def labels(self, viewer, who):
        return {a["label"] for a in palette_data(self.get(viewer, who))["actions"]}

    def test_nobody_the_person_filter_does_not_take(self):
        # Own staff may know Ivy, but she's in no project: neither the
        # activity's filter nor her page shows her activity
        ivy = person("Ivy", client=True)
        response = self.get(self.ben, ivy)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Recent activity")
        self.assertNotContains(response, self.all_activity(ivy))

    def test_the_person_feed_page_is_gone(self):
        self.client.force_login(self.ada)
        self.assertEqual(
            self.client.get(f"/people/{self.ada.pk}/feed/").status_code, 404
        )
