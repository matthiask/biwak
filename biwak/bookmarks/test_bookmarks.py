from django.db import IntegrityError, transaction
from django.test import TestCase

from biwak.accounts.models import APIToken
from biwak.audit.models import LoggedAction
from biwak.bookmarks import operations as ops
from biwak.bookmarks.models import Bookmark
from biwak.items import operations as ops_items
from biwak.test_utils import person, project


class BookmarkBase(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.bob, self.cleo])
        self.internal = ops_items.create_list(
            project=self.project, title="Internal", creator=self.ada
        )
        self.shared = ops_items.create_list(
            project=self.project, title="Shared", creator=self.ada, visible=True
        )
        self.secret = ops_items.create_todo(
            todolist=self.internal, title="Secret", creator=self.ada
        )
        self.todo = ops_items.create_todo(
            todolist=self.shared, title="Open point", creator=self.ada
        )


class BookmarkTest(BookmarkBase):
    def test_operations(self):
        self.assertTrue(ops.add_bookmark(self.ada, item=self.todo))
        self.assertFalse(ops.add_bookmark(self.ada, item=self.todo))
        self.assertTrue(ops.add_bookmark(self.ada, project=self.project))
        self.assertTrue(ops.is_bookmarked(self.ada, item=self.todo))
        self.assertFalse(ops.is_bookmarked(self.bob, item=self.todo))
        self.assertTrue(ops.remove_bookmark(self.ada, item=self.todo))
        self.assertFalse(ops.remove_bookmark(self.ada, item=self.todo))
        with self.assertRaises(ValueError):
            ops.add_bookmark(self.ada)
        with self.assertRaises(ValueError):
            ops.add_bookmark(self.ada, item=self.todo, project=self.project)

    def test_constraints(self):
        for kwargs in [
            {},
            {"item": self.todo, "project": self.project},
        ]:
            with (
                self.subTest(kwargs=kwargs),
                self.assertRaises(IntegrityError),
                transaction.atomic(),
            ):
                Bookmark.objects.create(user=self.ada, **kwargs)
        Bookmark.objects.create(user=self.ada, item=self.todo)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Bookmark.objects.create(user=self.ada, item=self.todo)

    def test_pages(self):
        self.client.force_login(self.ada)
        url = f"/todos/{self.todo.pk}/"
        self.assertContains(self.client.get(url), 'bi-bookmark"')
        response = self.client.post(
            f"/items/{self.todo.pk}/bookmark/", {"bookmark": "1", "next": url}
        )
        self.assertRedirects(response, url)
        self.assertContains(self.client.get(url), "bi-bookmark-fill")
        self.client.post(f"/projects/{self.project.pk}/bookmark/", {"bookmark": "1"})
        response = self.client.get("/bookmarks/")
        self.assertContains(response, "Open point")
        self.assertContains(response, "Website")
        self.assertContains(response, "to-do · Website")
        self.client.post(f"/items/{self.todo.pk}/bookmark/")
        self.assertNotContains(self.client.get("/bookmarks/"), "Open point")
        # Private
        ops.add_bookmark(self.ada, item=self.shared)
        self.client.force_login(self.bob)
        self.assertNotContains(self.client.get("/bookmarks/"), "Shared")

    def test_bookmarks_of_what_became_invisible_are_hidden(self):
        ops.add_bookmark(self.cleo, item=self.todo)
        ops.add_bookmark(self.cleo, project=self.project)
        self.client.force_login(self.cleo)
        self.assertContains(self.client.get("/bookmarks/"), "Open point")
        # Switched off, trashed, and removed from the project
        ops_items.set_visibility(self.shared, visible=False, actor=self.ada)
        self.assertNotContains(self.client.get("/bookmarks/"), "Open point")
        self.assertContains(self.client.get("/bookmarks/"), "Website")
        ops_items.set_visibility(self.shared, visible=True, actor=self.ada)
        self.assertContains(self.client.get("/bookmarks/"), "Open point")
        ops_items.trash(self.todo, actor=self.ada)
        self.assertNotContains(self.client.get("/bookmarks/"), "Open point")
        ops_items.restore(self.todo, actor=self.ada)
        from biwak.projects import operations as project_ops

        project_ops.remove_member(self.project, self.cleo, actor=self.ada)
        self.assertNotContains(self.client.get("/bookmarks/"), "Website")
        # Not deleted: back when they see it again
        self.assertEqual(Bookmark.objects.filter(user=self.cleo).count(), 2)
        project_ops.add_member(self.project, self.cleo, actor=self.ada)
        self.assertContains(self.client.get("/bookmarks/"), "Open point")

    def test_cant_bookmark_what_you_cant_see(self):
        self.client.force_login(self.cleo)
        response = self.client.post(
            f"/items/{self.secret.pk}/bookmark/", {"bookmark": "1"}
        )
        self.assertEqual(response.status_code, 404)
        hidden = project("Hidden", members=[self.bob], all_access=False)
        response = self.client.post(
            f"/projects/{hidden.pk}/bookmark/", {"bookmark": "1"}
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Bookmark.objects.exists())

    def test_audit_log(self):
        LoggedAction.objects.all().delete()
        ops.add_bookmark(self.ada, item=self.todo)
        self.assertTrue(
            LoggedAction.objects.filter(table_name="bookmarks_bookmark", action="I")
        )

    def test_api(self):
        def call(method, path, user=self.ada, data=None):
            _token, secret = APIToken.create_for(user=user, title="T", access="write")
            return getattr(self.client, method)(
                f"/api/v1/{path}",
                data,
                content_type="application/json",
                headers={"authorization": f"Bearer {secret}"},
            )

        self.assertEqual(
            call("put", f"items/{self.todo.pk}/bookmark/").json(), {"bookmarked": True}
        )
        call("put", f"projects/{self.project.pk}/bookmark/")
        data = call("get", "bookmarks/").json()
        self.assertEqual([b["project"] is not None for b in data], [True, False])
        self.assertEqual(data[1]["item"]["title"], "Open point")
        self.assertTrue(data[1]["item"]["visible_to_clients"])
        self.assertEqual(
            call("delete", f"items/{self.todo.pk}/bookmark/").json(),
            {"bookmarked": False},
        )
        self.assertEqual(len(call("get", "bookmarks/").json()), 1)
        # What you can't see isn't there
        response = call("put", f"items/{self.secret.pk}/bookmark/", user=self.cleo)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(call("get", "bookmarks/", user=self.cleo).json(), [])
