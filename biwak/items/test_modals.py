"""The forms of items in a modal (biwak/modals.py) and as pages of their own"""

from django.test import TestCase

from biwak.items import operations as ops
from biwak.items.models import Item
from biwak.test_utils import (
    MODAL,
    assert_modal,
    assert_modal_redirect,
    assert_page,
    person,
    project,
)


class ItemModalBase(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.cleo])
        self.shared = ops.create_list(
            project=self.project, title="Shared", creator=self.ada, visible=True
        )
        self.internal = ops.create_list(
            project=self.project, title="Internal", creator=self.ada
        )
        self.client.force_login(self.ada)


class GroupModalTest(ItemModalBase):
    def setUp(self):
        super().setUp()
        self.group = ops.create_group(todolist=self.shared.todolist, title="Later")
        self.new = f"/lists/{self.shared.pk}/groups/"
        self.edit = f"/groups/{self.group.pk}/edit/"

    def test_the_list_has_buttons_not_forms(self):
        response = self.client.get(self.shared.get_absolute_url())
        self.assertContains(response, f'href="{self.new}"')
        self.assertContains(response, f'href="{self.edit}"')
        self.assertNotContains(response, 'placeholder="New group"')

    def test_new_group_as_a_modal_and_a_page(self):
        response = self.client.get(self.new, headers=MODAL)
        assert_modal(self, response, title="New group")
        # The list is visible to clients: the banner says so
        self.assertContains(response, "Clients can see this.")
        assert_page(self, self.client.get(self.new), title="New group")
        response = self.client.get(f"/lists/{self.internal.pk}/groups/", headers=MODAL)
        self.assertNotContains(response, "Clients can see this.")

    def test_saving(self):
        response = self.client.post(self.new, {"title": "Soon"}, headers=MODAL)
        assert_modal_redirect(self, response, self.shared.get_absolute_url())
        self.assertEqual(
            list(self.shared.todolist.groups.values_list("title", flat=True)),
            ["Later", "Soon"],
        )
        response = self.client.post(self.new, {"title": "Page"})
        self.assertRedirects(response, self.shared.get_absolute_url())

    def test_errors_show_the_form_in_the_dialog(self):
        response = self.client.post(self.new, {"title": " "}, headers=MODAL)
        assert_modal(self, response, title="New group")
        self.assertContains(response, "This field is required.")
        self.assertEqual(self.shared.todolist.groups.count(), 1)

    def test_edit(self):
        response = self.client.get(self.edit, headers=MODAL)
        assert_modal(self, response, title="Edit the group")
        self.assertContains(response, 'value="Later"')
        assert_page(self, self.client.get(self.edit), title="Edit the group")
        response = self.client.post(self.edit, {"title": "Maybe"}, headers=MODAL)
        assert_modal_redirect(self, response, self.shared.get_absolute_url())
        self.group.refresh_from_db()
        self.assertEqual(self.group.title, "Maybe")
        response = self.client.post(self.edit, {"title": ""}, headers=MODAL)
        assert_modal(self, response, title="Edit the group")
        self.assertContains(response, "This field is required.")

    def test_clients_dont_change_groups_of_lists_staff_created(self):
        self.client.force_login(self.cleo)
        for url in [self.new, self.edit]:
            for headers in [{}, MODAL]:
                with self.subTest(url=url, headers=headers):
                    self.assertEqual(
                        self.client.get(url, headers=headers).status_code, 403
                    )
                    self.assertEqual(
                        self.client.post(
                            url, {"title": "x"}, headers=headers
                        ).status_code,
                        403,
                    )
        response = self.client.get(self.shared.get_absolute_url())
        self.assertNotContains(response, "New group")

    def test_clients_change_the_groups_of_their_lists(self):
        mine = ops.create_list(
            project=self.project, title="Mine", creator=self.cleo, visible=True
        )
        self.client.force_login(self.cleo)
        response = self.client.post(
            f"/lists/{mine.pk}/groups/", {"title": "Wishes"}, headers=MODAL
        )
        assert_modal_redirect(self, response)
        self.assertTrue(Item.objects.filter(pk=mine.pk).exists())
        self.assertEqual(mine.todolist.groups.get().title, "Wishes")


class TrashModalTest(ItemModalBase):
    def setUp(self):
        super().setUp()
        self.todo = ops.create_todo(
            todolist=self.shared, title="Pack", creator=self.ada
        )
        self.url = f"/items/{self.todo.pk}/trash/"

    def test_asks_first(self):
        response = self.client.get(self.url, headers=MODAL)
        assert_modal(self, response, title="Move to the trash?")
        self.assertContains(response, "It can be restored for 30 days.")
        self.assertContains(response, "Clients can see this.")
        assert_page(self, self.client.get(self.url), title="Move to the trash?")
        self.todo.refresh_from_db()
        self.assertNotEqual(self.todo.status, "trashed")

    def test_trashing_redirects_the_modal(self):
        response = self.client.post(self.url, headers=MODAL)
        assert_modal_redirect(self, response, self.shared.get_absolute_url())
        self.todo.refresh_from_db()
        self.assertEqual(self.todo.status, "trashed")

    def test_the_page_has_menu_entries_for_staff(self):
        response = self.client.get(self.todo.get_absolute_url())
        self.assertRegex(response.content.decode(), rf'href="{self.url}"\s+data-modal')
        self.assertContains(response, f'href="/todos/{self.todo.pk}/move-to/"')
        # No level of its own: subscribing is the switch
        # (specs/notifications.md, "Levels")
        self.assertNotContains(response, f"/items/{self.todo.pk}/notifications/")
        self.assertContains(response, ">Move to trash<", count=1)

    def test_clients_may_not_trash_what_staff_made(self):
        self.client.force_login(self.cleo)
        for headers in [{}, MODAL]:
            self.assertEqual(
                self.client.get(self.url, headers=headers).status_code, 403
            )
        response = self.client.get(self.todo.get_absolute_url())
        self.assertNotContains(response, self.url)
        # To-dos move for everybody, and they can see the subscribers
        self.assertContains(response, f"/items/{self.todo.pk}/subscribers/")

    def test_clients_trash_what_they_made(self):
        own = ops.create_todo(todolist=self.shared, title="Mine", creator=self.cleo)
        self.client.force_login(self.cleo)
        url = f"/items/{own.pk}/trash/"
        assert_modal(
            self, self.client.get(url, headers=MODAL), title="Move to the trash?"
        )
        assert_modal_redirect(self, self.client.post(url, headers=MODAL))

    def test_internal_items_are_404_for_clients(self):
        secret = ops.create_todo(todolist=self.internal, title="S", creator=self.ada)
        self.client.force_login(self.cleo)
        url = f"/items/{secret.pk}/trash/"
        for headers in [{}, MODAL]:
            self.assertEqual(self.client.get(url, headers=headers).status_code, 404)


class MoveTodoModalTest(ItemModalBase):
    def setUp(self):
        super().setUp()
        self.group = ops.create_group(todolist=self.internal.todolist, title="Later")
        self.todo = ops.create_todo(
            todolist=self.shared, title="Pack", creator=self.ada
        )
        self.url = f"/todos/{self.todo.pk}/move-to/"

    def test_modal_and_page(self):
        response = self.client.get(self.url, headers=MODAL)
        assert_modal(self, response, title="Move to…")
        self.assertContains(response, "Internal / Later")
        self.assertContains(response, "Clients can see this.")
        assert_page(self, self.client.get(self.url), title="Move to…")

    def test_moving_to_a_group(self):
        response = self.client.post(
            self.url,
            {"target": f"{self.internal.pk}:{self.group.pk}", "index": "0"},
            headers=MODAL,
        )
        assert_modal_redirect(self, response, self.todo.get_absolute_url())
        self.todo.refresh_from_db()
        self.assertEqual(self.todo.parent, self.internal)
        self.assertEqual(self.todo.todo.group, self.group)

    def test_errors_show_the_form_again(self):
        response = self.client.post(
            self.url, {"target": "999999", "index": "0"}, headers=MODAL
        )
        assert_modal(self, response, title="Move to…")
        self.assertContains(response, "Select a valid choice")
        self.todo.refresh_from_db()
        self.assertEqual(self.todo.parent, self.shared)

    def test_completed_todos_dont_move(self):
        ops.complete(self.todo, actor=self.ada)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        response = self.client.get(self.todo.get_absolute_url())
        self.assertNotContains(response, "move-to")

    def test_clients_see_only_visible_lists_and_not_internal_todos(self):
        mine = ops.create_todo(todolist=self.shared, title="Mine", creator=self.cleo)
        self.client.force_login(self.cleo)
        response = self.client.get(f"/todos/{mine.pk}/move-to/", headers=MODAL)
        self.assertNotContains(response, "Internal")
        secret = ops.create_todo(todolist=self.internal, title="S", creator=self.ada)
        self.assertEqual(
            self.client.get(f"/todos/{secret.pk}/move-to/").status_code, 404
        )


class NotificationsModalTest(ItemModalBase):
    def test_a_list(self):
        url = f"/items/{self.shared.pk}/notifications/"
        response = self.client.get(url, headers=MODAL)
        assert_modal(self, response, title="Notifications for this list")
        self.assertContains(response, "As usual (")
        self.assertContains(response, "activity feed always shows everything")
        assert_page(self, self.client.get(url), title="Notifications for this list")
        response = self.client.post(url, {"level": "concerns_me"}, headers=MODAL)
        assert_modal_redirect(self, response, self.shared.get_absolute_url())
        response = self.client.get(url, headers=MODAL)
        self.assertContains(
            response,
            'value="concerns_me" class="form-check-input" id="id_level_2" checked',
        )
        self.assertNotContains(response, 'value="nothing"')

    def test_a_todo_has_none_and_an_unknown_level(self):
        todo = ops.create_todo(todolist=self.shared, title="Pack", creator=self.ada)
        url = f"/items/{todo.pk}/notifications/"
        self.assertEqual(self.client.get(url, headers=MODAL).status_code, 404)
        url = f"/items/{self.shared.pk}/notifications/"
        # "nothing" is gone (decided 2026-11-22)
        for level in ["always", "nothing"]:
            self.assertEqual(
                self.client.post(url, {"level": level}, headers=MODAL).status_code,
                400,
            )

    def test_the_list_page_has_no_inline_form_anymore(self):
        response = self.client.get(self.shared.get_absolute_url())
        self.assertContains(response, "Notifications…")
        self.assertNotContains(response, 'aria-label="Notify me about"')

    def test_clients_set_theirs_on_visible_lists_only(self):
        self.client.force_login(self.cleo)
        url = f"/items/{self.shared.pk}/notifications/"
        assert_modal(
            self,
            self.client.get(url, headers=MODAL),
            title="Notifications for this list",
        )
        self.assertContains(
            self.client.get(self.shared.get_absolute_url()), "Notifications…"
        )
        hidden = f"/items/{self.internal.pk}/notifications/"
        self.assertEqual(self.client.get(hidden, headers=MODAL).status_code, 404)

    def test_the_project(self):
        url = f"/projects/{self.project.pk}/notifications/"
        assert_modal(
            self,
            self.client.get(url, headers=MODAL),
            title="Notifications for this project",
        )
        response = self.client.post(url, {"level": "concerns_me"}, headers=MODAL)
        assert_modal_redirect(self, response, self.project.get_absolute_url())
        self.assertContains(
            self.client.get(self.project.get_absolute_url()), "data-modal"
        )
