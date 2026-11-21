"""The live regions (specs/lantern.md): what frontend/live.js fetches is the
page itself through its view, with the view's permission checks; every
page with live updates says what it shows and marks its regions. Clients
get 404 for internal items, as everywhere."""

from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse

from biwak.items import operations as ops
from biwak.reactions.operations import add_reaction
from biwak.test_utils import check_in_answers, person, project


LIVE = {"X-Biwak-Live": "1"}


class LiveRegionsTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.cleo])

    def pages(self, visible):
        """(name, URL, item, regions) of every page with live updates"""
        todolist = ops.create_list(
            project=self.project, title="Plans", creator=self.ada, visible=visible
        )
        group = ops.create_group(todolist=todolist.todolist, title="Soon")
        todo = ops.create_todo(
            todolist=todolist, title="Pack", creator=self.ada, group=group
        )
        comment = ops.add_comment(todo, author=self.ada, content="On it")
        add_reaction(self.ada, "👍", item=todo)
        message = ops.create_message(
            project=self.project,
            title="News",
            content="Hello",
            creator=self.ada,
            visible=visible,
        )
        doc = ops.create_doc(
            project=self.project, title="Notes", creator=self.ada, visible=visible
        )
        upload = ops.create_upload(
            project=self.project,
            file=ContentFile(b"x", name="plan.txt"),
            creator=self.ada,
            visible=visible,
        )
        question = check_in_answers(self.project, [self.ada])[0].parent
        ops.set_visibility(question, visible=visible, actor=self.ada)
        common = ["live-header", "live-comments"]
        return [
            (
                "to-do",
                todo.get_absolute_url(),
                todo,
                [
                    "live-header",
                    "live-status",
                    "live-text",
                    "live-comments",
                    f"comment-{comment.pk}",
                    f"reactions-item-{todo.pk}",
                ],
            ),
            (
                "list",
                todolist.get_absolute_url(),
                todolist,
                [
                    "live-header",
                    "live-groups",
                    "group-none",
                    f"group-{group.pk}",
                    f"group-{group.pk}-title",
                    f"todos-{group.pk}",
                    f"todo-{todo.pk}",
                    f"add-{group.pk}",
                    "live-completed",
                ],
            ),
            (
                "board",
                todolist.get_absolute_url() + "?view=board",
                todolist,
                [
                    "live-groups",
                    f"todos-{group.pk}",
                    f"todo-{todo.pk}",
                ],
            ),
            ("message", message.get_absolute_url(), message, [*common, "live-text"]),
            ("doc", doc.get_absolute_url(), doc, [*common, "live-text"]),
            ("file", upload.get_absolute_url(), upload, [*common, "live-text"]),
            ("question", question.get_absolute_url(), question, ["live-header"]),
        ]

    def test_staff_get_every_region(self):
        for name, url, item, regions in self.pages(visible=False):
            with self.subTest(page=name):
                self.client.force_login(self.ada)
                response = self.client.get(url, headers=LIVE)
                self.assertEqual(response.status_code, 200)
                page = response.content.decode()
                self.assertIn(f'data-live-item="{item.pk}"', page)
                for region in regions:
                    self.assertIn(f'id="{region}"', page, region)

    def test_clients_get_404_for_internal_items(self):
        self.client.force_login(self.cleo)
        for name, url, _item, _regions in self.pages(visible=False):
            with self.subTest(page=name):
                self.assertEqual(self.client.get(url, headers=LIVE).status_code, 404)

    def test_clients_get_the_regions_of_visible_items(self):
        self.client.force_login(self.cleo)
        for name, url, item, regions in self.pages(visible=True):
            with self.subTest(page=name):
                response = self.client.get(url, headers=LIVE)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, f'data-live-item="{item.pk}"')
                for region in regions:
                    if region.startswith("add-") or region == "live-form":
                        continue
                    self.assertContains(response, f'id="{region}"')

    def test_the_doc_editor_opens_no_second_websocket(self):
        doc = ops.create_doc(project=self.project, title="Notes", creator=self.ada)
        self.client.force_login(self.ada)
        page = self.client.get(reverse("doc_edit", args=[doc.pk]))
        self.assertNotContains(page, 'data-live-socket="/ws/live/"')
        self.assertContains(
            self.client.get(doc.get_absolute_url()), 'data-live-socket="/ws/live/"'
        )
