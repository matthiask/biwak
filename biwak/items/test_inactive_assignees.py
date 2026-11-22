"""Deactivated people stay assigned and show as inactive wherever assignees
show; the to-dos page lists their open to-dos (specs/handover.md)"""

from django.test import TestCase

from biwak.items import operations as ops
from biwak.organizations import activation
from biwak.test_utils import person, project


class InactiveAssigneesTest(TestCase):
    def setUp(self):
        self.root = person("Root", is_admin=True)
        self.ada = person("Ada")
        self.gil = person("Gil")
        self.cleo = person("Cleo", client=True)
        self.website = project("Website", members=[self.ada, self.gil, self.cleo])
        self.todolist = ops.create_list(
            project=self.website, title="Launch", creator=self.ada, visible=True
        )
        self.todo = ops.create_todo(
            todolist=self.todolist,
            title="Write the copy",
            creator=self.ada,
            assignees=[self.gil],
        )
        activation.deactivate([self.gil], actor=self.root)
        self.gil.refresh_from_db()

    def test_rows_and_page(self):
        self.client.force_login(self.ada)
        for url in [
            self.todolist.get_absolute_url(),
            f"{self.todolist.get_absolute_url()}?view=board",
            self.todo.get_absolute_url(),
            "/todos/?assignee=anybody",
        ]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertContains(response, "wb-avatar-inactive")
                self.assertContains(
                    response, 'Gil <span class="text-body-secondary">(inactive)</span>'
                )

    def test_clients_see_it_too(self):
        self.client.force_login(self.cleo)
        response = self.client.get(self.todo.get_absolute_url())
        self.assertContains(response, "(inactive)")

    def test_the_timeline(self):
        other = ops.create_todo(todolist=self.todolist, title="Other", creator=self.ada)
        ops.assign(other, [self.ada], actor=self.ada)
        # An assignment from before somebody left
        bob = person("Bob")
        ops.assign(other, [bob], actor=self.ada)
        activation.deactivate([bob], actor=self.root)
        self.client.force_login(self.ada)
        response = self.client.get(other.get_absolute_url())
        self.assertContains(response, "Bob (inactive)")

    def test_not_offered_but_kept_in_the_picker(self):
        self.assertNotIn(self.gil, ops.assignable_people(self.todo, self.ada))
        self.client.force_login(self.ada)
        response = self.client.get(f"{self.todo.get_absolute_url()}edit/")
        self.assertContains(response, f'value="{self.gil.pk}" selected')
        self.assertContains(response, "Gil (inactive)")
        self.assertContains(response, "&quot;inactive&quot;: true")
        # Not offered when adding a to-do
        response = self.client.get(self.todolist.get_absolute_url())
        self.assertNotContains(response, f'<option value="{self.gil.pk}"')

    def test_the_todos_page_lists_them(self):
        self.client.force_login(self.ada)
        response = self.client.get("/todos/")
        self.assertContains(response, '<optgroup label="Inactive">')
        self.assertContains(response, f'<option value="{self.gil.pk}">Gil</option>')
        response = self.client.get(f"/todos/?assignee={self.gil.pk}")
        self.assertContains(response, "Write the copy")
        # Still nobody active's
        response = self.client.get("/todos/?assignee=nobody")
        self.assertContains(response, "Write the copy")

    def test_api(self):
        self.client.force_login(self.ada)
        data = self.client.get(f"/api/v1/todos/{self.todo.pk}/").json()
        [gil] = data["assignees"]
        self.assertEqual((gil["id"], gil["is_active"]), (self.gil.pk, False))
        data = self.client.get(f"/api/v1/todos/?assignee={self.gil.pk}").json()
        self.assertEqual([t["id"] for t in data["results"]], [self.todo.pk])
