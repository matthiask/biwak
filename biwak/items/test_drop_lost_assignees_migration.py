"""The data migration taking people removed from a project or deactivated
off its open to-dos (specs/todos.md)"""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from biwak.items import operations as ops
from biwak.items.models import Assignment
from biwak.projects.models import Membership
from biwak.test_utils import person, project


class DropLostAssigneesMigrationTest(TransactionTestCase):
    before = [("items", "0014_drafts")]

    def migrate(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.before)
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_drops_removed_and_deactivated_from_open_todos(self):
        ada = person("Ada")
        bob = person("Bob")  # removed from the project
        dan = person("Dan")  # deactivated
        eve = person("Eve")  # deactivated, then activated again
        imp = person("Imp", is_active=False)  # created so by the importer
        website = project(members=[ada, bob, dan, eve, imp])
        todolist = ops.create_list(project=website, title="Launch", creator=ada)
        people = [ada, bob, dan, eve, imp]
        todo = ops.create_todo(todolist=todolist, title="Copy", creator=ada)
        done = ops.create_todo(todolist=todolist, title="Done", creator=ada)
        for item in [todo, done]:
            for user in people:
                Assignment.objects.create(todo=item.todo, user=user)
        ops.complete(done, actor=ada)
        # The old way: removing and deactivating kept the assignments
        Membership.objects.filter(project=website, user=bob).delete()
        for user in [dan, eve]:
            user.is_active = False
            user.save()
        eve.is_active = True
        eve.save()

        self.migrate()
        self.assertEqual(set(todo.todo.assignees.all()), {ada, eve, imp})
        self.assertEqual(set(done.todo.assignees.all()), set(people))
