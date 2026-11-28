"""Links to Basecamp recordings in texts lead to what was imported from them,
when the text is shown (specs/import-basecamp.md, "Links", decided
2026-11-28): whatever was imported first, and links pasted later too"""

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, override_settings

from biwak.importer.models import ImportedObject
from biwak.items import operations as ops
from biwak.items.models import Item
from biwak.templatetags.biwak import render_markdown
from biwak.test_utils import person, project


BC = "https://3.basecamp.com/4001/buckets/5001"
APP = "https://app.basecamp.com/4001/buckets/5001"


def imported(obj, bc_type, bc_id):
    ImportedObject.objects.create(
        basecamp_type=bc_type,
        basecamp_id=bc_id,
        content_type=ContentType.objects.get_for_model(obj),
        object_id=obj.pk,
    )


class BasecampLinksTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.project = project(members=[self.ada])
        todolist = ops.create_list(project=self.project, title="Camp", creator=self.ada)
        self.todo = ops.create_todo(todolist=todolist, title="Tent", creator=self.ada)
        self.comment = ops.add_comment(self.todo, author=self.ada, content="Done")
        imported(self.todo, "Todo", 9001)
        imported(self.comment, "Comment", 9002)

    def test_both_hosts_lead_to_the_import(self):
        for base in (BC, APP):
            with self.subTest(base):
                html = render_markdown(f"See [the tent]({base}/todos/9001).")
                self.assertIn(f'href="{self.todo.get_absolute_url()}"', html)
                self.assertIn(">the tent</a>", html)

    def test_a_bare_address_too(self):
        html = render_markdown(f"See {APP}/todos/9001 please")
        self.assertIn(f'href="{self.todo.get_absolute_url()}"', html)

    def test_a_comment_by_its_anchor(self):
        html = render_markdown(f"[Done]({BC}/todos/9001#__recording_9002)")
        self.assertIn(
            f'href="{self.todo.get_absolute_url()}#comment-{self.comment.pk}"', html
        )
        # Not imported: the to-do
        html = render_markdown(f"[Done]({BC}/todos/9001#__recording_7777)")
        self.assertIn(f'href="{self.todo.get_absolute_url()}"', html)

    def test_what_wasnt_imported_stays(self):
        for href in (
            f"{BC}/todos/7777",
            f"{BC}/schedules/9001",
            "https://example.org/x",
        ):
            with self.subTest(href):
                self.assertIn(f'href="{href}"', render_markdown(f"[x]({href})"))

    def test_imported_later(self):
        """Not imported when the text was written (or imported): the link
        leads there as soon as it is"""
        text = f"[Later]({BC}/messages/9003)"
        self.assertIn(f'href="{BC}/messages/9003"', render_markdown(text))
        message = Item.objects.get(pk=self.todo.parent_id)
        imported(message, "Message", 9003)
        self.assertIn(f'href="{message.get_absolute_url()}"', render_markdown(text))

    @override_settings(BASE_URL="https://biwak.example.org")
    def test_mails_get_whole_addresses(self):
        html = render_markdown(f"[x]({BC}/todos/9001)", absolute=True)
        self.assertIn(
            f'href="https://biwak.example.org{self.todo.get_absolute_url()}"', html
        )

    def test_one_query_for_the_text(self):
        text = f"[a]({BC}/todos/9001) [b]({APP}/todos/9001#__recording_9002) [c]({BC}/todos/7777)"
        with self.assertNumQueries(2):
            render_markdown(text)
        # None: no query at all
        with self.assertNumQueries(0):
            render_markdown("[x](https://example.org/)")
