"""Moving internal to-dos into a list clients see asks first, like "Show
to clients…" (decided 2026-11-28, specs/access.md): "Move to…", the
selection's "Move…", the posts of dragging, the API and the CLI"""

from django.test import TestCase
from django.urls import reverse

from biwak.accounts.models import APIToken
from biwak.items import operations as ops, visibility
from biwak.items.models import Item
from biwak.test_cli import CLITest
from biwak.test_utils import assert_modal, assert_modal_redirect, person, project


NOTE = "Makes 2 to-dos and 1 comment visible to 1 client."


class Fixture:
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
        self.budget = ops.create_todo(
            todolist=self.internal, title="Budget", creator=self.ada
        )
        ops.add_comment(self.budget, author=self.ada, content="Raise the rate")
        self.rate = ops.create_todo(
            todolist=self.internal, title="Rate", creator=self.ada
        )
        self.tent = ops.create_todo(
            todolist=self.shared, title="Tent", creator=self.ada
        )
        self.client.force_login(self.ada)

    def assertIn_(self, items, todolist):
        for item in items:
            item.refresh_from_db()
            self.assertEqual(item.parent_id, todolist.pk)
            self.assertEqual(item.is_client_visible, todolist.is_client_visible)

    def api(self, path, data):
        _token, secret = APIToken.create_for(user=self.ada, title="T", access="write")
        return self.client.post(
            f"/api/v1/{path}",
            data,
            content_type="application/json",
            headers={"authorization": f"Bearer {secret}"},
        )


class ShowingMovesTest(Fixture, TestCase):
    def test_move_to_asks(self):
        url = f"/todos/{self.budget.pk}/move-to/"
        data = {"target": str(self.shared.pk), "index": "end"}
        response = self.client.post(url, data, headers={"HX-Modal": "true"})
        assert_modal(self, response, title="Move to…")
        self.assertContains(
            response, "Makes 1 to-do and 1 comment visible to 1 client."
        )
        self.assertContains(response, f'name="confirmed" value="{self.shared.pk}"')
        self.assertIn_([self.budget], self.internal)
        # Another target than the one asked about asks again
        response = self.client.post(
            url, data | {"confirmed": "999"}, headers={"HX-Modal": "true"}
        )
        self.assertContains(response, "visible to 1 client")
        self.assertIn_([self.budget], self.internal)
        response = self.client.post(
            url,
            data | {"confirmed": str(self.shared.pk)},
            headers={"HX-Modal": "true"},
        )
        assert_modal_redirect(self, response)
        self.assertIn_([self.budget], self.shared)

    def test_move_to_says_it_hides(self):
        """Like the selection's "Move…" (``hidden_note()``)"""
        url = f"/todos/{self.tent.pk}/move-to/"
        data = {"target": str(self.internal.pk), "index": "end"}
        response = self.client.post(url, data, headers={"HX-Modal": "true"})
        self.assertContains(
            response, "Clients won&#x27;t see 1 to-do any more: the list is internal."
        )
        self.assertIn_([self.tent], self.shared)
        response = self.client.post(
            url,
            data | {"confirmed": str(self.internal.pk)},
            headers={"HX-Modal": "true"},
        )
        assert_modal_redirect(self, response)
        self.assertIn_([self.tent], self.internal)

    def test_nothing_shown_nothing_asked(self):
        # Visible into visible, internal into internal
        other = ops.create_list(
            project=self.project, title="Other", creator=self.ada, visible=True
        )
        for todo, target in [
            (self.tent, other),
            (
                self.rate,
                ops.create_list(project=self.project, title="X", creator=self.ada),
            ),
        ]:
            response = self.client.post(
                f"/todos/{todo.pk}/move-to/", {"target": str(target.pk), "index": "end"}
            )
            self.assertRedirects(response, todo.get_absolute_url())
            self.assertIn_([todo], target)

    def test_selection_asks(self):
        url = (
            reverse("todos_move_selected")
            + f"?items={self.budget.pk}&items={self.rate.pk}&items={self.tent.pk}"
        )
        data = {
            "project": self.project.pk,
            "shown": self.project.pk,
            "target": str(self.shared.pk),
            "index": "end",
        }
        response = self.client.post(url, data, headers={"HX-Modal": "true"})
        self.assertContains(response, NOTE)
        self.assertIn_([self.budget, self.rate], self.internal)
        response = self.client.post(
            url,
            data | {"confirmed": f"{self.project.pk}:{self.shared.pk}"},
            headers={"HX-Modal": "true"},
        )
        assert_modal_redirect(self, response)
        self.assertIn_([self.budget, self.rate, self.tent], self.shared)

    def test_dragging_posts_say_so(self):
        """No page drags to-dos into another list (dragging stays within a
        list): the posts refuse unless they say so"""
        response = self.client.post(
            f"/todos/{self.budget.pk}/move/", {"list": self.shared.pk}
        )
        self.assertEqual(response.status_code, 400)
        response = self.client.post(
            f"/lists/{self.shared.pk}/todos/move/",
            {"todos": [self.budget.pk, self.rate.pk]},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn_([self.budget, self.rate], self.internal)
        response = self.client.post(
            f"/todos/{self.budget.pk}/move/",
            {"list": self.shared.pk, "show_to_clients": "1"},
        )
        self.assertEqual(response.status_code, 302)
        response = self.client.post(
            f"/lists/{self.shared.pk}/todos/move/",
            {"todos": [self.rate.pk], "show_to_clients": "1"},
        )
        self.assertEqual(response.status_code, 204)
        self.assertIn_([self.budget, self.rate], self.shared)

    def test_api(self):
        ids = [self.budget.pk, self.rate.pk]
        for path, data in [
            (f"todos/{self.budget.pk}/move/", {"list_id": self.shared.pk}),
            (f"lists/{self.shared.pk}/todos/move/", {"todo_ids": ids}),
            ("todos/move/", {"ids": ids, "list_id": self.shared.pk}),
        ]:
            with self.subTest(path=path):
                response = self.api(path, data)
                self.assertEqual(response.status_code, 400)
                self.assertIn("visible to 1 client", response.json()["detail"])
                self.assertIn("show_to_clients", response.json()["detail"])
                self.assertIn_([self.budget, self.rate], self.internal)
        response = self.api(
            "todos/move/",
            {"ids": ids, "list_id": self.shared.pk, "show_to_clients": True},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {todo["visible_to_clients"] for todo in response.json()}, {True}
        )
        self.assertIn_([self.budget, self.rate], self.shared)
        # Visible ones need nothing
        response = self.api(
            f"todos/{self.tent.pk}/move/", {"list_id": self.internal.pk}
        )
        self.assertEqual(response.status_code, 200)
        for path, data in [
            (
                f"todos/{self.tent.pk}/move/",
                {"list_id": self.shared.pk, "show_to_clients": True},
            ),
            (
                f"lists/{self.internal.pk}/todos/move/",
                {"todo_ids": [self.tent.pk], "show_to_clients": True},
            ),
        ]:
            # Saying so where nothing is shown is fine too
            with self.subTest(path=path):
                self.assertEqual(self.api(path, data).status_code, 200)


class ShowingAcrossProjectsTest(Fixture, TestCase):
    """Visible to-dos into another project's visible list ask the same
    way when clients there didn't see them (decided 2026-11-28; like
    ``move_to_project``'s ``new_clients()``)"""

    def setUp(self):
        super().setUp()
        self.dot = person("Dot", client=True)
        self.other = project("Other", members=[self.ada, self.cleo, self.dot])
        self.there = ops.create_list(
            project=self.other, title="There", creator=self.ada, visible=True
        )
        ops.add_comment(self.tent, author=self.ada, content="Pegs?")

    def test_selection_asks(self):
        url = reverse("todos_move_selected") + f"?items={self.tent.pk}"
        data = {
            "project": self.other.pk,
            "shown": self.other.pk,
            "target": str(self.there.pk),
            "index": "end",
        }
        response = self.client.post(url, data, headers={"HX-Modal": "true"})
        # Cleo saw it already, Dot didn't
        self.assertContains(
            response, "Makes 1 to-do and 1 comment visible to 1 client."
        )
        self.assertIn_([self.tent], self.shared)
        response = self.client.post(
            url,
            data | {"confirmed": f"{self.other.pk}:{self.there.pk}"},
            headers={"HX-Modal": "true"},
        )
        assert_modal_redirect(self, response)
        self.assertIn_([self.tent], self.there)

    def test_a_new_list_asks_too(self):
        """Visible to-dos make a new list visible (``new_list_visible()``)"""
        url = reverse("todos_move_selected") + f"?items={self.tent.pk}"
        data = {
            "project": self.other.pk,
            "shown": self.other.pk,
            "target": "new",
            "index": "end",
        }
        response = self.client.post(url, data, headers={"HX-Modal": "true"})
        self.assertContains(
            response, "Makes 1 to-do and 1 comment visible to 1 client."
        )
        self.assertIn_([self.tent], self.shared)
        response = self.client.post(
            url,
            data | {"confirmed": f"{self.other.pk}:new"},
            headers={"HX-Modal": "true"},
        )
        assert_modal_redirect(self, response)
        self.tent.refresh_from_db()
        self.assertEqual(self.tent.project, self.other)
        self.assertTrue(self.tent.is_client_visible)

    def test_no_new_clients_nothing_asked(self):
        self.other.memberships.filter(user=self.dot).delete()
        response = self.api(
            "todos/move/", {"ids": [self.tent.pk], "list_id": self.there.pk}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn_([self.tent], self.there)

    def test_api(self):
        response = self.api(
            "todos/move/", {"ids": [self.tent.pk], "list_id": self.there.pk}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("visible to 1 client.", response.json()["detail"])
        self.assertIn("show_to_clients", response.json()["detail"])
        response = self.api(
            "todos/move/",
            {"ids": [self.tent.pk], "list_id": self.there.pk, "show_to_clients": True},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn_([self.tent], self.there)

    def test_internal_and_visible_together(self):
        """Internal ones show to every client there, visible ones to the
        new ones: everybody who sees something new"""
        shown = visibility.shown_by_moving_into(
            [self.budget, self.tent], self.other, visible=True
        )
        self.assertEqual(shown, {"items": 2, "comments": 2, "clients": 2})


class ShowingMovesCLITest(CLITest):
    def test_show_to_clients(self):
        internal = ops.create_list(
            project=self.project, title="Internal", creator=self.ada
        )
        budget = ops.create_todo(todolist=internal, title="Budget", creator=self.ada)
        result = self.biwak("todos", "move", budget.pk, "--list", self.list.pk)
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("visible to 0 clients", result.output)
        self.assertEqual(Item.objects.get(pk=budget.pk).parent_id, internal.pk)
        result = self.biwak(
            "todos", "move", budget.pk, "--list", self.list.pk, "--show-to-clients"
        )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue(Item.objects.get(pk=budget.pk).is_client_visible)


class ShowingFileMovesTest(TestCase):
    """Internal docs, files and folders into a folder clients see ask
    first the same way (decided 2026-11-28): "Move to…", the selection's
    "Move to…", dragging in the library, the API and the CLI"""

    def setUp(self):
        self.ada = person("Ada")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.cleo])
        self.shared = ops.create_folder(
            project=self.project, title="Shared", creator=self.ada, visible=True
        )
        self.plans = ops.create_folder(
            project=self.project, title="Plans", creator=self.ada
        )
        self.budget = ops.create_doc(
            project=self.project, title="Budget", creator=self.ada, parent=self.plans
        )
        ops.add_comment(self.budget, author=self.ada, content="Raise the rate")
        self.rates = ops.create_doc(
            project=self.project, title="Rates", creator=self.ada
        )
        self.client.force_login(self.ada)

    def assertIn_(self, items, folder):
        for item in items:
            item.refresh_from_db()
            self.assertEqual(item.parent_id, folder.pk if folder else None)
            self.assertEqual(
                item.is_client_visible, bool(folder and folder.is_client_visible)
            )

    def test_move_to_asks(self):
        url = f"/items/{self.plans.pk}/move/"
        data = {"folder": str(self.shared.pk)}
        response = self.client.post(url, data, headers={"HX-Modal": "true"})
        assert_modal(self, response, title="Move to…")
        self.assertContains(
            response,
            "Makes it, 1 item below it and 1 comment visible to 1 client.",
        )
        self.assertIn_([self.plans], None)
        response = self.client.post(
            url,
            data | {"confirmed": str(self.shared.pk)},
            headers={"HX-Modal": "true"},
        )
        assert_modal_redirect(self, response)
        self.assertIn_([self.plans], self.shared)
        self.assertTrue(Item.objects.get(pk=self.budget.pk).is_client_visible)

    def test_nothing_shown_nothing_asked(self):
        # Internal into internal, visible out; a draft (only its creator
        # sees it)
        draft = ops.create_draft(project=self.project, creator=self.ada)
        self.assertIsNone(visibility.shown_by_moving_items([draft], self.shared))
        tent = ops.create_doc(
            project=self.project, title="Tent", creator=self.ada, parent=self.shared
        )
        for item, folder in [
            (self.rates, self.plans),
            (tent, None),
        ]:
            response = self.client.post(
                f"/items/{item.pk}/move/", {"folder": folder.pk if folder else ""}
            )
            self.assertRedirects(
                response, item.get_absolute_url(), fetch_redirect_response=False
            )
            self.assertEqual(
                Item.objects.get(pk=item.pk).parent_id, folder and folder.pk
            )

    def test_selection_asks(self):
        url = (
            reverse("files_move", args=[self.project.pk])
            + f"?items={self.plans.pk}&items={self.rates.pk}"
        )
        data = {"folder": str(self.shared.pk)}
        response = self.client.post(url, data, headers={"HX-Modal": "true"})
        self.assertContains(
            response, "Makes 3 items and 1 comment visible to 1 client."
        )
        self.assertIn_([self.plans, self.rates], None)
        response = self.client.post(
            url,
            data | {"confirmed": str(self.shared.pk)},
            headers={"HX-Modal": "true"},
        )
        assert_modal_redirect(self, response)
        self.assertIn_([self.plans, self.rates], self.shared)

    def test_dragging_asks_in_the_modal(self):
        """The drop posts with ``dragged``: ``X-Asks`` instead of moving,
        and the modal it opens then (a GET with the folder) asks"""
        url = reverse("files_move", args=[self.project.pk]) + f"?items={self.rates.pk}"
        response = self.client.post(
            url, {"folder": str(self.shared.pk), "dragged": "1"}
        )
        self.assertEqual(response.headers["X-Asks"], "1")
        self.assertContains(response, "visible to 1 client")
        self.assertIn_([self.rates], None)
        response = self.client.get(
            f"{url}&folder={self.shared.pk}", headers={"HX-Modal": "true"}
        )
        self.assertContains(
            response, "Makes it, 0 items below it and 0 comments visible to 1 client."
        )
        self.assertContains(response, f'name="confirmed" value="{self.shared.pk}"')
        # Dropping where nothing is shown moves
        response = self.client.post(url, {"folder": str(self.plans.pk), "dragged": "1"})
        self.assertEqual(response.status_code, 302)
        self.assertIn_([self.rates], self.plans)

    def test_api(self):
        _token, secret = APIToken.create_for(user=self.ada, title="T", access="write")

        def move(**data):
            return self.client.post(
                f"/api/v1/items/{self.plans.pk}/move/",
                data,
                content_type="application/json",
                headers={"authorization": f"Bearer {secret}"},
            )

        response = move(parent_id=self.shared.pk)
        self.assertEqual(response.status_code, 400)
        self.assertIn("visible to 1 client", response.json()["detail"])
        self.assertIn("show_to_clients", response.json()["detail"])
        self.assertIn_([self.plans], None)
        response = move(parent_id=self.shared.pk, show_to_clients=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["visible_to_clients"])
        # Out again needs nothing
        self.assertEqual(move(parent_id=None).status_code, 200)


class ShowingFileMovesCLITest(CLITest):
    def test_show_to_clients(self):
        shared = ops.create_folder(
            project=self.project, title="Shared", creator=self.ada, visible=True
        )
        doc = ops.create_doc(project=self.project, title="Rates", creator=self.ada)
        result = self.biwak("folders", "move", doc.pk, shared.pk)
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("visible to", result.output)
        self.assertIsNone(Item.objects.get(pk=doc.pk).parent_id)
        result = self.biwak("folders", "move", doc.pk, shared.pk, "--show-to-clients")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue(Item.objects.get(pk=doc.pk).is_client_visible)
