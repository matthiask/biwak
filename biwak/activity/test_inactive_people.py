from django.test import TestCase

from biwak.activity import operations as activity_ops
from biwak.items import operations as ops
from biwak.projects import operations as project_ops
from biwak.test_utils import person, project


class InactivePeopleTest(TestCase):
    """The operations accept inactive people only inside ``importing()``
    (decided 2026-11-21)"""

    def setUp(self):
        self.ada = person("Ada", is_admin=True)
        self.eve = person("Eve", is_active=False)
        self.project = project("Camp", members=[self.ada], all_access=False)
        self.todo = ops.create_todo(
            todolist=ops.create_list(
                project=self.project, title="Plan", creator=self.ada
            ),
            title="Pack",
            creator=self.ada,
        )

    def test_outside_an_import_they_are_refused(self):
        with self.assertRaises(ValueError):
            project_ops.add_member(self.project, self.eve, actor=self.ada)
        with self.assertRaises(ValueError):
            activity_ops.subscribe(self.eve, self.todo)
        with self.assertRaises(ValueError):
            ops.assign(self.todo, [self.eve], actor=self.ada)
        self.assertFalse(self.project.memberships.filter(user=self.eve).exists())
        self.assertFalse(self.todo.todo.assignees.exists())

    def test_inside_an_import_they_are_accepted(self):
        with activity_ops.importing():
            project_ops.add_member(self.project, self.eve, actor=self.ada)
            activity_ops.subscribe(self.eve, self.todo)
            ops.assign(self.todo, [self.eve], actor=self.ada)
        self.assertTrue(self.project.memberships.filter(user=self.eve).exists())
        self.assertEqual(list(self.todo.todo.assignees.all()), [self.eve])
        self.assertTrue(activity_ops.is_subscribed(self.eve, self.todo))

    def test_the_allowance_ends_with_the_import(self):
        with activity_ops.importing():
            pass
        self.assertFalse(activity_ops.is_importing())
        with self.assertRaises(ValueError):
            project_ops.add_member(self.project, self.eve, actor=self.ada)
