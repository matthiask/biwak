"""People removed from a project are dropped as assignees of its open
to-dos (decided 2026-11-21, specs/todos.md): through ``unassign()``, so the
events and the history show it, telling nobody. Deactivated people keep
theirs (decided 2026-11-22, specs/handover.md)."""

from django.core import mail
from django.test import TestCase

from biwak.activity.models import Action, Event
from biwak.items import operations as ops
from biwak.organizations import activation
from biwak.projects import operations as project_ops
from biwak.test_utils import person, project


class DroppedAssigneesTest(TestCase):
    def setUp(self):
        self.root = person("Root", is_admin=True)
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.website = project("Website", members=[self.ada, self.bob, self.cleo])
        self.shop = project("Shop", members=[self.ada, self.bob])
        self.todos = {}
        for p in [self.website, self.shop]:
            todolist = ops.create_list(
                project=p, title="Launch", creator=self.ada, visible=True
            )
            self.todos[p.name] = ops.create_todo(
                todolist=todolist,
                title=f"Copy for {p.name}",
                creator=self.ada,
                assignees=[self.ada, self.bob],
            )
        self.done = ops.create_todo(
            todolist=self.todos["Website"].parent,
            title="Done",
            creator=self.ada,
            assignees=[self.bob],
        )
        ops.complete(self.done, actor=self.ada)
        mail.outbox = []

    def assignees(self, item):
        return set(item.todo.assignees.all())

    def test_removing_from_a_project(self):
        with self.captureOnCommitCallbacks(execute=True):
            project_ops.remove_member(self.website, self.bob, actor=self.ada)
        self.assertEqual(self.assignees(self.todos["Website"]), {self.ada})
        # Other projects keep them
        self.assertEqual(self.assignees(self.todos["Shop"]), {self.ada, self.bob})
        # Completed to-dos are history: they stay
        self.assertEqual(self.assignees(self.done), {self.bob})
        # The history shows it, by whoever removed them; nobody is told
        event = Event.objects.get(action=Action.UNASSIGNED)
        self.assertEqual(event.item_id, self.todos["Website"].pk)
        self.assertEqual(event.actor, self.ada)
        self.assertEqual(event.data["assignees"], [self.bob.pk])
        self.assertEqual(mail.outbox, [])

    def test_leaving_a_project(self):
        project_ops.remove_member(self.website, self.bob, actor=self.bob)
        self.assertEqual(self.assignees(self.todos["Website"]), {self.ada})
        self.assertEqual(Event.objects.get(action=Action.UNASSIGNED).actor, self.bob)

    def test_deactivating_keeps_them(self):
        with self.captureOnCommitCallbacks(execute=True):
            activation.deactivate([self.bob], actor=self.root)
        self.assertEqual(self.assignees(self.todos["Website"]), {self.ada, self.bob})
        self.assertEqual(self.assignees(self.todos["Shop"]), {self.ada, self.bob})
        self.assertEqual(self.assignees(self.done), {self.bob})
        self.assertFalse(Event.objects.filter(action=Action.UNASSIGNED).exists())
        self.assertEqual(mail.outbox, [])

    def test_trashed_open_todos_too(self):
        """Restoring them brings no one back who can't be assigned"""
        todo = self.todos["Website"]
        ops.trash(todo, actor=self.ada)
        project_ops.remove_member(self.website, self.bob, actor=self.ada)
        self.assertEqual(self.assignees(todo), {self.ada})

    def test_withdrawing_an_invitation(self):
        with self.captureOnCommitCallbacks(execute=True):
            [invited] = project_ops.invite_people(
                [self.website],
                [{"email": "dora@example.net"}],
                actor=self.ada,
            )
        dora = invited.user
        ops.update_todo(
            self.todos["Website"], actor=self.ada, assignees=[self.ada, dora]
        )
        project_ops.withdraw_invitation(dora, actor=self.ada)
        dora.refresh_from_db()
        self.assertFalse(dora.is_active)
        self.assertEqual(self.assignees(self.todos["Website"]), {self.ada})


class EditFormTest(TestCase):
    """Saving the to-do's edit form never drops somebody the form can't
    offer (not assignable anymore, e.g. a client on a to-do made internal):
    the picker shows them, so they stay unless taken out"""

    def setUp(self):
        self.ada = person("Ada")
        self.cleo = person("Cleo", client=True)
        self.website = project("Website", members=[self.ada, self.cleo])
        todolist = ops.create_list(
            project=self.website, title="Launch", creator=self.ada, visible=True
        )
        self.todo = ops.create_todo(
            todolist=todolist,
            title="Copy",
            creator=self.ada,
            assignees=[self.ada, self.cleo],
        )
        ops.set_visibility(todolist, visible=False, actor=self.ada)
        self.todo.refresh_from_db()
        self.client.force_login(self.ada)

    def post(self, assignees):
        return self.client.post(
            self.todo.get_absolute_url(),
            {
                "form": "todo",
                "title": "Copy",
                "notes": "",
                "assignees": [u.pk for u in assignees],
            },
        )

    def test_kept_and_shown(self):
        self.assertNotIn(self.cleo, ops.assignable_people(self.todo, self.ada))
        response = self.client.get(f"{self.todo.get_absolute_url()}edit/")
        self.assertContains(response, f'value="{self.cleo.pk}" selected')
        response = self.post([self.ada, self.cleo])
        self.assertEqual(response.status_code, 302)
        self.assertEqual(set(self.todo.todo.assignees.all()), {self.ada, self.cleo})
        self.assertFalse(Event.objects.filter(action=Action.UNASSIGNED).exists())

    def test_taken_out(self):
        self.post([self.ada])
        self.assertEqual(set(self.todo.todo.assignees.all()), {self.ada})
