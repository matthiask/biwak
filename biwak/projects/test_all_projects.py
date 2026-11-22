"""All projects, for admins (specs/handover.md): every project with counts
and filters, nothing about the contents of projects the admin can't open;
the page, the API and the CLI"""

import json

from django.test import TestCase
from django.utils import timezone

from biwak import test_cli
from biwak.items import operations as ops
from biwak.organizations import activation
from biwak.palette.test_actions import palette_data
from biwak.projects.all_projects import all_projects
from biwak.test_utils import organization, partner, person, project


class Data:
    def make(self):
        self.root = person("Root", is_admin=True)
        # The CLI's tests have her already
        self.ada = getattr(self, "ada", None) or person("Ada")
        self.gil = person("Gil")
        acme = organization("Acme Clients")
        self.cleo = person("Cleo", client=True, organization=acme)
        # Gil's limited project, Root not a member; Gil leaves
        self.secret = project("Secret", members=[self.gil, self.cleo], all_access=False)
        self.website = project("Site", members=[self.ada, self.root])
        self.old = project("Old", members=[self.ada])
        self.old.archived_at = timezone.now()
        self.old.save()
        todolist = ops.create_list(
            project=self.secret, title="Hidden", creator=self.gil
        )
        for title in ["Left one", "Left two"]:
            ops.create_todo(
                todolist=todolist, title=title, creator=self.gil, assignees=[self.gil]
            )
        ops.create_todo(todolist=todolist, title="Nobody's", creator=self.gil)
        done = ops.create_todo(
            todolist=todolist, title="Done", creator=self.gil, assignees=[self.gil]
        )
        ops.complete(done, actor=self.gil)
        site = ops.create_list(project=self.website, title="Launch", creator=self.ada)
        ops.create_todo(
            todolist=site,
            title="Ada's",
            creator=self.ada,
            assignees=[self.ada, self.gil],
        )
        activation.deactivate([self.gil], actor=self.root)


class AllProjectsTest(Data, TestCase):
    def setUp(self):
        self.make()

    def by_name(self, **filters):
        return {p.name: p for p in all_projects(self.root, **filters)}

    def test_counts(self):
        projects = self.by_name()
        self.assertEqual(list(projects), ["Secret", "Site"])
        secret = projects["Secret"]
        self.assertEqual(
            (
                secret.active_staff,
                secret.client_organizations,
                secret.open_todos,
                secret.inactive_todos,
                secret.can_open,
                secret.joinable,
            ),
            (0, ["Acme Clients"], 3, 2, False, True),
        )
        website = projects["Site"]
        self.assertEqual(
            (website.active_staff, website.open_todos, website.inactive_todos),
            (2, 1, 0),
        )
        self.assertTrue(website.can_open)
        self.assertFalse(website.joinable)

    def test_filters(self):
        self.assertEqual(list(self.by_name(no_staff=True)), ["Secret"])
        self.assertEqual(list(self.by_name(limited=True)), ["Secret"])
        self.assertEqual(list(self.by_name(inactive=True)), ["Secret"])
        self.assertEqual(list(self.by_name(archived=True)), ["Old", "Secret", "Site"])

    def test_queries(self):
        for n in range(5):
            project(f"More {n}", members=[self.ada])
        with self.assertNumQueries(4):
            all_projects(self.root)

    def test_page(self):
        self.client.force_login(self.root)
        response = self.client.get("/projects/all/")
        self.assertContains(response, "Secret")
        self.assertContains(response, "Acme Clients")
        self.assertContains(response, f"/projects/{self.secret.pk}/join/")
        self.assertContains(response, f'href="{self.website.get_absolute_url()}"')
        # Nothing of the secret project's contents
        for text in ["Left one", "Hidden", "Gil", "Cleo"]:
            self.assertNotContains(response, text)
        self.assertNotContains(response, f'href="{self.secret.get_absolute_url()}"')
        response = self.client.get("/projects/all/?no_staff=on")
        self.assertNotContains(response, f'data-project="{self.website.pk}"')
        # Joining, recorded as usual
        response = self.client.post(f"/projects/{self.secret.pk}/join/")
        self.assertRedirects(response, self.secret.get_absolute_url())

    def test_only_admins(self):
        self.client.force_login(self.ada)
        self.assertEqual(self.client.get("/projects/all/").status_code, 403)
        self.assertNotContains(self.client.get("/projects/"), "/projects/all/")
        self.client.force_login(self.cleo)
        self.assertEqual(self.client.get("/projects/all/").status_code, 404)
        self.client.force_login(partner("Pia"))
        self.assertEqual(self.client.get("/projects/all/").status_code, 404)

    def test_the_projects_page_links_it(self):
        self.client.force_login(self.root)
        response = self.client.get("/projects/")
        self.assertContains(response, 'href="/projects/all/"')
        # The plain list of limited projects is gone
        self.assertNotContains(response, "Limited projects you're not a member of")
        self.assertNotContains(response, f"/projects/{self.secret.pk}/join/")

    def test_palette(self):
        self.client.force_login(self.root)
        labels = [a["label"] for a in palette_data(self.client.get("/"))["actions"]]
        self.assertIn("All projects", labels)
        self.client.force_login(self.ada)
        labels = [a["label"] for a in palette_data(self.client.get("/"))["actions"]]
        self.assertNotIn("All projects", labels)

    def test_api(self):
        self.client.force_login(self.root)
        data = self.client.get("/api/v1/projects/all/").json()
        self.assertEqual([p["name"] for p in data], ["Secret", "Site"])
        secret = data[0]
        self.assertEqual(
            (secret["inactive_todos"], secret["joinable"], secret["url"]),
            (2, True, None),
        )
        data = self.client.get(
            "/api/v1/projects/all/?archived=true&limited=true"
        ).json()
        self.assertEqual([p["name"] for p in data], ["Secret"])
        self.client.force_login(self.ada)
        self.assertEqual(self.client.get("/api/v1/projects/all/").status_code, 403)
        self.client.force_login(self.cleo)
        self.assertEqual(self.client.get("/api/v1/projects/all/").status_code, 403)


class AllProjectsCLITest(Data, test_cli.CLITest):
    def setUp(self):
        super().setUp()
        self.make()

    def test_all(self):
        self.ada.is_admin = True
        self.ada.save()
        output = self.biwak("projects", "--all").output
        self.assertIn("Secret", output)
        self.assertIn("limited joinable", output)
        data = json.loads(
            self.biwak("projects", "--all", "--no-staff", "--json").stdout
        )
        self.assertEqual([p["name"] for p in data], ["Secret"])
        self.assertNotEqual(self.biwak("projects", "--no-staff").exit_code, 0)
