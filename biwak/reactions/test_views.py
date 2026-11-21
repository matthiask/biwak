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

    def test_adding_again_keeps_it_removing_is_explicit(self):
        """The picker and others' pills add, one's own pill removes; choosing
        a reaction one has again keeps it (decided 2026-11-21)"""
        self.client.force_login(self.bob)
        url = f"/items/{self.todo.pk}/reactions/"
        for _ in range(2):
            self.client.post(url, {"content": "👍", "action": "add"})
        self.assertEqual(Reaction.objects.filter(user=self.bob).count(), 1)
        page = self.client.get(self.todo.get_absolute_url()).content.decode()
        # Marked in the picker, the others not
        self.assertRegex(
            page, r'value="👍"\s+class="wb-emoji is-mine"\s+aria-pressed="true"'
        )
        self.assertRegex(page, r'value="🎉"\s+class="wb-emoji"\s+aria-pressed="false"')
        self.assertIn('name="action" value="remove"', page)
        self.client.post(url, {"content": "👍", "action": "remove"})
        self.client.post(url, {"content": "👍", "action": "remove"})
        self.assertFalse(Reaction.objects.filter(user=self.bob).exists())

    def test_removing_says_mine_when_others_reacted_the_same(self):
        from biwak.reactions import operations as reaction_ops

        reaction_ops.add_reaction(self.bob, "👍", item=self.todo)
        self.client.force_login(self.bob)
        alone = self.client.get(self.todo.get_absolute_url())
        self.assertNotContains(alone, ">mine<")
        reaction_ops.add_reaction(self.ada, "👍", item=self.todo)
        shared = self.client.get(self.todo.get_absolute_url())
        self.assertContains(shared, '<span class="small">mine</span>')
        self.client.post(
            f"/items/{self.todo.pk}/reactions/", {"content": "👍", "action": "remove"}
        )
        self.assertEqual(
            list(Reaction.objects.values_list("user", flat=True)), [self.ada.pk]
        )

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

    def test_removing_without_javascript_asks_first(self):
        operations.add_reaction(self.bob, "👍", item=self.todo)
        operations.add_reaction(self.bob, "Thanks!", comment=self.comment)
        self.client.force_login(self.bob)
        page = self.client.get(self.todo.get_absolute_url())
        link = f"/items/{self.todo.pk}/reactions/remove/?content=%F0%9F%91%8D"
        self.assertContains(page, f'href="{link}"')

        response = self.client.get(link)
        self.assertContains(response, "Remove your 👍?")
        self.assertContains(response, f'action="/items/{self.todo.pk}/reactions/"')
        self.assertEqual(Reaction.objects.count(), 2)
        response = self.post(f"/items/{self.todo.pk}/reactions/", "👍", follow=True)
        self.assertEqual(Reaction.objects.count(), 1)

        response = self.client.get(
            f"/comments/{self.comment.pk}/reactions/remove/?content=Thanks!"
        )
        self.assertContains(response, "Remove your Thanks!?")
        self.assertContains(
            response, f'action="/comments/{self.comment.pk}/reactions/"'
        )

    def test_confirmation_only_for_one_s_own_reactions(self):
        operations.add_reaction(self.ada, "👍", item=self.todo)
        url = f"/items/{self.todo.pk}/reactions/remove/?content=%F0%9F%91%8D"
        self.client.force_login(self.bob)
        self.assertRedirects(self.client.get(url), self.todo.get_absolute_url())
        self.client.force_login(self.cleo)
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.cleo)
        internal = self.client.get(
            f"/items/{self.secret.pk}/reactions/remove/?content=x"
        )
        self.assertEqual(internal.status_code, 404)

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
