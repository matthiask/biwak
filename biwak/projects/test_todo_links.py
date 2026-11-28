"""The project page's links to its to-dos (specs/todos.md, "The to-dos page")"""

import re

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


class SectionHeadingsTest(TestCase):
    def test_every_heading_with_a_page_links_to_it(self):
        """Like "Messages" and "Docs and files": "To-do lists" leads to the
        to-dos by list, "Members" to the people, "Activity" to the
        project's activity (the user, 2026-11-28: "the to do lists title
        leads nowhere")"""
        ada = person("Ada")
        cleo = person("Cleo", client=True)
        p = project(members=[ada, cleo])
        for user in [ada, cleo]:
            self.client.force_login(user)
            html = self.client.get(p.get_absolute_url()).content.decode()
            headings = re.findall(
                r'<h2 class="h5[^"]*">\s*<a[^>]*href="([^"]*)"[^>]*>([^<]*)</a>', html
            )
            self.assertEqual(
                [(href, text.strip()) for href, text in headings],
                [
                    (f"/projects/{p.pk}/todos/", "To-do lists"),
                    (f"/projects/{p.pk}/messages/", "Messages"),
                    (f"/projects/{p.pk}/files/", "Docs and files"),
                    (f"/projects/{p.pk}/people/", "Members"),
                    (f"/projects/{p.pk}/feed/", "Activity"),
                ],
            )
