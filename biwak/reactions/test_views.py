from django.test import TestCase

from biwak.activity.models import Action, Event
from biwak.items import operations as ops
from biwak.reactions import operations
from biwak.reactions.emoji import QUICK
from biwak.reactions.models import Reaction
from biwak.test_utils import person, project


class ViewsTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.bob, self.cleo])
        self.shared = ops.create_list(
            project=self.project, title="Shared", creator=self.ada, visible=True
        )
        self.internal = ops.create_list(
            project=self.project, title="Internal", creator=self.ada
        )
        self.todo = ops.create_todo(
            todolist=self.shared, title="Order the tent", creator=self.ada
        )
        self.secret = ops.create_todo(
            todolist=self.internal, title="Secret plan", creator=self.ada
        )
        self.comment = ops.add_comment(self.todo, author=self.ada, content="Hi")
        self.secret_comment = ops.add_comment(
            self.secret, author=self.ada, content="Hush"
        )

    def post(self, url, content, **extra):
        return self.client.post(url, {"content": content}, **extra)

    def test_quick_set_and_form_on_the_page(self):
        self.client.force_login(self.bob)
        response = self.client.get(self.todo.get_absolute_url())
        for emoji in QUICK:
            self.assertContains(response, f'value="{emoji}"')
        self.assertContains(response, 'maxlength="40"')
        self.assertContains(response, f"/items/{self.todo.pk}/reactions/")
        self.assertContains(response, f"/comments/{self.comment.pk}/reactions/")

    def test_toggle_on_todo_and_comment(self):
        self.client.force_login(self.bob)
        response = self.post(f"/items/{self.todo.pk}/reactions/", "👍")
        self.assertRedirects(response, self.todo.get_absolute_url())
        self.post(f"/comments/{self.comment.pk}/reactions/", "Thanks!")
        self.assertEqual(Reaction.objects.count(), 2)
        page = self.client.get(self.todo.get_absolute_url())
        self.assertContains(page, "wb-reaction is-mine")
        self.assertContains(page, "Thanks!")
        self.post(f"/items/{self.todo.pk}/reactions/", "👍")
        self.assertEqual(Reaction.objects.count(), 1)

    def test_htmx_swaps_the_block_only(self):
        self.client.force_login(self.bob)
        response = self.post(
            f"/comments/{self.comment.pk}/reactions/", "🎉", HTTP_HX_REQUEST="true"
        )
        self.assertContains(response, f'id="reactions-comment-{self.comment.pk}"')
        self.assertContains(response, "🎉")
        self.assertNotContains(response, "<html")

    def test_length_and_empty(self):
        self.client.force_login(self.bob)
        response = self.post(
            f"/items/{self.todo.pk}/reactions/", "x" * 41, HTTP_HX_REQUEST="true"
        )
        self.assertContains(response, "at most 40 characters")
        self.post(f"/items/{self.todo.pk}/reactions/", "  ")
        self.assertFalse(Reaction.objects.exists())

    def test_lists_have_none(self):
        self.client.force_login(self.bob)
        response = self.post(f"/items/{self.shared.pk}/reactions/", "👍", follow=True)
        self.assertFalse(Reaction.objects.exists())
        self.assertContains(response, "You can&#x27;t react to this.")

    def test_get_not_allowed(self):
        self.client.force_login(self.bob)
        self.assertEqual(
            self.client.get(f"/items/{self.todo.pk}/reactions/").status_code, 405
        )

    def test_login_required(self):
        response = self.post(f"/items/{self.todo.pk}/reactions/", "👍")
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Reaction.objects.exists())

    def test_client_on_visible_items(self):
        self.client.force_login(self.cleo)
        self.post(f"/items/{self.todo.pk}/reactions/", "👍")
        self.post(f"/comments/{self.comment.pk}/reactions/", "🙏")
        self.assertEqual(Reaction.objects.filter(user=self.cleo).count(), 2)

    def test_client_gets_404_for_internal_items(self):
        self.client.force_login(self.cleo)
        for url in [
            f"/items/{self.secret.pk}/reactions/",
            f"/comments/{self.secret_comment.pk}/reactions/",
            "/items/99999/reactions/",
        ]:
            self.assertEqual(self.post(url, "👍").status_code, 404)
        self.assertFalse(Reaction.objects.exists())
        self.assertFalse(Event.objects.filter(action=Action.REACTED).exists())

    def test_client_doesnt_see_internal_reactions_on_pages(self):
        operations.toggle_reaction(self.bob, "🤫", item=self.secret)
        self.client.force_login(self.cleo)
        self.assertEqual(
            self.client.get(self.secret.get_absolute_url()).status_code, 404
        )
        self.client.force_login(self.bob)
        self.assertContains(self.client.get(self.secret.get_absolute_url()), "🤫")

    def test_visibility_taken_away(self):
        ops.set_visibility(self.shared, visible=False, actor=self.ada)
        self.client.force_login(self.cleo)
        self.assertEqual(
            self.post(f"/items/{self.todo.pk}/reactions/", "👍").status_code, 404
        )

    def test_names_of_everybody(self):
        operations.toggle_reaction(self.ada, "👍", item=self.todo)
        operations.toggle_reaction(self.bob, "👍", item=self.todo)
        self.client.force_login(self.cleo)
        page = self.client.get(self.todo.get_absolute_url())
        self.assertContains(page, 'title="Ada, Bob"')
        self.assertNotContains(page, "is-mine")
