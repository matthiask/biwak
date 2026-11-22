"""The ``biwak projects`` command of projects-overview.md"""

import json

from biwak import test_cli
from biwak.bookmarks import operations as bookmarks
from biwak.items import operations as ops
from biwak.items.models import Group
from biwak.projects.models import Membership, Project
from biwak.test_utils import person, project


class ProjectsCLITest(test_cli.CLITest):
    def setUp(self):
        super().setUp()
        self.zebra = project("Zebra", members=[self.ada])
        Membership.objects.get_or_create(project=self.zebra, user=self.ada)

    def names(self, *args):
        return [
            p["name"]
            for p in json.loads(self.biwak("projects", "--json", *args).stdout)
        ]

    def test_favorites_marked_and_first(self):
        self.assertEqual(self.names("--order", "name"), ["Website", "Zebra"])
        bookmarks.add_bookmark(self.ada, project=self.zebra)
        self.assertEqual(self.names("--order", "name"), ["Zebra", "Website"])
        output = self.biwak("projects", "--order", "name").output
        lines = [line for line in output.splitlines() if "Zebra" in line]
        self.assertTrue(lines[0].lstrip().startswith("*"))
        website = [line for line in output.splitlines() if "Website" in line]
        self.assertFalse(website[0].lstrip().startswith("*"))

    def test_order_and_last_activity(self):
        data = json.loads(self.biwak("projects", "--json").stdout)
        self.assertTrue(all("last_activity_at" in p for p in data))
        self.assertTrue(all("is_bookmarked" in p for p in data))
        # The CLI test case's project has events, Zebra none: it comes last
        self.assertEqual(self.names("--order", "activity"), ["Website", "Zebra"])
        self.assertIn("20", self.biwak("projects").output)
        self.assertEqual(self.biwak("projects", "--order", "x").exit_code, 2)


class ProjectGapsCLITest(test_cli.CLITest):
    def setUp(self):
        super().setUp()
        self.root = person("Root", is_admin=True)
        self.limited = project("HR", members=[self.ada], all_access=False)

    def test_add(self):
        output = self.biwak("project", "add", "Fresh", "--limited").output
        self.assertIn("Fresh (limited)", output)
        created = Project.objects.get(name="Fresh")
        self.assertFalse(created.is_all_access)
        self.assertTrue(created.is_member(self.ada))
        data = json.loads(self.biwak("project", "add", "Open", "--json").stdout)
        self.assertTrue(data["is_all_access"])

    def test_join(self):
        team = project("Team")
        self.assertIn("Joined", self.biwak("project", "join", team.pk).output)
        self.assertTrue(team.is_member(self.ada))
        # Ada isn't an admin: she can't join anything she doesn't see
        result = self.biwak("project", "join", project("Secret", all_access=False).pk)
        self.assertEqual(result.exit_code, 1)
        self.assertIn("404", result.output)
        self.assertEqual(
            self.biwak("projects", "--joinable", "--json").stdout.strip(), "[]"
        )

    def test_remove_anybody_including_oneself(self):
        """Own staff remove anybody, themselves included (decided 2026-11-22)"""
        bob = person("Bob")
        Membership.objects.create(project=self.project, user=bob)
        output = self.biwak("member", "remove", self.project.pk, bob.pk).output
        self.assertIn("Removed Bob Example", output)
        self.assertFalse(self.project.is_member(bob))
        self.biwak("member", "remove", self.project.pk, self.ada.pk)
        self.assertFalse(self.project.is_member(self.ada))

    def test_admin_joins_limited(self):
        self.ada.is_admin = True
        self.ada.save()
        other = project("Finance", all_access=False)
        output = self.biwak("projects", "--joinable").output
        self.assertIn("Finance", output)
        self.assertNotIn("HR", output)
        self.biwak("project", "join", other.pk)
        self.assertTrue(other.is_member(self.ada))
        self.assertNotIn("Finance", self.biwak("projects", "--joinable").output)


class TodoMoveCLITest(test_cli.CLITest):
    def setUp(self):
        super().setUp()
        self.other = ops.create_list(
            project=self.project, title="Later", creator=self.ada
        )
        self.group = Group.objects.create(todolist=self.other.todolist, title="Soon")

    def todos(self):
        self.a = ops.create_todo(todolist=self.list, title="A", creator=self.ada)
        self.b = ops.create_todo(todolist=self.list, title="B", creator=self.ada)

    def test_move_one(self):
        self.todos()
        output = self.biwak("todo", "move", self.a.pk, "--list", self.other.pk).output
        self.assertIn(f"Moved #{self.a.pk} A.", output)
        self.a.refresh_from_db()
        self.assertEqual(self.a.parent_id, self.other.pk)
        self.assertIsNone(self.a.todo.group)
        data = json.loads(
            self.biwak(
                "todo",
                "move",
                self.a.pk,
                "--list",
                self.other.pk,
                "--group",
                self.group.pk,
                "--json",
            ).stdout
        )
        self.assertEqual(data["group"]["title"], "Soon")

    def test_move_several(self):
        self.todos()
        output = self.biwak(
            "todo",
            "move",
            "--todos",
            f"{self.b.pk},{self.a.pk}",
            "--list",
            self.other.pk,
            "--group",
            self.group.pk,
        ).output
        self.assertIn("Moved", output)
        for todo in [self.a, self.b]:
            todo.refresh_from_db()
            self.assertEqual(todo.parent_id, self.other.pk)
            self.assertEqual(todo.todo.group_id, self.group.pk)
        self.assertLess(self.b.position, self.a.position)

    def test_arguments_and_errors(self):
        self.todos()
        for args in [
            ["todo", "move", "--list", self.other.pk],
            ["todo", "move", self.a.pk, "--todos", "1", "--list", self.other.pk],
            ["todo", "move", "--todos", "x", "--list", self.other.pk],
            ["todo", "move", self.a.pk],
        ]:
            with self.subTest(args=args):
                self.assertNotEqual(self.biwak(*args).exit_code, 0)
        elsewhere = ops.create_list(
            project=project("Other", members=[self.ada]), title="X", creator=self.ada
        )
        result = self.biwak("todo", "move", self.a.pk, "--list", elsewhere.pk)
        self.assertEqual(result.exit_code, 1)
        self.assertIn("400", result.output)
