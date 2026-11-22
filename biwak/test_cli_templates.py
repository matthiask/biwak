"""The CLI's templates (specs/templates.md)"""

import json

from biwak import test_cli
from biwak.items import operations as ops
from biwak.items.models import Item
from biwak.projects import operations as project_ops
from biwak.projects.models import Project


class TemplatesCLITest(test_cli.CLITest):
    def setUp(self):
        super().setUp()
        self.template = project_ops.create_template(name="Web project", actor=self.ada)
        todolist = ops.create_list(
            project=self.template, title="Onboarding", creator=self.ada
        )
        ops.create_todo(todolist=todolist, title="Kick-off", creator=self.ada)

    def test_list(self):
        data = json.loads(self.biwak("projects", "--templates", "--json").stdout)
        self.assertEqual([p["name"] for p in data], ["Web project"])
        self.assertNotIn("Web project", self.biwak("projects").output)

    def test_add_from_template(self):
        output = self.biwak(
            "project", "add", "Shop", "--template", str(self.template.pk)
        ).output
        self.assertIn("Created the project", output)
        shop = Project.objects.get(name="Shop")
        self.assertTrue(Item.objects.filter(project=shop, title="Kick-off").exists())

    def test_add_template(self):
        output = self.biwak("project", "add", "Event", "--as-template").output
        self.assertIn("Created the template", output)
        self.assertTrue(Project.objects.get(name="Event").is_template)
