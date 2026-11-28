"""Deactivated people stay assigned and show as inactive wherever assignees
show; the to-dos page lists their open to-dos (specs/handover.md)"""

from django.test import TestCase
from django.urls import reverse

from biwak.activity.models import Subscription
from biwak.checkins import operations as checkin_ops
from biwak.checkins.support import MONDAY_9
from biwak.items import operations as ops
from biwak.items.models import Item, Kind
from biwak.organizations import activation
from biwak.projects import operations as project_ops
from biwak.projects.models import Project
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
        # Not offered when adding a to-do (the list's filter lists them, as
        # the to-dos page does, specs/todos.md, "Filters on a list")
        response = self.client.get(self.todolist.get_absolute_url())
        picker = response.context["form"]["assignees"]
        self.assertNotIn(f'<option value="{self.gil.pk}"', str(picker))
        self.assertIn(
            f'<option value="{self.gil.pk}"', str(response.context["filter_form"])
        )

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

    def test_the_api_keeps_them_when_changing_assignees(self):
        # Like the edit form (``assignable_or_assigned()``): sending the
        # assignees back with somebody added doesn't need Gil taken out
        self.client.force_login(self.ada)
        response = self.client.patch(
            f"/api/v1/todos/{self.todo.pk}/",
            {"assignees": [self.gil.pk, self.ada.pk]},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(self.todo.todo.assignees.all()), {self.gil, self.ada})
        # Not added where they aren't assigned
        other = ops.create_todo(todolist=self.todolist, title="Other", creator=self.ada)
        response = self.client.patch(
            f"/api/v1/todos/{other.pk}/",
            {"assignees": [self.gil.pk]},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(other.todo.assignees.exists())

    def test_assigning_several_keeps_them_with_replace(self):
        # The handover skill repeats co-assignees with ``--replace``
        bob = person("Bob")
        self.website.memberships.create(user=bob)
        other = ops.create_todo(
            todolist=self.todolist,
            title="Other",
            creator=self.ada,
            assignees=[self.ada],
        )
        self.client.force_login(self.ada)
        response = self.client.post(
            "/api/v1/todos/assign/",
            {"ids": [self.todo.pk], "people": [bob.pk, self.gil.pk], "replace": True},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(self.todo.todo.assignees.all()), {self.gil, bob})
        # The page too
        response = self.client.post(
            f"{reverse('todos_assign')}?items={self.todo.pk}",
            {"people": [self.ada.pk, self.gil.pk], "replace": "on"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(set(self.todo.todo.assignees.all()), {self.gil, self.ada})
        # Not added to to-dos they aren't assigned to: all or nothing
        response = self.client.post(
            "/api/v1/todos/assign/",
            {"ids": [self.todo.pk, other.pk], "people": [self.gil.pk]},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(set(other.todo.assignees.all()), {self.ada})

    def test_copying_the_list(self):
        """The copy keeps them assigned, without subscribing them (decided
        2026-11-28)"""
        self.client.force_login(self.ada)
        pk = self.website.pk
        response = self.client.post(
            f"/lists/{self.todolist.pk}/copy/",
            {
                "project": pk,
                "title": "Launch",
                "dates": "keep",
                "visible": "on",
                "confirmed": f"{pk}:1",
            },
        )
        self.assertEqual(response.status_code, 302)
        copy = Item.objects.get(
            parent__project=self.website, title="Write the copy", pk__gt=self.todo.pk
        )
        self.assertEqual(list(copy.todo.assignees.all()), [self.gil])
        self.assertFalse(Subscription.objects.filter(item=copy, user=self.gil).exists())


class InactiveInTemplatesTest(TestCase):
    """A template's assignees and people asked who were deactivated stay on
    the new project's to-dos and questions, unsubscribed (decided 2026-11-28)"""

    def setUp(self):
        self.root = person("Root", is_admin=True)
        self.ada = person("Ada")
        self.gil = person("Gil")
        self.template = project_ops.create_template(name="Web", actor=self.ada)
        todolist = ops.create_list(
            project=self.template, title="Launch", creator=self.ada
        )
        ops.create_todo(
            todolist=todolist,
            title="Write the copy",
            creator=self.ada,
            assignees=[self.gil],
        )
        checkin_ops.create_question(
            project=self.template,
            title="What are you working on?",
            creator=self.ada,
            people=[self.gil, self.ada],
            **MONDAY_9,
        )
        activation.deactivate([self.gil], actor=self.root)

    def test_api(self):
        self.client.force_login(self.ada)
        response = self.client.post(
            "/api/v1/projects/",
            {"name": "Website", "template": self.template.pk},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        website = Project.objects.get(pk=response.json()["id"])
        todo = Item.objects.get(project=website, kind=Kind.TODO)
        self.assertEqual(list(todo.todo.assignees.all()), [self.gil])
        question = Item.objects.get(project=website, kind=Kind.QUESTION)
        self.assertEqual(set(question.question.people.all()), {self.ada, self.gil})
        self.assertFalse(
            Subscription.objects.filter(
                item__in=[todo, question], user=self.gil
            ).exists()
        )
        # Not asked: only active people are
        self.assertEqual(checkin_ops._recipients(question.question), [self.ada])
