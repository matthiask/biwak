"""The project page's links to its to-dos (specs/todos.md, "The to-dos page")"""

from django.test import TestCase

from biwak.test_utils import person, project


class ProjectTodoLinksTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.cleo])
        self.todos = f"/projects/{self.project.pk}/todos/"

    def test_both_groupings_are_linked_next_to_the_lists(self):
        for user in [self.ada, self.cleo]:
            self.client.force_login(user)
            response = self.client.get(self.project.get_absolute_url())
            self.assertContains(response, f'href="{self.todos}"')
            self.assertContains(response, f'href="{self.todos}?grouping=due"')

    def test_the_header_says_all_todos_and_restores_the_filters(self):
        self.client.force_login(self.ada)
        html = self.client.get(self.project.get_absolute_url()).content.decode()
        self.assertNotIn("To-dos by due date", html)
        self.assertIn(
            f'<a\n        class="btn btn-sm btn-quiet wb-phone-hide"\n        href="{self.todos}"\n        data-restore-filters',
            html,
        )

    def test_the_top_bar_links_restore_the_filters(self):
        self.client.force_login(self.ada)
        html = self.client.get("/todos/").content.decode()
        self.assertEqual(html.count("data-restore-filters"), 5)
