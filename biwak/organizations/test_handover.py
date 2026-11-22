"""The question before deactivating says what's left to hand over, only in
projects the person asking can open (specs/handover.md)"""

from django.test import TestCase
from django.utils import timezone

from biwak.items import operations as ops
from biwak.organizations import activation
from biwak.test_utils import assert_modal, person, project


class WhatIsLeftTest(TestCase):
    def setUp(self):
        self.root = person("Root", is_admin=True)
        self.ada = person("Ada")
        self.gil = person("Gil")
        self.cleo = person("Cleo", client=True)
        # Gil alone with a client: the only staff member
        self.website = project("Website", members=[self.gil, self.cleo])
        # Ada there too
        self.shop = project("Shop", members=[self.gil, self.ada])
        # Limited, Ada and Root not members: they know nothing about it
        self.secret = project("Secret", members=[self.gil], all_access=False)
        self.old = project("Old", members=[self.gil])
        self.old.archived_at = timezone.now()
        self.old.save()
        for p in [self.website, self.shop, self.secret]:
            todolist = ops.create_list(project=p, title="Launch", creator=self.gil)
            ops.create_todo(
                todolist=todolist,
                title=f"Open in {p.name}",
                creator=self.gil,
                assignees=[self.gil],
            )
        done = ops.create_todo(
            todolist=todolist, title="Done", creator=self.gil, assignees=[self.gil]
        )
        ops.complete(done, actor=self.gil)

    def test_what_is_left(self):
        left = activation.what_is_left(self.gil, viewer=self.root)
        self.assertEqual(left.open_todos, 2)
        self.assertEqual(left.only_staff_in, [self.website])
        # A member of the limited project sees it too
        left = activation.what_is_left(self.gil, viewer=self.gil)
        self.assertEqual(left.open_todos, 3)
        self.assertEqual(left.only_staff_in, [self.secret, self.website])

    def test_clients_are_not_staff(self):
        left = activation.what_is_left(self.cleo, viewer=self.root)
        self.assertEqual((left.open_todos, left.only_staff_in), (0, []))

    def test_the_question(self):
        self.client.force_login(self.root)
        url = f"/people/{self.gil.pk}/deactivate/"
        response = self.client.get(url, headers={"HX-Modal": "true"})
        assert_modal(self, response, title=f"Deactivate {self.gil.display_name}?")
        self.assertContains(response, "Gil Example has 2 open to-dos.")
        self.assertContains(response, f'href="/todos/?assignee={self.gil.pk}"')
        self.assertContains(response, "Gil Example is the only active staff member of:")
        self.assertContains(response, self.website.get_absolute_url())
        # Nothing about the limited project: not its name, not a count
        self.assertNotContains(response, "Secret")
        self.assertNotContains(response, self.secret.get_absolute_url())
        self.assertNotContains(response, "Old")
        # It never blocks
        self.client.post(url)
        self.gil.refresh_from_db()
        self.assertFalse(self.gil.is_active)

    def test_nothing_left_says_nothing(self):
        dan = person("Dan")
        self.client.force_login(self.root)
        response = self.client.get(f"/people/{dan.pk}/deactivate/")
        self.assertNotContains(response, "open to-do")
        self.assertNotContains(response, "only active staff member")

    def test_staff_deactivating_a_client(self):
        ops.assign(
            ops.create_todo(
                todolist=ops.create_list(
                    project=self.website, title="Shared", creator=self.ada, visible=True
                ),
                title="Review",
                creator=self.ada,
            ),
            [self.cleo],
            actor=self.ada,
        )
        self.client.force_login(self.ada)
        response = self.client.get(f"/people/{self.cleo.pk}/deactivate/")
        self.assertContains(response, "Cleo Example has 1 open to-do.")
        self.assertNotContains(response, "only active staff member")
