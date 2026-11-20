import datetime as dt

from django.test import TestCase
from django.utils import timezone

from biwak.accounts.models import APIToken
from biwak.activity.models import Action, Event, Subscription
from biwak.items import operations as ops
from biwak.items.models import Item
from biwak.test_utils import person, project


class APITest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.cleo])
        self.internal = ops.create_list(
            project=self.project, title="Internal", creator=self.ada
        )
        self.shared = ops.create_list(
            project=self.project, title="Shared", creator=self.ada, visible=True
        )
        self.secret = ops.create_todo(
            todolist=self.internal, title="Secret", creator=self.ada
        )
        self.todo = ops.create_todo(
            todolist=self.shared, title="Visible", creator=self.ada
        )

    def api(self, user, access="write"):
        _token, secret = APIToken.create_for(user=user, title="Test", access=access)
        return {"authorization": f"Bearer {secret}"}

    def get(self, path, headers, **params):
        return self.client.get(f"/api/v1/{path}", params, headers=headers)

    def send(self, method, path, headers, data=None):
        return getattr(self.client, method)(
            f"/api/v1/{path}", data, content_type="application/json", headers=headers
        )

    def test_authentication(self):
        self.assertEqual(self.client.get("/api/v1/me/").status_code, 401)
        bad = {"authorization": "Bearer biwak_nope"}
        self.assertEqual(self.get("me/", bad).status_code, 401)
        response = self.get("me/", self.api(self.ada, "read"))
        self.assertEqual(response.json()["access"], "read")
        # Sessions work too (the browser, the docs)
        self.client.force_login(self.ada)
        self.assertEqual(self.client.get("/api/v1/me/").json()["access"], "write")

    def test_tokens_expire_and_extend(self):
        token, secret = APIToken.create_for(user=self.ada, title="T", access="read")
        APIToken.objects.filter(pk=token.pk).update(
            expires_at=timezone.now() + dt.timedelta(days=1)
        )
        headers = {"authorization": f"Bearer {secret}"}
        self.assertEqual(self.get("me/", headers).status_code, 200)
        token.refresh_from_db()
        self.assertGreater(token.expires_at, timezone.now() + dt.timedelta(days=29))
        APIToken.objects.filter(pk=token.pk).update(expires_at=timezone.now())
        self.assertEqual(self.get("me/", headers).status_code, 401)
        # Inactive people's tokens don't work
        _token, secret = APIToken.create_for(user=self.ada, title="T", access="read")
        self.ada.is_active = False
        self.ada.save()
        self.assertEqual(
            self.get("me/", {"authorization": f"Bearer {secret}"}).status_code, 401
        )

    def test_read_only(self):
        headers = self.api(self.ada, "read")
        response = self.send("post", f"todos/{self.todo.pk}/complete/", headers)
        self.assertEqual(response.status_code, 403)
        # But it may revoke itself
        self.assertEqual(
            self.send("delete", "tokens/current/", headers).status_code, 200
        )
        self.assertEqual(self.get("me/", headers).status_code, 401)

    def test_clients_dont_create_lists(self):
        response = self.send(
            "post",
            f"projects/{self.project.pk}/lists/",
            self.api(self.cleo),
            {"title": "Our wishes"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Item.objects.filter(title="Our wishes").exists())

    def test_client_sees_what_clients_see(self):
        headers = self.api(self.cleo)
        lists = self.get(f"projects/{self.project.pk}/lists/", headers).json()
        self.assertEqual([item["title"] for item in lists], ["Shared"])
        self.assertTrue(lists[0]["visible_to_clients"])
        for path in [
            f"lists/{self.internal.pk}/",
            f"lists/{self.internal.pk}/todos/",
            f"todos/{self.secret.pk}/",
            f"items/{self.secret.pk}/comments/",
        ]:
            with self.subTest(path=path):
                self.assertEqual(self.get(path, headers).status_code, 404)
        for method, path, data in [
            ("post", f"todos/{self.secret.pk}/complete/", None),
            ("patch", f"todos/{self.secret.pk}/", {"title": "x"}),
            ("post", f"items/{self.secret.pk}/comments/", {"content": "x"}),
            ("post", f"lists/{self.internal.pk}/todos/", {"title": "x"}),
            ("post", f"todos/{self.todo.pk}/move/", {"list_id": self.internal.pk}),
        ]:
            with self.subTest(path=path):
                self.assertEqual(
                    self.send(method, path, headers, data).status_code, 404
                )
        response = self.send(
            "put",
            f"items/{self.shared.pk}/visibility/",
            headers,
            {"visible_to_clients": False},
        )
        self.assertEqual(response.status_code, 403)
        # Members: no addresses for clients
        members = self.get(f"projects/{self.project.pk}/members/", headers).json()
        self.assertEqual({m["email"] for m in members}, {None})
        # What clients create is visible
        response = self.send(
            "post", f"lists/{self.shared.pk}/todos/", headers, {"title": "Wish"}
        )
        self.assertTrue(response.json()["visible_to_clients"])

    def test_todos(self):
        headers = self.api(self.ada)
        group = ops.create_group(todolist=self.shared.todolist, title="Later")
        response = self.send(
            "post",
            f"lists/{self.shared.pk}/todos/",
            headers,
            {
                "title": "From the API",
                "notes": "**Soon**",
                "due_on": "2026-12-01",
                "assignees": [self.cleo.pk],
                "group_id": group.pk,
            },
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["notes_html"], "<p><strong>Soon</strong></p>\n")
        self.assertEqual(data["group"]["title"], "Later")
        self.assertEqual([p["name"] for p in data["assignees"]], ["Cleo Example"])
        self.assertTrue(data["visible_to_clients"])
        self.assertTrue(data["url"].endswith(f"/todos/{data['id']}/"))
        self.assertTrue(
            Event.objects.filter(action=Action.CREATED, item_id=data["id"]).exists()
        )
        self.assertTrue(
            Subscription.objects.filter(user=self.cleo, item_id=data["id"]).exists()
        )
        # Ungrouped first, then by group
        todos = self.get(f"lists/{self.shared.pk}/todos/", headers).json()
        self.assertEqual([t["title"] for t in todos], ["Visible", "From the API"])

        # Changing only what's given
        response = self.send(
            "patch", f"todos/{data['id']}/", headers, {"due_on": None, "assignees": []}
        )
        data = response.json()
        self.assertIsNone(data["due_on"])
        self.assertEqual(data["assignees"], [])
        self.assertEqual(data["notes"], "**Soon**")

        # Clients can't be assigned to internal to-dos
        response = self.send(
            "patch", f"todos/{self.secret.pk}/", headers, {"assignees": [self.cleo.pk]}
        )
        self.assertEqual(response.status_code, 400)

        self.send("post", f"todos/{data['id']}/complete/", headers)
        page = self.get(f"lists/{self.shared.pk}/todos/completed/", headers).json()
        self.assertEqual([t["title"] for t in page["results"]], ["From the API"])
        self.assertEqual(
            [
                t["title"]
                for t in self.get(f"lists/{self.shared.pk}/todos/", headers).json()
            ],
            ["Visible"],
        )

    def test_comments_paginate(self):
        headers = self.api(self.ada)
        for n in range(3):
            self.send(
                "post", f"items/{self.todo.pk}/comments/", headers, {"content": f"#{n}"}
            )
        page = self.get(f"items/{self.todo.pk}/comments/", headers, page_size=2).json()
        self.assertEqual([c["content"] for c in page["results"]], ["#0", "#1"])
        self.assertTrue(page["results"][0]["visible_to_clients"])
        cursor = page["next"].split("cursor=")[1].split("&")[0]
        page = self.get(
            f"items/{self.todo.pk}/comments/", headers, page_size=2, cursor=cursor
        ).json()
        self.assertEqual([c["content"] for c in page["results"]], ["#2"])
        self.assertIsNone(page["next"])
        # No comments on lists
        response = self.send(
            "post", f"items/{self.shared.pk}/comments/", headers, {"content": "x"}
        )
        self.assertEqual(response.status_code, 400)

    def test_visibility_switch(self):
        headers = self.api(self.ada)
        response = self.send(
            "put",
            f"items/{self.internal.pk}/visibility/",
            headers,
            {"visible_to_clients": True},
        )
        self.assertTrue(response.json()["visible_to_clients"])
        self.assertIn(self.secret, Item.objects.visible_to(self.cleo))
        response = self.send(
            "put",
            f"items/{self.secret.pk}/visibility/",
            headers,
            {"visible_to_clients": False},
        )
        self.assertEqual(response.status_code, 400)

    def test_subscription(self):
        headers = self.api(self.ada)
        path = f"items/{self.secret.pk}/subscription/"
        self.assertTrue(self.get(path, headers).json()["subscribed"])  # creator
        self.assertFalse(self.send("delete", path, headers).json()["subscribed"])
        self.assertTrue(self.send("put", path, headers).json()["subscribed"])

    def test_tokens_page_and_cli_login(self):
        self.client.force_login(self.ada)
        response = self.client.post(
            "/accounts/api-tokens/", {"title": "Script", "access": "read"}
        )
        self.assertContains(response, "biwak_")
        token = APIToken.objects.get(title="Script")
        self.client.post(f"/accounts/api-tokens/{token.pk}/delete/")
        self.assertFalse(APIToken.objects.filter(pk=token.pk).exists())

        url = "/accounts/cli-login/?port=4321&state=abcdefghijklmnopq&name=laptop"
        self.assertEqual(self.client.get(url).status_code, 400)  # no access
        self.assertContains(self.client.get(url + "&access=write"), "laptop")
        response = self.client.post(url + "&access=write")
        self.assertContains(response, "http://127.0.0.1:4321/")
        self.assertEqual(APIToken.objects.get().title, "biwak (laptop)")

    def test_cli_version(self):
        headers = self.api(self.ada)
        response = self.get("me/", headers | {"x-biwak-cli": "0.0.1"})
        self.assertEqual(response.status_code, 426)
        response = self.get("me/", headers | {"x-biwak-cli": "0.18.0"})
        self.assertEqual(response.status_code, 426, "no doc locks since 0.19.0")
        response = self.get("me/", headers | {"x-biwak-cli": "0.19.0"})
        self.assertIn("x-biwak-cli-latest", response.headers)

    def test_openapi_schema(self):
        self.client.force_login(self.ada)
        schema = self.client.get("/api/v1/openapi.json").json()
        self.assertIn("/api/v1/lists/{list_id}/todos/", schema["paths"])
        self.assertEqual(self.client.get("/api/v1/docs").status_code, 200)
