import datetime as dt
import json
from unittest.mock import patch
from urllib.parse import unquote

import time_machine
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from biwak.accounts.models import APIToken
from biwak.activity.models import Action, Event, Mention, Notification
from biwak.activity.operations import subscribe
from biwak.collab import live
from biwak.files import attachments, operations
from biwak.items import operations as ops
from biwak.items.models import Item, MessageCategory
from biwak.projects import operations as project_ops
from biwak.test_utils import organization, person, project


class APIFixture:
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.bob, self.cleo])
        self.news = MessageCategory.objects.create(name="News", emoji="📣")
        self.public = ops.create_folder(
            project=self.project, title="Public", creator=self.ada, visible=True
        )
        self.private = ops.create_folder(
            project=self.project, title="Private", creator=self.ada
        )
        self.shared_message = ops.create_message(
            project=self.project,
            title="Shared news",
            content="Hello **all**",
            creator=self.ada,
            visible=True,
            category=self.news,
        )
        self.secret_message = ops.create_message(
            project=self.project, title="Secret", content="Internal", creator=self.ada
        )
        self.shared_doc = ops.create_doc(
            project=self.project,
            title="Shared doc",
            content="One",
            creator=self.ada,
            visible=True,
        )
        self.secret_doc = ops.create_doc(
            project=self.project, title="Secret doc", content="Hidden", creator=self.ada
        )
        self.shared_file = self.upload("shared.txt", visible=True)
        self.secret_file = self.upload("secret.txt")

    def upload(self, name, content=b"Plan", **kwargs):
        return ops.create_upload(
            project=self.project,
            file=SimpleUploadedFile(name, content),
            creator=self.ada,
            **kwargs,
        )

    def headers(self, user, access="write"):
        _token, secret = APIToken.create_for(user=user, title="Test", access=access)
        return {"authorization": f"Bearer {secret}"}

    def call(self, user, method, path, data=None, **extra):
        kwargs = {"headers": self.headers(user)} | extra
        if data is not None and "content_type" not in extra and method != "get":
            kwargs["content_type"] = "application/json"
            data = json.dumps(data)
        return getattr(self.client, method)(f"/api/v1/{path}", data, **kwargs)


class MessageAPITest(APIFixture, TestCase):
    def messages(self, user, **params):
        response = self.call(
            user, "get", f"projects/{self.project.pk}/messages/", params
        )
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_staff_lists_everything_clients_what_is_visible(self):
        titles = [m["title"] for m in self.messages(self.ada)["results"]]
        self.assertEqual(titles, ["Secret", "Shared news"])
        results = self.messages(self.cleo)["results"]
        self.assertEqual([m["title"] for m in results], ["Shared news"])
        message = results[0]
        self.assertTrue(message["visible_to_clients"])
        self.assertEqual(message["content"], "Hello **all**")
        self.assertIn("<strong>all</strong>", message["content_html"])
        self.assertEqual(message["excerpt"], "Hello all")
        self.assertEqual(message["category"]["name"], "News")
        self.assertEqual(message["comment_count"], 0)
        self.assertFalse(message["pinned"])

    def test_pinned_first(self):
        operations.pin_message(self.secret_message, actor=self.ada)
        ops.create_message(
            project=self.project, title="Newest", creator=self.ada, visible=True
        )
        titles = [m["title"] for m in self.messages(self.ada)["results"]]
        self.assertEqual(titles, ["Secret", "Newest", "Shared news"])
        operations.pin_message(self.shared_message, actor=self.ada)
        titles = [m["title"] for m in self.messages(self.ada)["results"]]
        self.assertEqual(titles, ["Shared news", "Secret", "Newest"])
        # A client sees the pins of what they see
        titles = [m["title"] for m in self.messages(self.cleo)["results"]]
        self.assertEqual(titles, ["Shared news", "Newest"])

    def test_paging(self):
        for number in range(5):
            ops.create_message(
                project=self.project, title=f"M{number}", creator=self.ada
            )
        page = self.messages(self.ada, page_size=3)
        self.assertEqual(len(page["results"]), 3)
        self.assertTrue(page["next"])
        seen = [m["title"] for m in page["results"]]
        while page["next"]:
            cursor = page["next"].split("cursor=")[1].split("&")[0]

            page = self.messages(self.ada, page_size=3, cursor=unquote(cursor))
            seen += [m["title"] for m in page["results"]]
        self.assertEqual(len(seen), 7)
        self.assertEqual(len(set(seen)), 7)

    def test_non_members_get_404(self):
        outsider = person("Dan", client=True)
        response = self.call(outsider, "get", f"projects/{self.project.pk}/messages/")
        self.assertEqual(response.status_code, 404)

    def test_a_client_gets_404_for_internal_messages(self):
        mid = self.secret_message.pk
        for method, path, data in [
            ("get", f"messages/{mid}/", None),
            ("patch", f"messages/{mid}/", {"title": "x"}),
            ("put", f"messages/{mid}/pin/", None),
            ("delete", f"messages/{mid}/pin/", None),
            ("post", f"items/{mid}/comments/", {"content": "Hi"}),
        ]:
            with self.subTest(path=path, method=method):
                response = self.call(self.cleo, method, path, data)
                self.assertEqual(response.status_code, 404)
        self.assertEqual(Item.objects.get(pk=mid).title, "Secret")
        self.assertFalse(Item.objects.get(pk=mid).is_client_visible)

    def test_notify_defaults_to_everybody(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.call(
                self.ada,
                "post",
                f"projects/{self.project.pk}/messages/",
                {"title": "Hi", "visible_to_clients": True},
            )
        self.assertEqual(response.status_code, 201)
        event = Event.objects.get(item=response.json()["id"], action=Action.CREATED)
        self.assertEqual(
            {n.user for n in event.notifications.all()}, {self.bob, self.cleo}
        )

    def test_create(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.call(
                self.ada,
                "post",
                f"projects/{self.project.pk}/messages/",
                {
                    "title": "Posted",
                    "content": "Text",
                    "category_id": self.news.pk,
                    "visible_to_clients": True,
                    "notify": "everybody",
                },
            )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertTrue(data["visible_to_clients"])
        self.assertEqual(data["category"]["id"], self.news.pk)
        item = Item.objects.get(pk=data["id"])
        event = Event.objects.get(item=item, action=Action.CREATED)
        self.assertEqual(
            {n.user for n in event.notifications.all()}, {self.bob, self.cleo}
        )

    def test_create_notifying_chosen_people_or_nobody(self):
        url = f"projects/{self.project.pk}/messages/"
        with self.captureOnCommitCallbacks(execute=True):
            response = self.call(
                self.ada,
                "post",
                url,
                {"title": "A", "visible_to_clients": True, "notify": [self.cleo.pk]},
            )
        event = Event.objects.get(item=response.json()["id"], action=Action.CREATED)
        self.assertEqual({n.user for n in event.notifications.all()}, {self.cleo})
        with self.captureOnCommitCallbacks(execute=True):
            response = self.call(
                self.ada, "post", url, {"title": "B", "notify": "nobody"}
            )
        event = Event.objects.get(item=response.json()["id"], action=Action.CREATED)
        self.assertEqual(event.notifications.count(), 0)

    def test_only_members_can_be_notified(self):
        outsider = person("Dan")
        response = self.call(
            self.ada,
            "post",
            f"projects/{self.project.pk}/messages/",
            {"title": "A", "notify": [outsider.pk]},
        )
        self.assertEqual(response.status_code, 400)

    def test_clients_post_visible_messages(self):
        response = self.call(
            self.cleo,
            "post",
            f"projects/{self.project.pk}/messages/",
            {"title": "From a client", "notify": "nobody"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["visible_to_clients"])

    def test_bad_input(self):
        url = f"projects/{self.project.pk}/messages/"
        for data in [
            {"title": " ", "notify": "nobody"},
            {"title": "x", "notify": "nobody", "category_id": 99999},
        ]:
            self.assertEqual(self.call(self.ada, "post", url, data).status_code, 400)

    def test_read_only_tokens_cannot_write(self):
        headers = self.headers(self.ada, access="read")
        response = self.client.post(
            f"/api/v1/projects/{self.project.pk}/messages/",
            json.dumps({"title": "x", "notify": "nobody"}),
            content_type="application/json",
            headers=headers,
        )
        self.assertIn(response.status_code, {401, 403})

    def test_update(self):
        mid = self.secret_message.pk
        response = self.call(
            self.ada,
            "patch",
            f"messages/{mid}/",
            {"title": "New", "content": "Text", "category_id": self.news.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["category"]["name"], "News")
        response = self.call(
            self.ada, "patch", f"messages/{mid}/", {"category_id": None}
        )
        self.assertIsNone(response.json()["category"])
        self.assertEqual(response.json()["title"], "New")

    def test_clients_update_only_their_messages(self):
        response = self.call(
            self.cleo, "patch", f"messages/{self.shared_message.pk}/", {"title": "x"}
        )
        self.assertEqual(response.status_code, 403)
        mine = ops.create_message(
            project=self.project, title="Mine", creator=self.cleo, visible=True
        )
        response = self.call(
            self.cleo, "patch", f"messages/{mine.pk}/", {"title": "Changed"}
        )
        self.assertEqual(response.status_code, 200)

    def test_pinning(self):
        mid = self.shared_message.pk
        response = self.call(self.ada, "put", f"messages/{mid}/pin/")
        self.assertTrue(response.json()["pinned"])
        self.assertIsNotNone(response.json()["pinned_at"])
        response = self.call(self.ada, "delete", f"messages/{mid}/pin/")
        self.assertFalse(response.json()["pinned"])
        self.assertEqual(
            list(
                Event.objects
                .filter(item=self.shared_message)
                .values_list("action", flat=True)
                .order_by("pk")
            )[-2:],
            ["unpinned", "pinned"][::-1],
        )

    def test_a_client_cannot_pin(self):
        mid = self.shared_message.pk
        self.assertEqual(
            self.call(self.cleo, "put", f"messages/{mid}/pin/").status_code, 403
        )
        self.assertEqual(
            self.call(self.cleo, "delete", f"messages/{mid}/pin/").status_code, 403
        )
        self.assertIsNone(Item.objects.get(pk=mid).message.pinned_at)

    def test_pinning_notifies_nobody(self):

        subscribe(self.bob, self.shared_message)
        with self.captureOnCommitCallbacks(execute=True):
            self.call(self.ada, "put", f"messages/{self.shared_message.pk}/pin/")
        self.assertFalse(
            Notification.objects.filter(user=self.bob, event__action="pinned").exists()
        )

    def test_categories(self):
        response = self.call(self.cleo, "get", "message-categories/")
        self.assertEqual(
            response.json(), [{"id": self.news.pk, "name": "News", "emoji": "📣"}]
        )

    def test_comments_work_on_messages(self):
        response = self.call(
            self.cleo,
            "post",
            f"items/{self.shared_message.pk}/comments/",
            {"content": "Hi"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.messages(self.cleo)["results"][0]["comment_count"], 1)

    def test_events_in_the_feed_follow_visibility(self):
        operations.pin_message(self.secret_message, actor=self.ada)
        operations.pin_message(self.shared_message, actor=self.ada)
        response = self.call(self.cleo, "get", "feed/", {"project_id": self.project.pk})
        self.assertEqual(response.status_code, 200)
        text = json.dumps(response.json())
        self.assertIn("Shared news", text)
        self.assertNotIn("Secret", text)
        self.assertIn("pinned", text)


class MentionsAPITest(APIFixture, TestCase):
    """Plain mentions are resolved on create and on update, for those who
    can see the item (like to-dos and comments)"""

    def test_message_create_and_update(self):
        response = self.call(
            self.ada,
            "post",
            f"projects/{self.project.pk}/messages/",
            {"title": "N", "content": "Hi @bob@example.org", "notify": "nobody"},
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["content"], f"Hi [@Bob](person:{self.bob.pk})")
        pk = response.json()["id"]
        response = self.call(
            self.ada, "patch", f"messages/{pk}/", {"content": "Hi @Bob"}
        )
        self.assertEqual(response.json()["content"], f"Hi [@Bob](person:{self.bob.pk})")
        self.assertTrue(Mention.objects.filter(item_id=pk, user=self.bob).exists())
        # A client can't see an internal message: stays as written
        response = self.call(
            self.ada, "patch", f"messages/{pk}/", {"content": "Hi @cleo@example.org"}
        )
        self.assertEqual(response.json()["content"], "Hi @cleo@example.org")

    def test_visible_message_resolves_clients(self):
        response = self.call(
            self.ada,
            "post",
            f"projects/{self.project.pk}/messages/",
            {
                "title": "N",
                "content": "Hi @cleo@example.org",
                "visible_to_clients": True,
                "notify": "nobody",
            },
        )
        self.assertIn(f"(person:{self.cleo.pk})", response.json()["content"])

    def test_doc_create_and_update(self):
        response = self.call(
            self.ada,
            "post",
            f"projects/{self.project.pk}/docs/",
            {"title": "D", "content": "See @bob@example.org", "notify": "nobody"},
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(
            response.json()["content"], f"See [@Bob](person:{self.bob.pk})"
        )
        pk = response.json()["id"]
        response = self.call(
            self.ada, "patch", f"docs/{pk}/", {"content": "Then @bob@example.org"}
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            response.json()["content"], f"Then [@Bob](person:{self.bob.pk})"
        )
        self.assertTrue(Mention.objects.filter(item_id=pk, user=self.bob).exists())


class FolderAPITest(APIFixture, TestCase):
    def files(self, user, **params):
        return self.call(user, "get", f"projects/{self.project.pk}/files/", params)

    def test_the_root(self):
        data = self.files(self.ada).json()
        self.assertIsNone(data["folder"])
        titles = [e["title"] for e in data["entries"]]
        # Folders first, then docs and files by title
        self.assertEqual(titles[:2], ["Private", "Public"])
        self.assertEqual(
            titles[2:], ["Secret doc", "secret.txt", "Shared doc", "shared.txt"]
        )
        files = {e["title"]: e for e in data["entries"]}
        self.assertEqual(files["shared.txt"]["size"], 4)
        self.assertEqual(files["shared.txt"]["content_type"], "text/plain")
        self.assertTrue(files["shared.txt"]["download_url"].endswith("/download/"))
        self.assertIsNone(files["Public"]["size"])

    def test_a_client_sees_what_is_visible(self):
        data = self.files(self.cleo).json()
        self.assertEqual(
            sorted(e["title"] for e in data["entries"]),
            ["Public", "Shared doc", "shared.txt"],
        )
        self.assertTrue(all(e["visible_to_clients"] for e in data["entries"]))

    def test_a_folder(self):
        nested = ops.create_upload(
            project=self.project,
            file=SimpleUploadedFile("nested.txt", b"x"),
            creator=self.ada,
            parent=self.public,
        )
        data = self.files(self.cleo, folder_id=self.public.pk).json()
        self.assertEqual([e["id"] for e in data["entries"]], [nested.pk])
        self.assertEqual(data["folder"]["id"], self.public.pk)
        self.assertEqual([c["title"] for c in data["breadcrumbs"]], ["Public"])
        self.assertTrue(data["entries"][0]["visible_to_clients"])

    def test_internal_folders_are_404_for_clients(self):
        self.assertEqual(
            self.files(self.cleo, folder_id=self.private.pk).status_code, 404
        )
        for path, data in [
            (
                f"projects/{self.project.pk}/folders/",
                {"title": "x", "parent_id": self.private.pk},
            ),
            (
                f"projects/{self.project.pk}/docs/",
                {"title": "x", "parent_id": self.private.pk, "notify": "nobody"},
            ),
        ]:
            self.assertEqual(self.call(self.cleo, "post", path, data).status_code, 404)

    def test_a_folder_of_another_project_is_404(self):
        other = project("Other", members=[self.ada])
        folder = ops.create_folder(project=other, title="Elsewhere", creator=self.ada)
        self.assertEqual(self.files(self.ada, folder_id=folder.pk).status_code, 404)

    def test_create_folders(self):
        url = f"projects/{self.project.pk}/folders/"
        response = self.call(
            self.ada, "post", url, {"title": "Top", "visible_to_clients": True}
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["visible_to_clients"])
        response = self.call(
            self.ada, "post", url, {"title": "Inner", "parent_id": self.private.pk}
        )
        self.assertEqual(response.json()["parent_id"], self.private.pk)
        self.assertFalse(response.json()["visible_to_clients"])
        # Clients create to-dos, comments and messages (specs/access.md)
        response = self.call(self.cleo, "post", url, {"title": "Client folder"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            self.call(self.ada, "post", url, {"title": " "}).status_code, 400
        )

    def test_move(self):
        mid = self.secret_file.pk
        response = self.call(
            self.ada, "post", f"items/{mid}/move/", {"parent_id": self.public.pk}
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["visible_to_clients"])
        self.assertEqual(self.call(self.cleo, "get", f"files/{mid}/").status_code, 200)
        response = self.call(
            self.ada, "post", f"items/{mid}/move/", {"parent_id": self.private.pk}
        )
        self.assertFalse(response.json()["visible_to_clients"])
        self.assertEqual(self.call(self.cleo, "get", f"files/{mid}/").status_code, 404)

    def test_moving_a_folder_changes_its_contents(self):
        inner = ops.create_upload(
            project=self.project,
            file=SimpleUploadedFile("inner.txt", b"x"),
            creator=self.ada,
            parent=self.private,
        )
        self.call(
            self.ada,
            "post",
            f"items/{self.private.pk}/move/",
            {"parent_id": self.public.pk},
        )
        self.assertEqual(
            self.call(self.cleo, "get", f"files/{inner.pk}/").status_code, 200
        )
        self.call(
            self.ada, "post", f"items/{self.private.pk}/move/", {"parent_id": None}
        )
        self.assertEqual(
            self.call(self.cleo, "get", f"files/{inner.pk}/").status_code, 404
        )

    def test_move_errors(self):
        url = f"items/{self.private.pk}/move/"
        response = self.call(self.ada, "post", url, {"parent_id": self.private.pk})
        self.assertEqual(response.status_code, 400)
        message = self.shared_message
        response = self.call(
            self.ada, "post", f"items/{message.pk}/move/", {"parent_id": None}
        )
        self.assertEqual(response.status_code, 400)
        # Clients move only what they created
        response = self.call(
            self.cleo, "post", f"items/{self.shared_file.pk}/move/", {"parent_id": None}
        )
        self.assertEqual(response.status_code, 403)
        # And not into folders they do not see
        mine = ops.create_upload(
            project=self.project,
            file=SimpleUploadedFile("mine.txt", b"x"),
            creator=self.cleo,
            parent=self.public,
        )
        response = self.call(
            self.cleo, "post", f"items/{mine.pk}/move/", {"parent_id": self.private.pk}
        )
        self.assertEqual(response.status_code, 404)
        response = self.call(
            self.cleo, "post", f"items/{self.secret_file.pk}/move/", {"parent_id": None}
        )
        self.assertEqual(response.status_code, 404)


class DocAPITest(APIFixture, TestCase):
    def test_get(self):
        for user in [self.ada, self.cleo]:
            data = self.call(user, "get", f"docs/{self.shared_doc.pk}/").json()
            self.assertEqual(data["content"], "One")
            self.assertTrue(data["visible_to_clients"])
            self.assertEqual(
                data["version_id"], self.shared_doc.doc.versions.first().pk
            )
            self.assertFalse(data["read_only"])

    def test_internal_docs_are_404_for_clients_everywhere(self):
        did = self.secret_doc.pk
        version = self.secret_doc.doc.versions.first().pk
        for method, path, data in [
            ("get", f"docs/{did}/", None),
            ("patch", f"docs/{did}/", {"content": "Hacked"}),
            ("patch", f"docs/{did}/", {"read_only": True}),
            ("get", f"docs/{did}/versions/", None),
            ("get", f"docs/{did}/versions/{version}/", None),
            ("post", f"docs/{did}/versions/{version}/restore/", None),
            ("post", f"items/{did}/move/", {"parent_id": None}),
        ]:
            with self.subTest(path=path, method=method):
                self.assertEqual(
                    self.call(self.cleo, method, path, data).status_code, 404
                )
        self.assertEqual(self.secret_doc.doc.content, "Hidden")

    def test_create(self):
        response = self.call(
            self.ada,
            "post",
            f"projects/{self.project.pk}/docs/",
            {
                "title": "New",
                "content": "Text",
                "parent_id": self.public.pk,
                "notify": "nobody",
            },
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["visible_to_clients"])
        # Without notify, everybody is told
        response = self.call(
            self.ada, "post", f"projects/{self.project.pk}/docs/", {"title": "x"}
        )
        self.assertEqual(response.status_code, 201)

    def test_clients_dont_create_docs(self):
        """Clients create to-dos, comments and messages (specs/access.md)"""
        response = self.call(
            self.cleo,
            "post",
            f"projects/{self.project.pk}/docs/",
            {"title": "Ours", "parent_id": self.public.pk},
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Item.objects.filter(title="Ours").exists())

    def test_update_with_the_version_rules(self):
        did = self.shared_doc.pk
        response = self.call(self.ada, "patch", f"docs/{did}/", {"content": "Two"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.shared_doc.doc.versions.count(), 1)
        response = self.call(
            self.bob, "patch", f"docs/{did}/", {"content": "Three", "title": "Renamed"}
        )
        self.assertEqual(response.json()["title"], "Renamed")
        self.assertEqual(self.shared_doc.doc.versions.count(), 2)
        response = self.call(
            self.bob, "patch", f"docs/{did}/", {"content": "Four", "new_version": True}
        )
        self.assertEqual(self.shared_doc.doc.versions.count(), 3)
        with time_machine.travel(timezone.now() + dt.timedelta(minutes=11)):
            self.call(self.bob, "patch", f"docs/{did}/", {"content": "Five"})
        self.assertEqual(self.shared_doc.doc.versions.count(), 4)

    def test_clients_cannot_edit_docs_staff_created(self):
        """Clients change only what they created (specs/access.md)"""
        did = self.shared_doc.pk
        for data in [
            {"content": "Scope doubled, same price"},
            {"read_only": True},
        ]:
            with self.subTest(data=data):
                response = self.call(self.cleo, "patch", f"docs/{did}/", data)
                self.assertEqual(response.status_code, 403)
        self.shared_doc.doc.refresh_from_db()
        self.assertEqual(self.shared_doc.doc.content, "One")
        self.assertFalse(self.shared_doc.doc.read_only)

    def test_a_client_edits_a_doc_it_created(self):
        doc = ops.create_doc(
            project=self.project, title="Ours", creator=self.cleo, visible=True
        )
        response = self.call(
            self.cleo, "patch", f"docs/{doc.pk}/", {"content": "By Cleo"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["content"], "By Cleo")
        # Read-only is for staff
        response = self.call(self.cleo, "patch", f"docs/{doc.pk}/", {"read_only": True})
        self.assertEqual(response.status_code, 403)

    def test_refusing_to_overwrite_a_newer_version(self):
        did = self.shared_doc.pk
        base = self.call(self.ada, "get", f"docs/{did}/").json()["version_id"]
        self.call(self.bob, "patch", f"docs/{did}/", {"content": "Bob's"})
        response = self.call(
            self.ada,
            "patch",
            f"docs/{did}/",
            {"content": "Ada's", "base_version": base},
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("Bob", response.json()["detail"])
        self.assertEqual(Item.objects.get(pk=did).doc.content, "Bob's")
        # Without a base the save goes through
        response = self.call(self.ada, "patch", f"docs/{did}/", {"content": "Ada's"})
        self.assertEqual(response.status_code, 200)

    def test_read_only(self):
        did = self.shared_doc.pk
        response = self.call(
            self.bob, "patch", f"docs/{did}/", {"read_only": True, "content": "Last"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["content"], "Last")
        self.assertTrue(response.json()["read_only"])
        response = self.call(self.ada, "patch", f"docs/{did}/", {"content": "x"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "The doc is read-only.")
        old = self.shared_doc.doc.versions.last().pk
        response = self.call(self.ada, "post", f"docs/{did}/versions/{old}/restore/")
        self.assertEqual(response.status_code, 409)
        response = self.call(
            self.ada, "patch", f"docs/{did}/", {"read_only": False, "content": "y"}
        )
        self.assertEqual(response.json()["content"], "y")
        self.assertFalse(response.json()["read_only"])

    def test_edits_merge_with_what_is_typed_live(self):
        """The content is an edit of the text as last saved: what people
        typed meanwhile stays (specs/collaboration.md)"""
        did = self.shared_doc.pk
        live.apply_text(Item.objects.get(pk=did).doc, "One, typed live", user=self.bob)
        response = self.call(self.ada, "patch", f"docs/{did}/", {"content": "Uno"})
        self.assertEqual(response.json()["content"], "Uno, typed live")

    def test_versions_are_for_staff(self):
        did = self.shared_doc.pk
        self.call(self.bob, "patch", f"docs/{did}/", {"content": "Two"})
        versions = self.call(self.ada, "get", f"docs/{did}/versions/").json()
        self.assertEqual([v["is_current"] for v in versions], [True, False])
        old = versions[1]["id"]
        detail = self.call(self.ada, "get", f"docs/{did}/versions/{old}/").json()
        self.assertEqual(detail["content"], "One")
        for path in [f"docs/{did}/versions/", f"docs/{did}/versions/{old}/"]:
            self.assertEqual(self.call(self.cleo, "get", path).status_code, 403)
        self.assertEqual(
            self.call(
                self.cleo, "post", f"docs/{did}/versions/{old}/restore/"
            ).status_code,
            403,
        )

    def test_restoring(self):
        did = self.shared_doc.pk
        self.call(self.bob, "patch", f"docs/{did}/", {"content": "Two"})
        old = self.shared_doc.doc.versions.last().pk
        response = self.call(self.ada, "post", f"docs/{did}/versions/{old}/restore/")
        self.assertEqual(response.json()["content"], "One")
        self.assertEqual(self.shared_doc.doc.versions.count(), 3)
        other = self.secret_doc.doc.versions.first().pk
        self.assertEqual(
            self.call(self.ada, "get", f"docs/{did}/versions/{other}/").status_code, 404
        )


class FileAPITest(APIFixture, TestCase):
    def post_file(self, user, name="new.txt", content=b"New", **data):
        data = ({} if data.pop("no_notify", False) else {"notify": "nobody"}) | data
        return self.client.post(
            f"/api/v1/projects/{self.project.pk}/files/",
            {"file": SimpleUploadedFile(name, content)} | data,
            headers=self.headers(user),
        )

    def test_upload(self):
        response = self.post_file(
            self.ada, description="About", visible_to_clients="true"
        )
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()
        self.assertEqual(data["name"], "new.txt")
        self.assertEqual(data["description"], "About")
        self.assertTrue(data["visible_to_clients"])
        self.assertEqual(len(data["versions"]), 1)
        self.assertTrue(data["download_url"].endswith(f"/files/{data['id']}/download/"))

    def test_upload_into_a_folder_and_notify(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.post_file(
                self.ada, parent_id=self.public.pk, notify="everybody"
            )
        data = response.json()
        self.assertEqual(data["parent_id"], self.public.pk)
        self.assertTrue(data["visible_to_clients"])
        event = Event.objects.get(item=data["id"], action=Action.CREATED)
        self.assertEqual(
            {n.user for n in event.notifications.all()}, {self.bob, self.cleo}
        )
        with self.captureOnCommitCallbacks(execute=True):
            response = self.post_file(
                self.ada, parent_id=self.public.pk, notify=f"{self.bob.pk}"
            )
        event = Event.objects.get(item=response.json()["id"], action=Action.CREATED)
        self.assertEqual({n.user for n in event.notifications.all()}, {self.bob})

    def test_upload_notifies_everybody_by_default(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.post_file(
                self.ada, parent_id=self.public.pk, no_notify=True
            )
        event = Event.objects.get(item=response.json()["id"], action=Action.CREATED)
        self.assertEqual(
            {n.user for n in event.notifications.all()}, {self.bob, self.cleo}
        )

    def test_bad_notify(self):
        self.assertEqual(self.post_file(self.ada, notify="some").status_code, 400)
        outsider = person("Dan")
        self.assertEqual(
            self.post_file(self.ada, notify=str(outsider.pk)).status_code, 400
        )

    def test_clients_dont_upload(self):
        """Clients create to-dos, comments and messages (specs/access.md)"""
        response = self.post_file(self.cleo, parent_id=self.public.pk)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.post_file(self.cleo).status_code, 403)
        self.assertEqual(
            self.post_file(self.cleo, parent_id=self.private.pk).status_code, 404
        )
        self.assertFalse(Item.objects.filter(title="new.txt").exists())

    def test_too_large(self):

        with patch.object(attachments, "MAX_SIZE", 2):
            self.assertEqual(self.post_file(self.ada).status_code, 413)

    def test_detail(self):
        for user in [self.ada, self.cleo]:
            data = self.call(user, "get", f"files/{self.shared_file.pk}/").json()
            self.assertEqual(data["name"], "shared.txt")
            self.assertEqual(data["size"], 4)
            self.assertTrue(data["visible_to_clients"])

    def test_a_client_gets_404_for_internal_files_everywhere(self):
        fid = self.secret_file.pk
        version = self.secret_file.upload.versions.get().pk
        for method, path, data in [
            ("get", f"files/{fid}/", None),
            ("patch", f"files/{fid}/", {"title": "x"}),
            ("get", f"files/{fid}/download/", None),
            ("get", f"files/{fid}/versions/", None),
            ("get", f"files/{fid}/versions/{version}/download/", None),
            ("post", f"items/{fid}/comments/", {"content": "Hi"}),
        ]:
            with self.subTest(path=path, method=method):
                self.assertEqual(
                    self.call(self.cleo, method, path, data).status_code, 404
                )
        response = self.client.post(
            f"/api/v1/files/{fid}/versions/",
            {"file": SimpleUploadedFile("x.txt", b"x")},
            headers=self.headers(self.cleo),
        )
        self.assertEqual(response.status_code, 404)

    def test_download(self):
        response = self.call(self.cleo, "get", f"files/{self.shared_file.pk}/download/")
        self.assertEqual(b"".join(response.streaming_content), b"Plan")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(
            self.call(
                self.ada, "get", f"files/{self.secret_file.pk}/download/"
            ).status_code,
            200,
        )

    def test_clients_of_the_same_organization_change_each_others_files(self):
        colleague = person("Cora", client=True)
        stranger = person("Dan", client=True)
        stranger.organization = organization("Other Ltd")
        stranger.save()
        nobody = person("Eve", client=True)
        nobody.organization = None
        nobody.save()
        no_org = person("Finn", client=True)
        no_org.organization = None
        no_org.save()
        for user in [colleague, stranger, nobody, no_org]:
            project_ops.add_member(self.project, user, actor=self.ada)
        theirs = ops.create_upload(
            project=self.project,
            file=SimpleUploadedFile("cleo.txt", b"Plan"),
            creator=self.cleo,
            parent=self.public,
        )
        by_nobody = ops.create_upload(
            project=self.project,
            file=SimpleUploadedFile("eve.txt", b"Plan"),
            creator=nobody,
            parent=self.public,
        )
        for user, item, allowed in [
            (colleague, theirs, True),
            (stranger, theirs, False),
            (nobody, theirs, False),
            (no_org, by_nobody, False),
            (colleague, self.shared_file, False),
            (self.ada, theirs, True),
        ]:
            with self.subTest(user=user.email, item=item.title):
                patched = self.call(
                    user, "patch", f"files/{item.pk}/", {"title": "New"}
                )
                replaced = self.client.post(
                    f"/api/v1/files/{item.pk}/versions/",
                    {"file": SimpleUploadedFile("x.txt", b"x")},
                    headers=self.headers(user),
                )
                self.assertEqual(patched.status_code, 200 if allowed else 403)
                self.assertEqual(replaced.status_code, 201 if allowed else 403)
        theirs.refresh_from_db()
        self.assertEqual(theirs.title, "New")

    def test_replace_keeps_the_item_and_lists_the_versions_for_staff(self):
        fid = self.shared_file.pk
        response = self.client.post(
            f"/api/v1/files/{fid}/versions/",
            {"file": SimpleUploadedFile("shared-2.txt", b"Version two")},
            headers=self.headers(self.ada),
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["id"], fid)
        self.assertEqual(data["name"], "shared-2.txt")
        self.assertEqual(
            [v["name"] for v in data["versions"]], ["shared-2.txt", "shared.txt"]
        )
        old = data["versions"][1]
        self.assertFalse(old["is_current"])
        self.assertIn("/versions/", old["download_url"])
        listed = self.call(self.ada, "get", f"files/{fid}/versions/").json()
        self.assertEqual(len(listed), 2)
        # Clients get the current one only, and cannot list or fetch the rest
        client_data = self.call(self.cleo, "get", f"files/{fid}/").json()
        self.assertEqual([v["name"] for v in client_data["versions"]], ["shared-2.txt"])
        self.assertEqual(
            self.call(self.cleo, "get", f"files/{fid}/versions/").status_code, 403
        )
        old_path = f"files/{fid}/versions/{old['id']}/download/"
        self.assertEqual(
            b"".join(self.call(self.ada, "get", old_path).streaming_content), b"Plan"
        )
        self.assertEqual(self.call(self.cleo, "get", old_path).status_code, 403)

    def test_a_version_of_another_file_is_404(self):
        version = self.secret_file.upload.versions.get().pk
        path = f"files/{self.shared_file.pk}/versions/{version}/download/"
        self.assertEqual(self.call(self.ada, "get", path).status_code, 404)

    def test_comments_survive_replacing(self):
        fid = self.shared_file.pk
        self.call(self.cleo, "post", f"items/{fid}/comments/", {"content": "Nice"})
        self.client.post(
            f"/api/v1/files/{fid}/versions/",
            {"file": SimpleUploadedFile("v2.txt", b"2")},
            headers=self.headers(self.ada),
        )
        comments = self.call(self.cleo, "get", f"items/{fid}/comments/").json()
        self.assertEqual(len(comments["results"]), 1)

    def test_update(self):
        fid = self.secret_file.pk
        response = self.call(
            self.ada,
            "patch",
            f"files/{fid}/",
            {"title": "Renamed", "description": "Text"},
        )
        self.assertEqual(response.json()["title"], "Renamed")
        self.assertEqual(response.json()["description"], "Text")
        self.assertEqual(
            self.call(self.ada, "patch", f"files/{fid}/", {"title": ""}).status_code,
            400,
        )
        response = self.call(
            self.cleo, "patch", f"files/{self.shared_file.pk}/", {"title": "x"}
        )
        self.assertEqual(response.status_code, 403)

    def test_clients_replace_only_their_files(self):
        response = self.client.post(
            f"/api/v1/files/{self.shared_file.pk}/versions/",
            {"file": SimpleUploadedFile("x.txt", b"x")},
            headers=self.headers(self.cleo),
        )
        self.assertEqual(response.status_code, 403)

    def test_after_the_item_is_hidden_the_urls_stop_working(self):
        ops.set_visibility(self.shared_file, visible=False, actor=self.ada)
        for path in [
            f"files/{self.shared_file.pk}/",
            f"files/{self.shared_file.pk}/download/",
        ]:
            self.assertEqual(self.call(self.cleo, "get", path).status_code, 404)


class ReviewFixesAPITest(APIFixture, TestCase):
    def test_blank_titles_are_refused_when_patching(self):
        for path in [
            f"messages/{self.shared_message.pk}/",
            f"docs/{self.shared_doc.pk}/",
            f"files/{self.shared_file.pk}/",
        ]:
            for title in ["", "   "]:
                with self.subTest(path=path, title=title):
                    response = self.call(self.ada, "patch", path, {"title": title})
                    self.assertEqual(response.status_code, 400)

    def test_a_title_is_stripped_when_patching(self):
        response = self.call(
            self.ada, "patch", f"files/{self.shared_file.pk}/", {"title": " New "}
        )
        self.assertEqual(response.json()["title"], "New")

    def test_files_resolve_mentions_in_descriptions(self):
        response = self.client.post(
            f"/api/v1/projects/{self.project.pk}/files/",
            {
                "file": SimpleUploadedFile("n.txt", b"x"),
                "description": "Ask @bob@example.org",
                "notify": "nobody",
            },
            headers=self.headers(self.ada),
        )
        self.assertEqual(response.status_code, 201, response.content)
        mention = f"[@Bob](person:{self.bob.pk})"
        self.assertEqual(response.json()["description"], f"Ask {mention}")
        pk = response.json()["id"]
        self.assertTrue(Mention.objects.filter(item_id=pk, user=self.bob).exists())
        response = self.call(
            self.ada, "patch", f"files/{pk}/", {"description": "Then @Bob"}
        )
        self.assertEqual(response.json()["description"], f"Then {mention}")

    def test_a_doc_switch_inside_an_internal_folder_is_ignored(self):
        """The doc stays internal, so its text is written for staff"""
        response = self.call(
            self.ada,
            "post",
            f"projects/{self.project.pk}/docs/",
            {
                "title": "D",
                "content": "Hi @cleo@example.org",
                "parent_id": self.private.pk,
                "visible_to_clients": True,
                "notify": "nobody",
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertFalse(response.json()["visible_to_clients"])
        self.assertEqual(response.json()["content"], "Hi @cleo@example.org")

    def test_a_doc_in_a_visible_folder_is_written_for_clients(self):
        response = self.call(
            self.ada,
            "post",
            f"projects/{self.project.pk}/docs/",
            {
                "title": "D",
                "content": "Hi @cleo@example.org",
                "parent_id": self.public.pk,
                "notify": "nobody",
            },
        )
        self.assertTrue(response.json()["visible_to_clients"])
        self.assertIn(f"(person:{self.cleo.pk})", response.json()["content"])

    def test_conflict_messages_name_people_by_their_short_name(self):
        base = self.shared_doc.doc.versions.first().pk
        operations.update_doc(
            self.shared_doc, actor=self.bob, content="Bob was here", new_version=True
        )
        response = self.call(
            self.ada,
            "patch",
            f"docs/{self.shared_doc.pk}/",
            {"content": "x", "base_version": base},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "Bob saved a newer version.")
