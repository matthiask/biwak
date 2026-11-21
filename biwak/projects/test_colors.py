"""Project colors (specs/project-colors.md): the field, the form, the API,
the suggestion for new projects and the dot next to names"""

import datetime as dt

from django.test import TestCase
from django.urls import reverse

from biwak.accounts.models import ACCENT_NAMES, PALETTE, Accent, APIToken, Color
from biwak.items import operations as ops
from biwak.palette import queries
from biwak.projects import operations as project_ops
from biwak.projects.models import Project
from biwak.test_utils import person, project, tags


class ColorTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.cleo = person("Cleo", client=True)

    def test_one_list_of_names_for_accents_and_projects(self):
        self.assertEqual(len(PALETTE), 10)
        self.assertEqual(list(Accent.values), ACCENT_NAMES)
        self.assertTrue(set(Accent.values) <= set(Color.values))
        self.assertNotIn("amber", Color.values)

    def test_a_project_has_no_color_by_default(self):
        camp = project("Camp")
        self.assertEqual(camp.color, "")
        self.assertEqual(camp.color_label, "")

    def test_staff_set_the_color_clients_cannot(self):
        camp = project("Camp", members=[self.ada, self.cleo])
        project_ops.update_project(camp, actor=self.ada, color="lake")
        camp.refresh_from_db()
        self.assertEqual((camp.color, camp.color_label), ("lake", "Lake"))
        with self.assertRaises(PermissionError):
            project_ops.update_project(camp, actor=self.cleo, color="berry")
        with self.assertRaises(PermissionError):
            project_ops.create_project(name="X", color="berry", actor=self.cleo)
        camp.refresh_from_db()
        self.assertEqual(camp.color, "lake")

    def test_unknown_names_are_refused(self):
        camp = project("Camp")
        with self.assertRaises(Exception) as caught:
            project_ops.update_project(camp, actor=self.ada, color="amber")
        self.assertEqual(type(caught.exception).__name__, "ValidationError")

    def test_new_projects_get_a_color_no_other_active_project_has(self):
        first = project_ops.create_project(name="One", actor=self.ada)
        self.assertEqual(first.color, PALETTE[0])
        second = project_ops.create_project(name="Two", actor=self.ada)
        self.assertEqual(second.color, PALETTE[1])
        # An archived project's color is free again
        project_ops.archive_project(first, actor=self.ada)
        third = project_ops.create_project(name="Three", actor=self.ada)
        self.assertEqual(third.color, PALETTE[0])

    def test_when_all_are_taken_the_least_used_one_is_suggested(self):
        for name in PALETTE:
            Project.objects.create(name=name, color=name)
        Project.objects.create(name="Twice", color="heather")
        self.assertEqual(project_ops.suggested_color(), "lake")

    def test_creating_without_a_color_on_purpose(self):
        made = project_ops.create_project(name="Grey", color="", actor=self.ada)
        self.assertEqual(made.color, "")


class ColorPagesTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.cleo = person("Cleo", client=True)
        self.camp = project("Camp", members=[self.ada, self.cleo])
        project_ops.update_project(self.camp, actor=self.ada, color="forest")

    def checked(self, response):
        import re

        html = response.content.decode()
        return [
            m.group(1)
            for m in re.finditer(r'<input[^>]*value="(\w*)"[^>]*\schecked', html)
            if 'name="color"' in m.group(0)
        ]

    def test_the_edit_page_sets_the_color_for_staff(self):
        self.client.force_login(self.ada)
        url = reverse("project_edit", args=[self.camp.pk])
        self.assertContains(self.client.get(url), 'name="color"')
        response = self.client.post(
            url, {"name": "Camp", "is_all_access": "on", "color": "berry"}
        )
        self.assertEqual(response.status_code, 302)
        self.camp.refresh_from_db()
        self.assertEqual(self.camp.color, "berry")

    def test_the_edit_page_refuses_unknown_names(self):
        self.client.force_login(self.ada)
        response = self.client.post(
            reverse("project_edit", args=[self.camp.pk]),
            {"name": "Camp", "is_all_access": "on", "color": "amber"},
        )
        self.assertEqual(response.status_code, 200)
        self.camp.refresh_from_db()
        self.assertEqual(self.camp.color, "forest")

    def test_a_client_cannot_use_the_edit_page(self):
        self.client.force_login(self.cleo)
        url = reverse("project_edit", args=[self.camp.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
        response = self.client.post(url, {"name": "Camp", "color": "berry"})
        self.assertEqual(response.status_code, 403)
        self.camp.refresh_from_db()
        self.assertEqual(self.camp.color, "forest")

    def test_the_new_project_form_suggests_a_color(self):
        self.client.force_login(self.ada)
        response = self.client.get(reverse("project_create"))
        # Forest is taken: the suggestion is the first free one
        self.assertEqual(self.checked(response), ["heather"])
        self.assertNotContains(response, "<select")

    def test_the_picker_is_radio_swatches_with_the_names_as_labels(self):
        self.client.force_login(self.ada)
        for url in [
            reverse("project_create"),
            reverse("project_edit", args=[self.camp.pk]),
        ]:
            response = self.client.get(url)
            self.assertContains(response, 'type="radio"', count=len(Color.values) + 1)
            self.assertContains(response, 'name="color"', count=len(Color.values) + 1)
            for color in Color:
                self.assertContains(response, f'aria-label="{color.label}"')
                self.assertContains(response, f'title="{color.label}"')
            self.assertContains(response, 'aria-label="None"')
        # The project's own color is the checked one
        self.assertEqual(self.checked(response), ["forest"])

    def test_the_new_project_form_saves_the_chosen_color(self):
        self.client.force_login(self.ada)
        self.client.post(
            reverse("project_create"),
            {"name": "New", "is_all_access": "on", "color": "moss"},
        )
        self.assertEqual(Project.objects.get(name="New").color, "moss")

    def test_the_projects_page_shows_the_card_stripe_and_the_dot_with_the_name(self):
        for user in [self.ada, self.cleo]:
            self.client.force_login(user)
            html = self.client.get(reverse("projects")).content.decode()
            self.assertTrue(
                tags(html, cls="wb-project-card", data_project_color="forest")
            )
            self.assertIn('data-project-color="forest" title="Forest"', html)
            self.assertIn("Camp", html)

    def test_a_project_without_a_color_has_no_dot_and_no_stripe(self):
        project("Plain", members=[self.ada])
        self.client.force_login(self.ada)
        html = self.client.get(reverse("projects")).content.decode()
        # Only Camp's card and its dot
        self.assertEqual(html.count("data-project-color="), 2)

    def test_the_project_header_has_the_line_and_the_dot(self):
        for user in [self.ada, self.cleo]:
            self.client.force_login(user)
            html = self.client.get(self.camp.get_absolute_url()).content.decode()
            for cls in ["wb-project-line", "wb-project-dot"]:
                self.assertTrue(tags(html, cls=cls, data_project_color="forest"))

    def test_the_archived_list_has_the_dot(self):
        project_ops.archive_project(self.camp, actor=self.ada)
        self.client.force_login(self.ada)
        html = self.client.get(reverse("projects"), {"archived": 1}).content.decode()
        self.assertIn('class="wb-project-dot" data-project-color="forest"', html)


class ColorNextToNamesTest(TestCase):
    """The tag where project names are shown beside content: the feed, search,
    "my to-dos" and the palette's results"""

    def setUp(self):
        self.ada = person("Ada")
        self.cleo = person("Cleo", client=True)
        self.camp = project("Camp", members=[self.ada, self.cleo])
        project_ops.update_project(self.camp, actor=self.ada, color="lake")
        self.plain = project("Plain", members=[self.ada, self.cleo])
        self.todos = {}
        for p in [self.camp, self.plain]:
            todo_list = ops.create_list(
                project=p, title=f"Tent list {p.name}", creator=self.ada, visible=True
            )
            self.todos[p] = ops.create_todo(
                todolist=todo_list,
                title=f"Tent todo {p.name}",
                creator=self.ada,
                assignees=[self.ada, self.cleo],
                due_on=dt.date.today(),
            )
        self.dot = 'class="wb-project-dot" data-project-color="lake"'

    def get(self, user, name, **query):
        self.client.force_login(user)
        return self.client.get(reverse(name), query).content.decode()

    def test_the_feed(self):
        for user in [self.ada, self.cleo]:
            html = self.get(user, "feed")
            self.assertIn(self.dot, html, user)
            # One dot, Plain has no color
            self.assertEqual(html.count("wb-project-dot"), html.count(self.dot))

    def test_the_project_feed_does_not_repeat_the_project(self):
        self.client.force_login(self.ada)
        html = self.client.get(
            reverse("project_feed", args=[self.camp.pk])
        ).content.decode()
        self.assertNotIn("wb-project-dot", html)

    def test_search(self):
        for user in [self.ada, self.cleo]:
            html = self.get(user, "search", q="tent")
            self.assertEqual(html.count(self.dot), 2, user)
            self.assertIn("todo Plain", html)

    def test_my_todos(self):
        for user in [self.ada, self.cleo]:
            html = self.get(user, "todos")
            self.assertIn(self.dot, html, user)
            self.assertIn("Tent todo Plain", html)

    def test_the_palette_results_carry_the_color_and_its_name(self):
        results = queries.jumps(self.ada, "camp") + queries.jumps(self.ada, "tent")
        colored = [r for r in results if r["color"]]
        self.assertTrue(colored)
        for result in colored:
            self.assertEqual((result["color"], result["color_name"]), ("lake", "Lake"))
        # Always with the name: the title or the context says which project
        self.assertEqual(
            {r["title"] for r in colored if r["kind"] == "project"}, {"Camp"}
        )
        self.assertTrue(
            all(r["context"] == "Camp" for r in colored if r["kind"] != "project")
        )
        plain = [r for r in results if r["context"] == "Plain"]
        self.assertTrue(plain)
        self.assertFalse(any(r["color"] for r in plain))

    def test_the_palette_endpoint_and_bookmarks(self):
        self.client.force_login(self.cleo)
        data = self.client.get(reverse("palette"), {"q": "camp"}).json()
        self.assertEqual(data["results"][0]["color"], "lake")

    def test_the_tag_is_empty_without_a_color(self):
        from biwak.templatetags.biwak import project_dot

        self.assertEqual(project_dot(self.plain), "")
        self.assertIn("Color: Lake", project_dot(self.camp))


class ColorAPITest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.cleo = person("Cleo", client=True)
        self.camp = project("Camp", members=[self.ada, self.cleo])

    def api(self, method, path, user, data=None):
        _token, secret = APIToken.create_for(user=user, title="T", access="write")
        return getattr(self.client, method)(
            f"/api/v1/{path}",
            data,
            content_type="application/json",
            headers={"authorization": f"Bearer {secret}"},
        )

    def test_staff_set_and_clear_the_color(self):
        path = f"projects/{self.camp.pk}/"
        data = self.api("patch", path, self.ada, {"color": "ember"}).json()
        self.assertEqual((data["color"], data["color_name"]), ("ember", "Ember"))
        # Left out, it stays
        data = self.api("patch", path, self.ada, {"name": "Camp 2"}).json()
        self.assertEqual(data["color"], "ember")
        data = self.api("patch", path, self.ada, {"color": ""}).json()
        self.assertEqual((data["color"], data["color_name"]), ("", ""))

    def test_a_client_cannot_set_it_but_sees_it(self):
        path = f"projects/{self.camp.pk}/"
        self.api("patch", path, self.ada, {"color": "ember"})
        response = self.api("patch", path, self.cleo, {"color": "berry"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.api("get", path, self.cleo).json()["color"], "ember")
        listed = self.api("get", "projects/", self.cleo).json()
        self.assertEqual(listed[0]["color"], "ember")

    def test_unknown_names_are_refused(self):
        path = f"projects/{self.camp.pk}/"
        response = self.api("patch", path, self.ada, {"color": "amber"})
        self.assertEqual(response.status_code, 422)
        self.camp.refresh_from_db()
        self.assertEqual(self.camp.color, "")

    def test_create_suggests_a_color_or_takes_the_given_one(self):
        data = self.api("post", "projects/", self.ada, {"name": "A"}).json()
        self.assertEqual(data["color"], PALETTE[0])
        data = self.api("post", "projects/", self.ada, {"name": "B", "color": "bark"})
        self.assertEqual(data.json()["color"], "bark")
        data = self.api("post", "projects/", self.ada, {"name": "C", "color": ""})
        self.assertEqual(data.json()["color"], "")
        response = self.api(
            "post", "projects/", self.cleo, {"name": "D", "color": "bark"}
        )
        self.assertEqual(response.status_code, 403)
