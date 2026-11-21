import json

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from biwak.accounts.models import APIToken
from biwak.items import operations as ops
from biwak.reactions import operations
from biwak.reactions.models import Reaction
from biwak.test_utils import person, project


class APITest(TestCase):
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
        self.secret_comment = ops.add_comment(self.secret, author=self.ada, content="X")

    def headers(self, user, access="write"):
        _token, secret = APIToken.create_for(user=user, title="T", access=access)
        return {"authorization": f"Bearer {secret}"}

    def call(self, method, user, path, content=None, access="write"):
        kwargs = {}
        if content is not None and method != "get":
            kwargs = {
                "data": json.dumps({"content": content}),
                "content_type": "application/json",
            }
        return getattr(self.client, method)(
            f"/api/v1/{path}", headers=self.headers(user, access), **kwargs
        )

    def test_add_list_remove_on_todo(self):
        path = f"items/{self.todo.pk}/reactions/"
        response = self.call("post", self.bob, path, "👍")
        self.assertEqual(response.status_code, 201)
        self.call("post", self.ada, path, "👍")
        self.call("post", self.ada, path, "Nice")
        response = self.call("get", self.bob, path, access="read")
        found = response.json()
        self.assertEqual([r["content"] for r in found], ["👍", "Nice"])
        self.assertEqual(found[0]["count"], 2)
        self.assertTrue(found[0]["mine"])
        self.assertFalse(found[1]["mine"])
        self.assertEqual(
            [p["name"] for p in found[0]["people"]], ["Bob Example", "Ada Example"]
        )
        # Again: no change; removing only your own
        self.call("post", self.bob, path, "👍")
        self.assertEqual(Reaction.objects.count(), 3)
        response = self.call("delete", self.bob, path, "👍")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["count"], 1)
        self.assertEqual(Reaction.objects.count(), 2)
        self.call("delete", self.bob, path, "Nice")
        self.assertEqual(Reaction.objects.count(), 2)

    def test_on_comment(self):
        path = f"comments/{self.comment.pk}/reactions/"
        self.assertEqual(self.call("post", self.bob, path, "🎉").status_code, 201)
        self.assertEqual(self.call("get", self.bob, path).json()[0]["content"], "🎉")
        self.assertEqual(
            self.call("get", self.bob, f"items/{self.todo.pk}/reactions/").json(), []
        )
        self.call("delete", self.bob, path, "🎉")
        self.assertFalse(Reaction.objects.exists())

    def test_validation(self):
        path = f"items/{self.todo.pk}/reactions/"
        self.assertEqual(self.call("post", self.bob, path, "x" * 41).status_code, 400)
        self.assertEqual(self.call("post", self.bob, path, " ").status_code, 400)
        self.assertEqual(
            self.call(
                "post", self.bob, f"items/{self.shared.pk}/reactions/", "👍"
            ).status_code,
            400,
        )
        self.assertFalse(Reaction.objects.exists())

    def test_read_tokens_cant_write(self):
        path = f"items/{self.todo.pk}/reactions/"
        response = self.call("post", self.bob, path, "👍", access="read")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Reaction.objects.exists())

    def test_client_and_internal_items(self):
        operations.toggle_reaction(self.ada, "🤫", item=self.secret)
        operations.toggle_reaction(self.ada, "🤫", comment=self.secret_comment)
        for path in [
            f"items/{self.secret.pk}/reactions/",
            f"comments/{self.secret_comment.pk}/reactions/",
        ]:
            for method in ["get", "post", "delete"]:
                response = self.call(method, self.cleo, path, "🤫")
                self.assertEqual(response.status_code, 404, (method, path))
        self.assertEqual(Reaction.objects.count(), 2)
        # Visible ones work for a client
        path = f"items/{self.todo.pk}/reactions/"
        self.assertEqual(self.call("post", self.cleo, path, "🙏").status_code, 201)

    def test_in_other_responses(self):
        operations.toggle_reaction(self.bob, "👍", item=self.todo)
        operations.toggle_reaction(self.ada, "Nice", comment=self.comment)
        for path in [
            f"todos/{self.todo.pk}/",
            f"lists/{self.shared.pk}/todos/",
        ]:
            data = self.call("get", self.bob, path).json()
            todo = data[0] if isinstance(data, list) else data
            self.assertEqual(todo["reactions"][0]["content"], "👍", path)
            self.assertTrue(todo["reactions"][0]["mine"])
        data = self.call("get", self.ada, f"todos/{self.todo.pk}/").json()
        self.assertFalse(data["reactions"][0]["mine"])
        data = self.call("get", self.bob, f"items/{self.todo.pk}/comments/").json()
        self.assertEqual(data["results"][0]["reactions"][0]["content"], "Nice")

    def test_the_reactions_are_loaded_once(self):
        """Adding or removing loads the reactions to answer with once, not
        before the change too"""
        for method in ["post", "delete"]:
            with self.subTest(method=method):
                with CaptureQueriesContext(connection) as queries:
                    self.call(
                        method, self.ada, f"items/{self.todo.pk}/reactions/", "🎉"
                    )
                # The reactions with their people, as answered
                loaded = [
                    q["sql"]
                    for q in queries.captured_queries
                    if 'FROM "reactions_reaction" INNER JOIN "accounts_user"'
                    in q["sql"]
                ]
                self.assertEqual(len(loaded), 1, loaded)
