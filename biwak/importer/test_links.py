"""Links to Basecamp recordings in texts go through a trampoline
(specs/import-basecamp.md, "Rich text", decided 2026-11-28): shown
without looking anything up, followed to what was imported from them when
the person may see it, else to Basecamp"""

from urllib.parse import urlencode

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, override_settings

from biwak.importer.models import ImportedObject
from biwak.items import operations as ops
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


def trampoline(href):
    return "/basecamp/?" + urlencode({"to": href})


class RenderingTest(TestCase):
    def test_both_hosts_go_through_the_trampoline(self):
        for href in (f"{BC}/todos/9001", f"{APP}/todos/9001#__recording_9002"):
            with self.subTest(href), self.assertNumQueries(0):
                html = render_markdown(f"See [the tent]({href}).")
                self.assertIn(f'href="{trampoline(href).replace("&", "&amp;")}"', html)
                self.assertNotIn("_blank", html)

    def test_a_bare_address_too(self):
        html = render_markdown(f"See {APP}/todos/9001 please")
        self.assertIn(f'href="{trampoline(f"{APP}/todos/9001")}"', html)

    def test_other_links_stay(self):
        for href in (f"{BC}/schedules/9001", "https://example.org/x"):
            with self.subTest(href):
                self.assertIn(f'href="{href}"', render_markdown(f"[x]({href})"))

    @override_settings(BASE_URL="https://biwak.example.org")
    def test_mails_get_whole_addresses(self):
        html = render_markdown(f"[x]({BC}/todos/9001)", absolute=True)
        self.assertIn(
            f'href="https://biwak.example.org{trampoline(f"{BC}/todos/9001")}"', html
        )

    def test_public_pages_keep_basecamp(self):
        """Nobody signs in there to follow the trampoline"""
        html = render_markdown(f"[x]({BC}/todos/9001)", public_token="abc")
        self.assertIn(f'href="{BC}/todos/9001"', html)


class TrampolineTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.cleo])
        todolist = ops.create_list(project=self.project, title="Camp", creator=self.ada)
        self.todo = ops.create_todo(todolist=todolist, title="Tent", creator=self.ada)
        self.comment = ops.add_comment(self.todo, author=self.ada, content="Done")
        imported(self.todo, "Todo", 9001)
        imported(self.comment, "Comment", 9002)

    def follow(self, href, user=None):
        self.client.force_login(user or self.ada)
        return self.client.get("/basecamp/", {"to": href})

    def test_to_the_import(self):
        for href in (f"{BC}/todos/9001", f"{APP}/todos/9001"):
            with self.subTest(href):
                self.assertRedirects(
                    self.follow(href),
                    self.todo.get_absolute_url(),
                    fetch_redirect_response=False,
                )

    def test_to_the_comment(self):
        response = self.follow(f"{BC}/todos/9001#__recording_9002")
        self.assertRedirects(
            response,
            f"{self.todo.get_absolute_url()}#comment-{self.comment.pk}",
            fetch_redirect_response=False,
        )
        # A comment not imported: its to-do
        response = self.follow(f"{BC}/todos/9001#__recording_7777")
        self.assertRedirects(
            response, self.todo.get_absolute_url(), fetch_redirect_response=False
        )

    def test_to_basecamp_when_not_imported_or_not_visible(self):
        """Both look the same: nothing tells whether it was imported"""
        for href, user in (
            (f"{BC}/todos/7777", self.ada),
            (f"{BC}/todos/9001", self.cleo),  # an internal list
        ):
            with self.subTest(href):
                response = self.follow(href, user)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response["Location"], href)

    def test_only_basecamp_addresses(self):
        """No open redirect"""
        for href in ("https://example.org/", f"{BC}/schedules/1", "", "/todos/1/"):
            with self.subTest(href):
                self.assertEqual(self.follow(href).status_code, 404)

    def test_signed_in_only(self):
        response = self.client.get("/basecamp/", {"to": f"{BC}/todos/9001"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])
