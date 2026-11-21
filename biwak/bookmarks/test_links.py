from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from biwak import links
from biwak.accounts.models import APIToken
from biwak.audit.models import LoggedAction
from biwak.bookmarks import operations as ops
from biwak.bookmarks.models import Link
from biwak.bookmarks.test_bookmarks import BookmarkBase


class KindTest(SimpleTestCase):
    def test_kind_by_host(self):
        for url, kind in [
            ("https://www.figma.com/file/abc", "figma"),
            ("https://figma.com/", "figma"),
            ("https://github.com/example/repo/issues/1", "github"),
            ("https://gitlab.com/example/repo", "gitlab"),
            ("https://docs.google.com/document/d/1", "google_drive"),
            ("https://drive.google.com/drive/folders/1", "google_drive"),
            ("https://sub.github.com/x", "github"),
            ("https://notgithub.com/", "link"),
            ("https://github.com.example.org/", "link"),
            ("https://google.com/", "link"),
            ("https://staging.example.org/", "link"),
            ("HTTPS://GITHUB.COM/x", "github"),
            ("not a url", "link"),
        ]:
            with self.subTest(url=url):
                self.assertEqual(links.kind_for(url), kind)


class LinkTest(BookmarkBase):
    def setUp(self):
        super().setUp()
        self.link = ops.add_link(
            project=self.project, url="https://figma.com/file/1", created_by=self.ada
        )

    def test_operations(self):
        self.assertEqual(self.link.kind, "figma")
        self.assertEqual(self.link.title, "figma.com")
        second = ops.add_link(
            project=self.project,
            url=" https://github.com/example/repo ",
            title="Repository",
            visible=True,
            created_by=self.ada,
        )
        self.assertEqual(
            (second.kind, second.position, second.url),
            ("github", 2, "https://github.com/example/repo"),
        )
        ops.update_link(second, url="https://gitlab.com/x", title="")
        self.assertEqual((second.kind, second.title), ("gitlab", "gitlab.com"))
        ops.reorder_links(
            [second.pk, self.link.pk], user=self.ada, project=self.project
        )
        self.assertEqual(
            list(Link.objects.values_list("pk", flat=True)),
            [second.pk, self.link.pk],
        )
        ops.delete_link(second)
        self.assertEqual(Link.objects.count(), 1)

    def test_only_web_addresses(self):
        for url in ["javascript:alert(1)", "ftp://example.org/x", "not a url", ""]:
            with self.subTest(url=url), self.assertRaises(ValidationError):
                ops.add_link(project=self.project, url=url, created_by=self.ada)

    def test_visibility(self):
        internal = ops.add_link(
            project=self.project, url="https://example.org/a", created_by=self.ada
        )
        shown = ops.add_link(
            project=self.project,
            url="https://example.org/b",
            visible=True,
            created_by=self.ada,
        )
        staff = set(Link.objects.visible_to(self.ada))
        self.assertEqual(len(staff), 3)
        client = set(Link.objects.visible_to(self.cleo))
        self.assertEqual(client, {shown})
        self.assertNotIn(internal, client)
        # Projects clients aren't in
        from biwak.test_utils import project

        other = project("Other")
        ops.add_link(
            project=other,
            url="https://example.org/f",
            visible=True,
            created_by=self.ada,
        )
        self.assertEqual(set(Link.objects.visible_to(self.cleo)), {shown})

    def test_items_show_no_links(self):
        ops.add_link(
            project=self.project,
            url="https://github.com/example/repo",
            title="The project link",
            created_by=self.ada,
        )
        self.client.force_login(self.ada)
        for item in [self.todo, self.shared]:
            response = self.client.get(item.get_absolute_url())
            self.assertNotContains(response, "The project link")
            self.assertNotContains(response, "Add a link")
            self.assertEqual(
                self.client.post(
                    f"/items/{item.pk}/links/", {"url": "https://example.org/x"}
                ).status_code,
                404,
            )

    def test_pages_as_staff(self):
        self.client.force_login(self.ada)
        response = self.client.get(self.project.get_absolute_url())
        self.assertContains(response, "figma.com")
        self.assertContains(response, "bi-palette")
        self.assertContains(response, "Add a link")
        self.assertContains(response, "data-sortable-order")
        self.assertNotContains(response, "No links yet.")
        # After "Docs and files", in a list group of its own
        content = response.content.decode()
        self.assertLess(content.index("Docs and files"), content.index("Add a link"))
        self.assertLess(content.index("Add a link"), content.index("figma.com"))

        # The modal and its page
        url = f"/projects/{self.project.pk}/links/new/"
        self.assertContains(self.client.get(url), "<html")
        response = self.client.get(url, headers={"HX-Modal": "true"})
        self.assertNotContains(response, "<html")
        self.assertContains(response, 'name="url"')
        response = self.client.post(
            url,
            {
                "url": "https://example.org/docs",
                "title": "Docs",
                "visible_to_clients": "on",
            },
        )
        self.assertRedirects(response, self.project.get_absolute_url())
        added = Link.objects.get(title="Docs")
        self.assertTrue(added.visible_to_clients)
        # Edit, order, delete
        response = self.client.get(f"/links/{added.pk}/edit/")
        self.assertContains(response, "https://example.org/docs")
        response = self.client.post(
            f"/links/{added.pk}/edit/",
            {"url": "https://example.org/new", "title": "Docs 2"},
        )
        self.assertRedirects(response, self.project.get_absolute_url())
        added.refresh_from_db()
        self.assertEqual((added.title, added.visible_to_clients), ("Docs 2", False))
        ids = [added.pk, self.link.pk]
        self.client.post(f"/projects/{self.project.pk}/links/order/", {"links": ids})
        self.assertEqual(list(Link.objects.values_list("pk", flat=True)), ids)
        response = self.client.post(
            f"/projects/{self.project.pk}/links/order/", {"links": ids[:1]}
        )
        self.assertEqual(response.status_code, 400)
        self.client.post(f"/links/{added.pk}/delete/")
        self.assertFalse(Link.objects.filter(pk=added.pk).exists())
        self.client.post(f"/links/{self.link.pk}/delete/")
        response = self.client.get(self.project.get_absolute_url())
        self.assertContains(response, "No links yet.")
        self.assertContains(response, "Add a link")

    def test_bad_urls_in_forms(self):
        self.client.force_login(self.ada)
        response = self.client.post(
            f"/projects/{self.project.pk}/links/new/",
            {"url": "javascript:alert(1)"},
        )
        self.assertContains(response, "Enter a valid URL")
        self.assertEqual(Link.objects.count(), 1)
        response = self.client.post(
            f"/links/{self.link.pk}/edit/", {"url": "nope nope"}
        )
        self.assertContains(response, "Enter a valid URL")

    def test_pages_as_client(self):
        shown = ops.add_link(
            project=self.project,
            url="https://example.org/b",
            title="Shown",
            visible=True,
            created_by=self.ada,
        )
        self.client.force_login(self.cleo)
        response = self.client.get(self.project.get_absolute_url())
        self.assertContains(response, "Shown")
        self.assertNotContains(response, "figma.com")
        self.assertNotContains(response, "Add a link")
        self.assertNotContains(response, "data-sortable-order")
        self.assertNotContains(response, "No links yet.")
        # Can't change, can't even find the internal one
        self.assertEqual(self.client.get(f"/links/{shown.pk}/edit/").status_code, 403)
        self.assertEqual(
            self.client.post(f"/links/{shown.pk}/delete/").status_code, 403
        )
        self.assertEqual(
            self.client.get(f"/links/{self.link.pk}/edit/").status_code, 404
        )
        self.assertEqual(
            self.client.post(f"/links/{self.link.pk}/delete/").status_code, 404
        )
        url = f"/projects/{self.project.pk}/links/new/"
        self.assertEqual(self.client.get(url).status_code, 403)
        response = self.client.post(url, {"url": "https://example.org/x"})
        self.assertEqual(response.status_code, 403)
        response = self.client.post(
            f"/projects/{self.project.pk}/links/order/", {"links": [shown.pk]}
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Link.objects.count(), 2)

    def test_client_without_visible_links(self):
        self.client.force_login(self.cleo)
        response = self.client.get(self.project.get_absolute_url())
        self.assertContains(response, "No links yet.")
        self.assertNotContains(response, "figma.com")

    def test_audit_log(self):
        LoggedAction.objects.all().delete()
        ops.add_link(
            project=self.project, url="https://example.org/", created_by=self.ada
        )
        self.assertTrue(LoggedAction.objects.filter(table_name="bookmarks_link"))

    def api(self, method, path, user=None, data=None, access="write"):
        _token, secret = APIToken.create_for(
            user=user or self.ada, title="T", access=access
        )
        return getattr(self.client, method)(
            f"/api/v1/{path}",
            data,
            content_type="application/json",
            headers={"authorization": f"Bearer {secret}"},
        )

    def test_api(self):
        response = self.api(
            "post",
            f"projects/{self.project.pk}/links/",
            data={
                "url": "https://github.com/example/repo",
                "title": "Code",
                "visible_to_clients": True,
            },
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual((data["kind"], data["visible_to_clients"]), ("github", True))
        self.assertNotIn("item_id", data)
        # Links on items are gone
        self.assertEqual(
            self.api(
                "post",
                f"items/{self.secret.pk}/links/",
                data={"url": "https://example.org/"},
            ).status_code,
            404,
        )
        self.assertEqual(
            self.api(
                "post",
                f"projects/{self.project.pk}/links/",
                data={"url": "javascript:x"},
            ).status_code,
            400,
        )
        listed = self.api("get", f"projects/{self.project.pk}/links/").json()
        self.assertEqual([link["title"] for link in listed], ["figma.com", "Code"])

        patched = self.api(
            "patch",
            f"links/{data['id']}/",
            data={"title": "Repository", "visible_to_clients": False},
        )
        self.assertEqual(
            (patched.json()["title"], patched.json()["visible_to_clients"]),
            ("Repository", False),
        )
        ordered = self.api(
            "put",
            f"projects/{self.project.pk}/links/order/",
            data={"links": [data["id"], self.link.pk]},
        )
        self.assertEqual(
            [link["id"] for link in ordered.json()], [data["id"], self.link.pk]
        )
        self.assertEqual(
            self.api(
                "put",
                f"projects/{self.project.pk}/links/order/",
                data={"links": [data["id"]]},
            ).status_code,
            400,
        )
        self.assertEqual(
            self.api("delete", f"links/{data['id']}/").json()["id"], data["id"]
        )
        self.assertFalse(Link.objects.filter(pk=data["id"]).exists())

    def test_api_as_client_and_read_only(self):
        shown = ops.add_link(
            project=self.project,
            url="https://example.org/b",
            title="Shown",
            visible=True,
            created_by=self.ada,
        )
        listed = self.api(
            "get", f"projects/{self.project.pk}/links/", user=self.cleo
        ).json()
        self.assertEqual([link["id"] for link in listed], [shown.pk])
        for method, path, data in [
            (
                "post",
                f"projects/{self.project.pk}/links/",
                {"url": "https://example.org/x"},
            ),
            ("patch", f"links/{shown.pk}/", {"title": "No"}),
            ("delete", f"links/{shown.pk}/", None),
            ("put", f"projects/{self.project.pk}/links/order/", {"links": [shown.pk]}),
        ]:
            with self.subTest(path=path, method=method):
                response = self.api(method, path, user=self.cleo, data=data)
                self.assertEqual(response.status_code, 403)
        self.assertEqual(
            self.api(
                "patch", f"links/{self.link.pk}/", user=self.cleo, data={"title": "No"}
            ).status_code,
            404,
        )
        # A read-only token only reads
        response = self.api(
            "post",
            f"projects/{self.project.pk}/links/",
            data={"url": "https://example.org/x"},
            access="read",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Link.objects.count(), 2)
