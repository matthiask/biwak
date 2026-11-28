"""Importing Basecamp's project templates and its to-do list library as
templates (specs/templates.md, specs/import-basecamp.md), from recorded
shapes with made-up data: a template is served like a project, a bucket
with a dock"""

import copy
import io
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase

from biwak.activity.models import Action, Event, Notification
from biwak.importer import support
from biwak.importer.importer import Importer
from biwak.items.models import Item, Kind
from biwak.projects.models import Project
from biwak.test_utils import person


TEMPLATE_ID, LIBRARY_ID = 2000, 3000


def with_templates(data, *, library=True):
    """The recorded project's dock as a template's (only templates are
    imported in these tests, so the tools' IDs don't clash), and the
    library holding the project's "Budget" list"""
    project = data[f"/projects/{support.PROJECT}.json"]
    template = copy.deepcopy(project) | {
        "id": TEMPLATE_ID,
        "name": "Web project",
        "description": "For websites",
        "url": f"{support.BASE}/templates/{TEMPLATE_ID}.json",
    }
    data["/templates.json"] = [template]
    if library:
        budget = next(
            rec for rec in data["/todosets/300/todolists.json"] if rec["id"] == 302
        )
        # Its own copy of the list (another ID), with its to-dos and groups
        budget = copy.deepcopy(budget) | {"id": 3302}
        for key in [key for key in data if key.startswith("/todolists/302/")]:
            data[key.replace("/302/", "/3302/")] = copy.deepcopy(data[key])
        data["/template_library/todolists.json"] = {
            "bucket": {"id": LIBRARY_ID, "name": "", "type": "Project"},
            "todolists": [budget],
        }
    return data


class TemplatesImportTest(TestCase):
    def setUp(self):
        self.ada = person("Ada", is_admin=True)
        data, files = support.make_data()
        self.client_ = support.FakeClient(with_templates(data), files)

    def run_import(self, **kwargs):
        return Importer(self.client_, actor=self.ada, **kwargs).run_templates()

    def test_templates(self):
        report = self.run_import()
        template = Project.objects.get(name="Web project")
        self.assertTrue(template.is_template)
        self.assertTrue(template.is_all_access)
        self.assertEqual(template.description, "For websites")
        # No members: the people come with the project
        self.assertFalse(template.memberships.exists())
        items = Item.objects.filter(project=template)
        self.assertTrue(items.filter(kind=Kind.LIST, title="Kitchen plan").exists())
        self.assertTrue(items.filter(kind=Kind.MESSAGE).exists())
        self.assertTrue(items.filter(kind=Kind.FOLDER).exists())
        # Visibility as in Basecamp
        self.assertTrue(
            items.get(kind=Kind.LIST, title="Kitchen plan").is_client_visible
        )
        self.assertIn("templates: 2 new", report.as_text())
        # Nothing told
        self.assertFalse(Notification.objects.exists())

    def test_library(self):
        """One "To-do list library", whatever the bucket's name (decided
        2026-11-22)"""
        bucket = self.client_.data["/template_library/todolists.json"]["bucket"]
        bucket["name"] = "Vorlagen"
        self.run_import()
        library = Project.objects.get(name="To-do list library")
        self.assertTrue(library.is_template)
        self.assertEqual(
            list(
                Item.objects.filter(project=library, kind=Kind.LIST).values_list(
                    "title", flat=True
                )
            ),
            ["Budget"],
        )

    def test_second_run_updates(self):
        self.run_import()
        template = self.client_.data["/templates.json"][0]
        template["name"] = "Website project"
        template["updated_at"] = "2026-04-01T09:00:00.000Z"
        self.run_import()
        self.assertEqual(Project.objects.filter(is_template=True).count(), 2)
        self.assertTrue(Project.objects.filter(name="Website project").exists())

    def test_renames_and_archiving_name_nobody(self):
        """At Basecamp's time, without a person (decided 2026-11-28)"""
        self.run_import()
        template = self.client_.data["/templates.json"][0]
        template |= {
            "name": "Website project",
            "status": "archived",
            "updated_at": "2026-04-01T09:00:00.000Z",
        }
        self.run_import()
        events = Event.objects.filter(
            action__in=[Action.EDITED_PROJECT, Action.ARCHIVED],
            project__name="Website project",
            item=None,
        )
        self.assertEqual(
            sorted(
                (
                    (
                        e.action,
                        e.actor,
                        e.created_at.isoformat(),
                        e.data.get("imported"),
                    )
                    for e in events
                ),
                key=lambda event: event[0],
            ),
            [
                (action, None, "2026-04-01T09:00:00+00:00", "basecamp")
                for action in sorted([Action.ARCHIVED, Action.EDITED_PROJECT])
            ],
        )

    def test_dry_run(self):
        report = self.run_import(dry_run=True)
        self.assertFalse(Project.objects.exists())
        self.assertIn("templates: 2 new", report.as_text())

    def test_without_library(self):
        del self.client_.data["/template_library/todolists.json"]
        self.run_import()
        self.assertEqual(
            list(Project.objects.values_list("name", flat=True)), ["Web project"]
        )

    def test_dock_fetched_when_missing(self):
        template = self.client_.data["/templates.json"][0]
        self.client_.data[f"/templates/{TEMPLATE_ID}.json"] = copy.deepcopy(template)
        del template["dock"]
        self.run_import()
        self.assertTrue(
            Item.objects.filter(
                project__name="Web project", title="Kitchen plan"
            ).exists()
        )

    def test_command(self):
        out = io.StringIO()
        with (
            mock.patch.dict("os.environ", {"BASECAMP_TOKEN": "secret"}),
            mock.patch(
                "biwak.importer.management.commands.import_basecamp.make_client",
                return_value=self.client_,
            ),
        ):
            call_command(
                "import_basecamp",
                "--account",
                "1000",
                "--templates",
                stdout=out,
                stderr=io.StringIO(),
            )
            with self.assertRaises(CommandError):
                call_command("import_basecamp", "--account", "1000")
        self.assertIn("templates: 2 new", out.getvalue())
        self.assertFalse(Project.objects.filter(is_template=False).exists())
