import html
import io
import re
from unittest.mock import patch
from urllib.parse import parse_qs, quote, urlsplit

import boto3
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from moto import mock_aws
from PIL import Image

from biwak.accounts.models import NotificationLevel
from biwak.activity.models import Action, Event
from biwak.files import attachments, operations, previews
from biwak.files.models import preview_name
from biwak.items import operations as ops, visibility
from biwak.items.models import Folder, Item, Kind
from biwak.projects import operations as project_ops
from biwak.test_utils import (
    assert_modal,
    assert_modal_redirect,
    assert_page,
    organization,
    person,
    project,
)


def png(width=800, height=400, color="red"):
    out = io.BytesIO()
    Image.new("RGB", (width, height), color).save(out, "PNG")
    return out.getvalue()


def pdf():
    import pypdfium2

    document = pypdfium2.PdfDocument.new()
    document.new_page(300, 600)
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def file(name="plan.txt", content=b"Plan"):
    return ContentFile(content, name=name)


def read(response):
    """The body of a response, closing a streamed file"""
    if response.streaming:
        return b"".join(response.streaming_content)
    return response.content


class Fixture:
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.bob, self.cleo])
        self.public = ops.create_folder(
            project=self.project, title="Public", creator=self.ada, visible=True
        )
        self.private = ops.create_folder(
            project=self.project, title="Private", creator=self.ada
        )
        self.shared_file = self.upload("shared.txt", parent=self.public)
        self.secret_file = self.upload("secret.txt", parent=self.private)
        self.root_shared = self.upload("root-shared.txt", visible=True)
        self.root_secret = self.upload("root-secret.txt")

    def upload(self, name, *, content=b"Plan", **kwargs):
        return ops.create_upload(
            project=self.project,
            file=file(name, content),
            creator=self.ada,
            **kwargs,
        )

    def get(self, user, url, **kwargs):
        self.client.force_login(user)
        response = self.client.get(url, **kwargs)
        read(response)
        return response


class LibraryTest(Fixture, TestCase):
    def root(self):
        return reverse("project_files", args=[self.project.pk])

    def names(self, response):
        return [row.title for row in response.context["rows"]]

    def test_staff_sees_everything_folders_first_then_by_title(self):
        ops.create_doc(project=self.project, title="a doc", creator=self.ada)
        response = self.get(self.ada, self.root())
        self.assertEqual(
            self.names(response),
            ["Private", "Public", "a doc", "root-secret.txt", "root-shared.txt"],
        )

    def test_a_client_sees_what_is_visible(self):
        response = self.get(self.cleo, self.root())
        self.assertEqual(self.names(response), ["Public", "root-shared.txt"])
        self.assertNotContains(response, "Private")
        self.assertNotContains(response, "root-secret")
        self.assertContains(response, "Clients")  # the badge

    def test_inside_a_folder(self):
        response = self.get(self.ada, self.public.get_absolute_url())
        self.assertEqual(self.names(response), ["shared.txt"])
        self.assertContains(response, "Clients can see this")
        response = self.get(self.cleo, self.public.get_absolute_url())
        self.assertEqual(self.names(response), ["shared.txt"])

    def test_a_client_gets_404_for_an_internal_folder(self):
        self.assertEqual(
            self.get(self.cleo, self.private.get_absolute_url()).status_code, 404
        )
        self.client.force_login(self.cleo)
        self.assertEqual(
            self.client.post(
                self.private.get_absolute_url(), {"title": "x"}
            ).status_code,
            404,
        )
        self.assertFalse(Item.objects.filter(title="x").exists())

    def test_breadcrumbs(self):
        inner = ops.create_folder(
            project=self.project, title="Inner", creator=self.ada, parent=self.public
        )
        response = self.get(self.cleo, inner.get_absolute_url())
        self.assertEqual(
            [c.title for c in response.context["breadcrumbs"]], ["Public", "Inner"]
        )
        self.assertContains(response, self.public.get_absolute_url())

    def test_tiles_with_up_to_the_parent(self):
        """A grid of tiles; inside a folder ".." leads to the folder above,
        from a first-level folder to the project's top level
        (specs/files.md, "Folders")"""
        inner = ops.create_folder(
            project=self.project, title="Inner", creator=self.ada, parent=self.public
        )
        response = self.get(self.ada, self.root())
        self.assertNotContains(response, "wb-tile-up")
        self.assertContains(response, 'class="wb-tile wb-tile-folder"', count=2)
        self.assertContains(response, 'class="wb-tile wb-tile-file"', count=2)
        response = self.get(self.cleo, self.public.get_absolute_url())
        self.assertEqual(response.context["up_url"], self.root())
        self.assertContains(response, "wb-tile-up")
        self.assertContains(response, 'data-drop-folder=""')
        response = self.get(self.cleo, inner.get_absolute_url())
        self.assertEqual(response.context["up_url"], self.public.get_absolute_url())
        self.assertContains(response, f'data-drop-folder="{self.public.pk}"')
        self.assertContains(response, "Nothing here yet.")

    def test_tiles_show_previews_of_images_sizes_and_checklists(self):
        image = self.upload("photo.png", content=png(), parent=self.private)
        ops.create_doc(
            project=self.project,
            title="Tasks",
            content="- [x] one\n- [ ] two",
            creator=self.ada,
            parent=self.private,
        )
        response = self.get(self.ada, self.private.get_absolute_url())
        self.assertContains(response, reverse("file_preview", args=[image.pk]))
        self.assertContains(response, "1/2")
        self.assertContains(response, "4\xa0bytes")  # secret.txt
        # Only images have a preview
        self.assertNotContains(
            response, reverse("file_preview", args=[self.secret_file.pk])
        )

    def test_ordering(self):
        """Stored on the folder, the project's for the top level; folders
        first, in the same order (specs/files.md, "Folders")"""
        ops.create_folder(project=self.project, title="Archive", creator=self.ada)
        names = lambda: self.names(self.get(self.ada, self.root()))  # noqa: E731
        self.assertEqual(
            names(),
            ["Archive", "Private", "Public", "root-secret.txt", "root-shared.txt"],
        )
        url = reverse("project_files_order", args=[self.project.pk])
        self.client.force_login(self.ada)
        response = self.client.get(url, headers={"HX-Modal": "true"})
        assert_modal(self, response, title="Order…")
        self.assertContains(
            response,
            'value="alphabetical" class="form-check-input" id="id_ordering_0" required checked',
        )
        response = self.client.post(
            url, {"ordering": "reverse"}, headers={"HX-Modal": "true"}
        )
        assert_modal_redirect(self, response, self.root())
        self.assertEqual(
            names(),
            ["Public", "Private", "Archive", "root-shared.txt", "root-secret.txt"],
        )
        self.client.post(url, {"ordering": "newest"})
        self.assertEqual(
            names(),
            ["Archive", "Private", "Public", "root-secret.txt", "root-shared.txt"],
        )
        self.client.post(url, {"ordering": "oldest"})
        self.assertEqual(
            names(),
            ["Public", "Private", "Archive", "root-shared.txt", "root-secret.txt"],
        )
        # A folder has its own, everybody sees it; no event
        self.upload("a.txt", parent=self.public)
        url = reverse("folder_order", args=[self.public.pk])
        self.client.post(url, {"ordering": "reverse"})
        self.assertEqual(
            self.names(self.get(self.cleo, self.public.get_absolute_url())),
            ["shared.txt", "a.txt"],
        )
        self.assertEqual(Folder.objects.get(pk=self.public.pk).ordering, "reverse")
        self.assertFalse(
            Event.objects
            .filter(item=self.public)
            .exclude(action=Action.CREATED)
            .exists()
        )
        # The menus offer it
        self.assertContains(
            self.get(self.ada, self.root()),
            reverse("project_files_order", args=[self.project.pk]),
        )
        self.assertContains(self.get(self.ada, self.public.get_absolute_url()), url)

    def test_clients_dont_order(self):
        self.client.force_login(self.cleo)
        for url in [
            reverse("project_files_order", args=[self.project.pk]),
            reverse("folder_order", args=[self.public.pk]),
        ]:
            with self.subTest(url=url):
                self.assertEqual(
                    self.client.post(url, {"ordering": "newest"}).status_code, 403
                )
        url = reverse("folder_order", args=[self.private.pk])
        self.assertEqual(self.client.post(url, {"ordering": "newest"}).status_code, 404)
        self.project.refresh_from_db()
        self.assertEqual(self.project.files_ordering, "alphabetical")
        self.assertNotContains(self.get(self.cleo, self.root()), "Order…")
        self.assertNotContains(
            self.get(self.cleo, self.public.get_absolute_url()), "Order…"
        )

    def test_non_members_get_404(self):
        outsider = person("Dan", client=True)
        self.assertEqual(self.get(outsider, self.root()).status_code, 404)
        self.assertEqual(
            self.get(outsider, self.public.get_absolute_url()).status_code, 404
        )

    def test_the_trash_is_left_out(self):
        ops.trash(self.root_shared, actor=self.ada)
        ops.trash(self.public, actor=self.ada)
        self.assertEqual(self.names(self.get(self.cleo, self.root())), [])
        self.assertEqual(
            self.get(self.cleo, self.public.get_absolute_url()).status_code, 404
        )
        self.assertEqual(
            self.get(self.cleo, self.shared_file.get_absolute_url()).status_code, 404
        )

    def new_folder_url(self, folder=None):
        url = reverse("folder_new", args=[self.project.pk])
        return f"{url}?folder={folder.pk}" if folder else url

    def test_creating_folders(self):
        """Through a modal (specs/files.md, "Folders"), also a page"""
        self.client.force_login(self.ada)
        response = self.client.get(self.new_folder_url(), headers={"HX-Modal": "true"})
        assert_modal(self, response, title="New folder")
        self.assertContains(response, "Visible to clients")
        # The switch only at the top level
        response = self.client.get(self.new_folder_url(self.private))
        assert_page(self, response, title="New folder")
        self.assertNotContains(response, "Visible to clients")
        response = self.client.post(
            self.new_folder_url(),
            {"title": "Staff folder"},
            headers={"HX-Modal": "true"},
        )
        staff_folder = Item.objects.get(title="Staff folder")
        assert_modal_redirect(self, response, staff_folder.get_absolute_url())
        self.client.post(self.new_folder_url(), {"title": "Shown", "visible": "on"})
        self.client.post(
            self.new_folder_url(self.private), {"title": "Nested", "visible": "on"}
        )
        folders = {i.title: i for i in Item.objects.filter(kind=Kind.FOLDER)}
        self.assertFalse(folders["Staff folder"].is_client_visible)
        self.assertTrue(folders["Shown"].is_client_visible)
        self.assertEqual(folders["Nested"].parent, self.private)
        self.assertFalse(folders["Nested"].visible_to_clients)
        # Errors stay in the dialog
        response = self.client.post(
            self.new_folder_url(), {"title": " "}, headers={"HX-Modal": "true"}
        )
        assert_modal(self, response, title="New folder")
        # The button in the header opens it
        response = self.client.get(self.private.get_absolute_url())
        self.assertContains(response, f'href="{self.new_folder_url(self.private)}"')

    def test_renaming_a_folder(self):
        url = reverse("folder_edit", args=[self.public.pk])
        self.client.force_login(self.ada)
        response = self.client.get(self.public.get_absolute_url())
        self.assertContains(response, f'href="{url}"')
        response = self.client.get(url, headers={"HX-Modal": "true"})
        assert_modal(self, response, title="Edit…")
        self.assertContains(response, 'value="Public"')
        response = self.client.post(
            url, {"title": "Shared"}, headers={"HX-Modal": "true"}
        )
        assert_modal_redirect(self, response, self.public.get_absolute_url())
        self.public.refresh_from_db()
        self.assertEqual(self.public.title, "Shared")
        self.assertTrue(
            Event.objects.filter(item=self.public, action=Action.EDITED).exists()
        )

    def test_folder_colors_through_the_modals(self):
        """No color unless chosen; the tile and the header carry it"""
        self.client.force_login(self.ada)
        url = reverse("folder_new", args=[self.project.pk])
        response = self.client.get(url, headers={"HX-Modal": "true"})
        self.assertContains(response, "wb-color-picker")
        self.assertContains(response, "checked", count=1)  # None
        self.client.post(url, {"title": "Plain"})
        self.client.post(url, {"title": "Tinted", "color": "lake"})
        folders = {i.title: i for i in Item.objects.filter(kind=Kind.FOLDER)}
        self.assertEqual(folders["Plain"].folder.color, "")
        self.assertEqual(folders["Tinted"].folder.color, "lake")
        response = self.client.post(url, {"title": "Bad", "color": "amber"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Item.objects.filter(title="Bad").exists())
        # The grid: only the colored one is tinted
        response = self.client.get(reverse("project_files", args=[self.project.pk]))
        self.assertContains(response, 'data-folder-color="lake"', count=1)
        self.assertRegex(
            self.client.get(folders["Tinted"].get_absolute_url()).content.decode(),
            r'class="wb-folder-icon"\s+data-folder-color="lake"',
        )
        # No color is neutral grey, not the accent (main.css)
        response = self.client.get(folders["Plain"].get_absolute_url())
        self.assertNotContains(response, "data-folder-color")
        self.assertContains(response, 'class="wb-folder-icon"')
        # Edit: the color alone, no event, then none again
        edit = reverse("folder_edit", args=[folders["Plain"].pk])
        response = self.client.get(edit, headers={"HX-Modal": "true"})
        self.assertContains(response, 'value="Plain"')
        before = Event.objects.filter(item=folders["Plain"], action=Action.EDITED)
        response = self.client.post(
            edit, {"title": "Plain", "color": "ember"}, headers={"HX-Modal": "true"}
        )
        assert_modal_redirect(self, response, folders["Plain"].get_absolute_url())
        self.assertEqual(Folder.objects.get(pk=folders["Plain"].pk).color, "ember")
        self.assertFalse(before.exists())
        response = self.client.get(edit, headers={"HX-Modal": "true"})
        self.assertRegex(
            response.content.decode(), r"value=\"ember\"\s+id=\"id_color_5\"\s+checked"
        )
        self.client.post(edit, {"title": "Plain", "color": ""})
        self.assertEqual(Folder.objects.get(pk=folders["Plain"].pk).color, "")

    def test_clients_dont_color_folders(self):
        url = reverse("folder_edit", args=[self.public.pk])
        self.client.force_login(self.cleo)
        self.assertEqual(
            self.client.post(url, {"title": "Public", "color": "lake"}).status_code,
            403,
        )
        url = reverse("folder_edit", args=[self.private.pk])
        self.assertEqual(
            self.client.post(url, {"title": "Private", "color": "lake"}).status_code,
            404,
        )
        self.assertFalse(Folder.objects.exclude(color="").exists())
        # They see what staff chose
        Folder.objects.filter(pk=self.public.pk).update(color="forest")
        response = self.client.get(self.public.get_absolute_url())
        self.assertContains(response, 'data-folder-color="forest"')

    def test_clients_dont_rename_folders(self):
        url = reverse("folder_edit", args=[self.public.pk])
        self.client.force_login(self.cleo)
        self.assertNotContains(self.client.get(self.public.get_absolute_url()), url)
        self.assertEqual(self.client.post(url, {"title": "Mine"}).status_code, 403)
        url = reverse("folder_edit", args=[self.private.pk])
        self.assertEqual(self.client.post(url, {"title": "Mine"}).status_code, 404)
        self.assertFalse(Item.objects.filter(title="Mine").exists())

    def test_clients_dont_create_folders_docs_or_files(self):
        """Clients create to-dos, comments and messages, not folders, docs
        or files (specs/access.md)"""
        self.client.force_login(self.cleo)
        for folder in [None, self.public]:
            with self.subTest(folder=folder):
                url = self.new_folder_url(folder)
                response = self.client.post(url, {"title": "Client folder"})
                self.assertEqual(response.status_code, 403)
                response = self.client.get(
                    folder.get_absolute_url() if folder else self.root()
                )
                self.assertNotContains(response, "New folder")
                self.assertNotContains(response, "New doc")
                self.assertNotContains(response, "Upload files")
        # A folder clients don't see: 404 first
        response = self.client.post(
            self.new_folder_url(self.private), {"title": "Client folder"}
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Item.objects.filter(title="Client folder").exists())
        self.client.force_login(self.ada)
        response = self.client.get(self.root())
        self.assertContains(response, "New folder")
        self.assertContains(response, "New doc")
        self.assertContains(response, "Upload files")

    def test_the_switch(self):
        self.client.force_login(self.ada)
        url = reverse("switch", args=[self.private.pk])
        response = self.client.get(self.private.get_absolute_url())
        self.assertContains(response, "Show to clients")
        response = self.client.get(url)
        self.assertContains(response, "Show this folder to clients?")
        self.assertContains(response, "items below it")
        self.assertContains(response, "visible to 1 client.")
        self.client.post(url, {"visible": "1"})
        self.private.refresh_from_db()
        self.secret_file.refresh_from_db()
        self.assertTrue(self.secret_file.is_client_visible)
        self.assertEqual(visibility.check(), [])
        self.client.force_login(self.cleo)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.assertContains(
            self.client.get(self.secret_file.get_absolute_url()), "secret.txt"
        )
        # Nested folders have no switch
        nested = ops.create_folder(
            project=self.project, title="Nested", creator=self.ada, parent=self.public
        )
        self.client.force_login(self.ada)
        self.assertNotContains(
            self.client.get(nested.get_absolute_url()), "Hide from clients"
        )

    def test_hiding_hides_the_files_again(self):
        self.client.force_login(self.ada)
        self.client.post(reverse("switch", args=[self.public.pk]))
        self.assertEqual(
            self.get(self.cleo, self.shared_file.get_absolute_url()).status_code, 404
        )
        self.assertEqual(
            self.get(
                self.cleo, reverse("file_download", args=[self.shared_file.pk])
            ).status_code,
            404,
        )


class TileMenuTest(Fixture, TestCase):
    """Each tile's "…" menu offers what the item's own "More" menu does,
    its modals coming back to the grid (specs/files.md, "Folders")"""

    def menus(self, user, url):
        """{item pk: the menu's entries as {label: href}}"""
        response = self.get(user, url)
        self.assertEqual(response.status_code, 200)
        menus = {}
        for tile in response.content.decode().split("<li>")[1:]:
            pk = re.search(r'data-tile="(\d+)"', tile)
            if pk is None:  # ".."
                self.assertNotIn("wb-tile-menu", tile)
                continue
            menu = tile.split('class="dropdown wb-menu wb-tile-menu"')[1]
            menus[int(pk[1])] = {
                label: html.unescape(href)
                for href, label in re.findall(
                    r'class="dropdown-item"\s+href="([^"]+)"\s+data-modal\s*>([^<]+)<',
                    menu,
                )
            }
        return menus

    def test_staff_get_what_the_items_pages_offer(self):
        doc = ops.create_doc(project=self.project, title="Brief", creator=self.ada)
        root = reverse("project_files", args=[self.project.pk])
        menus = self.menus(self.bob, root)
        self.assertEqual(
            set(menus),
            {self.public.pk, self.private.pk, doc.pk, self.root_shared.pk}
            | {self.root_secret.pk},
        )
        back = "?next=" + quote(root)
        self.assertEqual(
            menus[self.public.pk],
            {
                "Subscribers…": reverse("item_subscribers", args=[self.public.pk])
                + back,
                "Edit…": reverse("folder_edit", args=[self.public.pk]) + back,
                "Order…": reverse("folder_order", args=[self.public.pk]) + back,
                "Move to…": reverse("item_move", args=[self.public.pk]) + back,
                "Trash": reverse("item_trash", args=[self.public.pk]) + back,
            },
        )
        for item in [doc, self.root_secret]:
            self.assertEqual(
                menus[item.pk],
                {
                    "Subscribers…": reverse("item_subscribers", args=[item.pk]) + back,
                    "Move to…": reverse("item_move", args=[item.pk]) + back,
                    "Trash": reverse("item_trash", args=[item.pk]) + back,
                },
            )
        # The same entries as on the item's page
        page = self.get(self.bob, doc.get_absolute_url()).content.decode()
        for href in menus[doc.pk].values():
            self.assertIn(href.split("?")[0], page)

    def test_clients_get_what_they_may_do(self):
        mine = ops.create_doc(
            project=self.project, title="Notes", creator=self.cleo, parent=self.public
        )
        url = self.public.get_absolute_url()
        menus = self.menus(self.cleo, url)
        self.assertEqual(set(menus), {self.shared_file.pk, mine.pk})
        back = "?next=" + quote(url)
        # Staff's file: only the subscribers
        self.assertEqual(
            list(menus[self.shared_file.pk]),
            ["Subscribers…"],
        )
        # Their own doc: moving and trashing too
        self.assertEqual(
            menus[mine.pk],
            {
                "Subscribers…": reverse("item_subscribers", args=[mine.pk]) + back,
                "Move to…": reverse("item_move", args=[mine.pk]) + back,
                "Trash": reverse("item_trash", args=[mine.pk]) + back,
            },
        )
        # A folder: no editing, no ordering, at the top level
        menus = self.menus(self.cleo, reverse("project_files", args=[self.project.pk]))
        self.assertEqual(list(menus[self.public.pk]), ["Subscribers…"])
        self.assertNotIn(self.private.pk, menus)

    def test_the_modals_come_back_to_the_grid(self):
        root = reverse("project_files", args=[self.project.pk])
        back = {"next": root}
        self.client.force_login(self.ada)
        modal = {"HX-Modal": "true"}
        url = reverse("folder_edit", args=[self.public.pk])
        response = self.client.get(url, back)
        self.assertContains(response, f'href="{root}" class="btn btn-quiet"')
        response = self.client.post(
            f"{url}?next={root}", {"title": "Shared"}, headers=modal
        )
        assert_modal_redirect(self, response, root)
        response = self.client.post(
            f"{reverse('item_move', args=[self.root_secret.pk])}?next={root}",
            {"folder": self.private.pk},
            headers=modal,
        )
        assert_modal_redirect(self, response, root)
        response = self.client.post(
            f"{reverse('folder_order', args=[self.public.pk])}?next={root}",
            {"ordering": "newest"},
            headers=modal,
        )
        assert_modal_redirect(self, response, root)
        response = self.client.post(
            f"{reverse('item_subscribers', args=[self.public.pk])}?next={root}",
            {"people": [self.bob.pk]},
            headers=modal,
        )
        assert_modal_redirect(self, response, root)
        response = self.client.post(
            f"{reverse('item_trash', args=[self.root_shared.pk])}?next={root}",
            headers=modal,
        )
        assert_modal_redirect(self, response, root)
        # Not elsewhere
        response = self.client.post(
            f"{reverse('item_trash', args=[self.private.pk])}?next=https://example.com/",
            headers=modal,
        )
        assert_modal_redirect(self, response, self.project.get_absolute_url())


class MoveTest(Fixture, TestCase):
    def move(self, user, item, folder):
        self.client.force_login(user)
        return self.client.post(
            reverse("item_move", args=[item.pk]),
            {"folder": folder.pk if folder else ""},
        )

    def test_a_folder_that_is_no_number_answers_404(self):
        self.client.force_login(self.ada)
        for folder in ["x", "1.5", "-1"]:
            with self.subTest(folder=folder):
                response = self.client.post(
                    reverse("item_move", args=[self.root_secret.pk]),
                    {"folder": folder},
                )
                self.assertEqual(response.status_code, 404)

    def test_moving_a_file_between_folders_changes_its_visibility(self):
        response = self.move(self.ada, self.secret_file, self.public)
        self.assertRedirects(response, self.secret_file.get_absolute_url())
        self.secret_file.refresh_from_db()
        self.assertEqual(self.secret_file.parent, self.public)
        self.assertTrue(self.secret_file.is_client_visible)
        self.assertEqual(
            self.get(self.cleo, self.secret_file.get_absolute_url()).status_code, 200
        )
        self.move(self.ada, self.secret_file, self.private)
        self.assertEqual(
            self.get(self.cleo, self.secret_file.get_absolute_url()).status_code, 404
        )
        self.assertEqual(visibility.check(), [])

    def test_moving_a_folder_moves_the_contents_visibility(self):
        self.move(self.ada, self.private, self.public)
        self.secret_file.refresh_from_db()
        self.assertTrue(self.secret_file.is_client_visible)
        self.move(self.ada, self.private, None)
        self.secret_file.refresh_from_db()
        self.assertFalse(self.secret_file.is_client_visible)
        self.assertEqual(visibility.check(), [])

    def test_to_the_root(self):
        self.move(self.ada, self.shared_file, None)
        self.shared_file.refresh_from_db()
        self.assertIsNone(self.shared_file.parent)
        # At the top level the switch rules, and it's off
        self.assertFalse(self.shared_file.is_client_visible)

    def test_a_folder_cannot_go_into_itself(self):
        inner = ops.create_folder(
            project=self.project, title="Inner", creator=self.ada, parent=self.private
        )
        self.move(self.ada, self.private, inner)
        self.private.refresh_from_db()
        self.assertIsNone(self.private.parent)

    def test_clients_cannot_move_into_folders_they_do_not_see(self):
        mine = ops.create_upload(
            project=self.project,
            file=file("mine.txt"),
            creator=self.cleo,
            parent=self.public,
        )
        self.assertEqual(self.move(self.cleo, mine, self.private).status_code, 404)
        mine.refresh_from_db()
        self.assertEqual(mine.parent, self.public)

    def test_clients_move_only_what_they_created(self):
        self.assertEqual(self.move(self.cleo, self.shared_file, None).status_code, 403)
        mine = ops.create_upload(
            project=self.project,
            file=file("mine.txt"),
            creator=self.cleo,
            parent=self.public,
        )
        other = ops.create_folder(
            project=self.project, title="Other", creator=self.ada, visible=True
        )
        self.assertEqual(self.move(self.cleo, mine, other).status_code, 302)

    def test_not_what_clients_cannot_see(self):
        self.assertEqual(
            self.move(self.cleo, self.secret_file, self.public).status_code, 404
        )

    def test_only_folders_docs_and_files_move(self):
        message = ops.create_message(project=self.project, title="Hi", creator=self.ada)
        self.assertEqual(self.move(self.ada, message, self.public).status_code, 403)

    def test_into_another_project(self):
        other = project("Other", members=[self.ada])
        folder = ops.create_folder(project=other, title="Elsewhere", creator=self.ada)
        self.assertEqual(self.move(self.ada, self.shared_file, folder).status_code, 404)

    def test_the_form_lists_folders_the_person_sees(self):
        response = self.get(self.ada, self.shared_file.get_absolute_url())
        self.assertEqual(
            [path for _folder, path in response.context["move_choices"]],
            ["Private", "Public"],
        )
        response = self.get(self.cleo, self.root_shared.get_absolute_url())
        self.assertEqual(
            [path for _folder, path in response.context["move_choices"]], ["Public"]
        )

    def root(self):
        return reverse("project_files", args=[self.project.pk])


class MoveSeveralTest(Fixture, TestCase):
    """Moving and trashing a selection, dragging onto folders
    (specs/files.md, "Moving and selecting"): the operation of "Move to…" for each"""

    def setUp(self):
        super().setUp()
        self.move_url = reverse("files_move", args=[self.project.pk])
        self.trash_url = reverse("files_trash", args=[self.project.pk])

    def items(self, *items):
        return "&".join(f"items={item.pk}" for item in items)

    def test_the_tiles_offer_it(self):
        self.client.force_login(self.ada)
        response = self.client.get(reverse("project_files", args=[self.project.pk]))
        self.assertContains(response, f'data-tiles-move="{self.move_url}"')
        self.assertContains(response, "data-tile-movable", count=4)
        self.assertContains(response, "data-selection-bar")
        # Clients drag only what they may move
        self.client.force_login(self.cleo)
        response = self.client.get(reverse("project_files", args=[self.project.pk]))
        self.assertNotContains(response, "data-tile-movable")

    def test_dropping_onto_a_folder(self):
        self.client.force_login(self.ada)
        response = self.client.post(
            self.move_url,
            {
                "folder": self.public.pk,
                "items": [self.root_secret.pk, self.private.pk],
            },
        )
        self.assertRedirects(response, reverse("project_files", args=[self.project.pk]))
        for item in [self.root_secret, self.private, self.secret_file]:
            item.refresh_from_db()
            self.assertTrue(item.is_client_visible, item)
        self.assertEqual(self.private.parent, self.public)
        self.assertEqual(Event.objects.filter(action=Action.MOVED).count(), 2)
        # Back to the top level (an empty folder: "..", the breadcrumbs)
        response = self.client.post(
            self.move_url, {"folder": "", "items": [self.private.pk]}
        )
        self.assertRedirects(response, self.public.get_absolute_url())
        self.private.refresh_from_db()
        self.assertIsNone(self.private.parent)
        self.assertFalse(self.private.is_client_visible)

    def test_the_modal_of_the_selection(self):
        self.client.force_login(self.ada)
        url = f"{self.move_url}?{self.items(self.root_secret, self.private)}"
        response = self.client.get(url, headers={"HX-Modal": "true"})
        assert_modal(self, response, title="Move to…")
        self.assertContains(response, "2 items")
        # Not into a folder that is moved itself
        self.assertNotContains(response, f'value="{self.private.pk}"')
        self.assertContains(response, f'value="{self.public.pk}"')
        response = self.client.post(
            url, {"folder": self.public.pk}, headers={"HX-Modal": "true"}
        )
        assert_modal_redirect(
            self, response, reverse("project_files", args=[self.project.pk])
        )
        self.root_secret.refresh_from_db()
        self.assertEqual(self.root_secret.parent, self.public)
        # A folder into itself: the error, nothing moved
        response = self.client.post(
            f"{self.move_url}?{self.items(self.root_shared, self.private)}",
            {"folder": self.private.pk},
            headers={"HX-Modal": "true"},
        )
        self.assertContains(response, "A folder can&#x27;t be moved into itself.")
        self.root_shared.refresh_from_db()
        self.assertIsNone(self.root_shared.parent)

    def test_trashing_several(self):
        self.client.force_login(self.ada)
        url = f"{self.trash_url}?{self.items(self.private, self.secret_file)}"
        response = self.client.get(url, headers={"HX-Modal": "true"})
        assert_modal(self, response, title="Move to the trash?")
        self.assertContains(response, "2 items can be restored for 30 days.")
        response = self.client.post(url, headers={"HX-Modal": "true"})
        assert_modal_redirect(
            self, response, reverse("project_files", args=[self.project.pk])
        )
        self.private.refresh_from_db()
        self.secret_file.refresh_from_db()
        self.assertEqual(self.private.status, "trashed")
        # Trashed with its folder, restored with it
        self.assertEqual(self.secret_file.trashed_at, self.private.trashed_at)
        self.assertEqual(Event.objects.filter(action=Action.TRASHED).count(), 1)

    def test_clients_move_only_what_they_may(self):
        mine = ops.create_upload(
            project=self.project,
            file=file("mine.txt"),
            creator=self.cleo,
            parent=self.public,
        )
        inner = ops.create_folder(
            project=self.project, title="Inner", creator=self.ada, parent=self.public
        )
        self.client.force_login(self.cleo)
        response = self.client.get(self.public.get_absolute_url())
        self.assertContains(response, "data-tile-movable", count=1)
        # Their own file into a folder they see, not what staff made
        response = self.client.post(
            self.move_url, {"folder": inner.pk, "items": [mine.pk]}
        )
        self.assertEqual(response.status_code, 302)
        mine.refresh_from_db()
        self.assertEqual(mine.parent, inner)
        for items in [[self.shared_file.pk], [mine.pk, self.shared_file.pk]]:
            with self.subTest(items=items):
                response = self.client.post(
                    self.move_url, {"folder": "", "items": items}
                )
                self.assertEqual(response.status_code, 403)
                response = self.client.post(self.trash_url, {"items": items})
                self.assertEqual(response.status_code, 403)
        # Not into folders or with items they don't see
        response = self.client.post(
            self.move_url, {"folder": self.private.pk, "items": [mine.pk]}
        )
        self.assertEqual(response.status_code, 404)
        response = self.client.post(
            self.move_url, {"folder": inner.pk, "items": [self.secret_file.pk]}
        )
        self.assertEqual(response.status_code, 404)
        for item in [mine, self.shared_file, self.secret_file]:
            before = item.parent_id
            item.refresh_from_db()
            self.assertEqual(item.parent_id, before)
            self.assertEqual(item.status, "active")

    def test_nothing_or_nonsense_is_404(self):
        self.client.force_login(self.ada)
        for query in ["", "items=x", f"items={self.project.pk + 10**6}"]:
            with self.subTest(query=query):
                response = self.client.get(f"{self.move_url}?{query}")
                self.assertEqual(response.status_code, 404)
        other = project("Elsewhere", members=[self.ada])
        response = self.client.get(
            reverse("files_move", args=[other.pk]) + f"?items={self.private.pk}"
        )
        self.assertEqual(response.status_code, 404)


class UploadPageTest(Fixture, TestCase):
    """ "Upload files" (specs/files.md, "Uploading files"): a modal, also a page
    taking several files at once"""

    def url(self, folder=None):
        url = reverse("file_new", args=[self.project.pk])
        return f"{url}?folder={folder.pk}" if folder else url

    def test_who_is_told_follows_the_folder(self):
        """The line says who is told by default in the folder, "Also
        tell…" offers the others who see it (decided 2026-11-21)"""
        self.client.force_login(self.ada)
        for folder, line, offered in [
            (None, "Bob will be told.", set()),
            (self.private, "Bob will be told.", set()),
            (self.public, "Bob and Cleo will be told.", set()),
        ]:
            response = self.client.get(self.url(folder), headers={"HX-Modal": "true"})
            self.assertContains(response, line)
            self.assertEqual(
                set(response.context["form"].fields["also"].queryset), offered
            )
        self.bob.notification_level = NotificationLevel.CONCERNS_ME
        self.bob.save()
        response = self.client.get(self.url(self.public), headers={"HX-Modal": "true"})
        self.assertContains(response, "Cleo will be told.")
        self.assertEqual(
            set(response.context["form"].fields["also"].queryset), {self.bob}
        )

    def test_a_modal_and_a_page(self):
        self.client.force_login(self.ada)
        response = self.client.get(self.url(self.private), headers={"HX-Modal": "true"})
        assert_modal(self, response, title="Upload files")
        self.assertContains(response, 'enctype="multipart/form-data"')
        self.assertContains(response, "multiple")
        self.assertContains(
            response,
            f'data-upload="{reverse("file_upload", args=[self.project.pk])}'
            f'?folder={self.private.pk}"',
        )
        response = self.client.get(self.url())
        assert_page(self, response, title="Upload files")
        # The button on the folder's page opens it
        response = self.client.get(self.private.get_absolute_url())
        self.assertContains(response, "Upload files")
        self.assertContains(response, "data-tiles-upload")

    def test_the_form_in_a_visible_folder_has_the_client_banner(self):
        self.client.force_login(self.ada)
        self.assertContains(
            self.client.get(self.url(self.public)), "Clients can see this"
        )
        self.assertNotContains(
            self.client.get(self.url(self.private)), "Clients can see this"
        )
        self.assertNotContains(self.client.get(self.url()), "Clients can see this")

    def send(self, user, folder=None, **data):
        self.client.force_login(user)
        data = {
            "files": [SimpleUploadedFile("new.txt", b"New")],
        } | data
        return self.client.post(self.url(folder), data)

    def test_staff_uploads_into_the_root(self):
        response = self.send(self.ada)
        item = Item.objects.get(title="new.txt")
        self.assertRedirects(response, reverse("file", args=[item.pk]))
        self.assertFalse(item.is_client_visible)
        self.assertEqual(item.upload.versions.get().uploaded_by, self.ada)

    def test_several_at_once_are_a_batch(self):
        response = self.send(
            self.ada,
            folder=self.public,
            files=[
                SimpleUploadedFile("one.txt", b"1"),
                SimpleUploadedFile("two.txt", b"2"),
            ],
        )
        self.assertRedirects(response, self.public.get_absolute_url())
        events = Event.objects.filter(
            item__title__in=["one.txt", "two.txt"], action=Action.CREATED
        )
        self.assertEqual(len(events), 2)
        self.assertEqual(len({e.data["batch"] for e in events}), 1)
        self.assertTrue(all(e.item.is_client_visible for e in events))

    def test_staff_chooses_visibility_and_folder(self):
        self.send(self.ada, visible="on")
        self.assertTrue(Item.objects.get(title="new.txt").is_client_visible)
        self.send(
            self.ada,
            folder=self.private,
            files=[SimpleUploadedFile("in.txt", b"x")],
            visible="on",
        )
        item = Item.objects.get(title="in.txt")
        self.assertEqual(item.parent, self.private)
        self.assertFalse(item.is_client_visible)

    def test_clients_dont_upload_files(self):
        self.assertEqual(self.send(self.cleo, folder=self.public).status_code, 403)
        self.assertEqual(self.send(self.cleo).status_code, 403)
        self.assertEqual(self.get(self.cleo, self.url()).status_code, 403)
        self.assertFalse(Item.objects.filter(title="new.txt").exists())
        self.client.force_login(self.cleo)
        response = self.client.get(self.public.get_absolute_url())
        self.assertNotContains(response, "data-tiles-upload")

    def test_a_client_cannot_upload_into_an_internal_folder(self):
        response = self.send(self.cleo, folder=self.private)
        self.assertEqual(response.status_code, 404)
        self.assertFalse(Item.objects.filter(title="new.txt").exists())
        self.assertEqual(self.get(self.cleo, self.url(self.private)).status_code, 404)

    def test_notifying(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.send(self.ada, visible="on")
        item = Item.objects.get(title="new.txt")
        told = {n.user for n in Event.objects.get(item=item).notifications.all()}
        self.assertEqual(told, {self.bob, self.cleo})

    def test_too_large(self):
        big = SimpleUploadedFile("big.bin", b"xxxx")
        with patch.object(attachments, "MAX_SIZE", 3):
            response = self.send(self.ada, files=[big])
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Files can be at most")
        self.assertFalse(Item.objects.filter(title="big.bin").exists())
        # The others go up, the error is said
        with patch.object(attachments, "MAX_SIZE", 3):
            response = self.send(
                self.ada,
                files=[
                    SimpleUploadedFile("big.bin", b"xxxx"),
                    SimpleUploadedFile("ok.txt", b"ok"),
                ],
            )
        self.assertRedirects(
            response,
            reverse("project_files", args=[self.project.pk]),
            fetch_redirect_response=False,
        )
        self.assertTrue(Item.objects.filter(title="ok.txt").exists())
        self.assertFalse(Item.objects.filter(title="big.bin").exists())

    def test_no_file(self):
        self.client.force_login(self.ada)
        self.assertEqual(self.client.post(self.url(), {}).status_code, 200)

    def test_the_switch_only_at_the_top_level(self):
        self.assertContains(self.get(self.ada, self.url()), "Visible to clients")
        self.assertNotContains(
            self.get(self.ada, self.url(self.public)), "Visible to clients"
        )


class UploadOneTest(Fixture, TestCase):
    """One file of the modal's upload (frontend/upload.js)"""

    batch = "0123456789abcdef0123456789abcdef"

    def send(self, user, folder=None, **data):
        self.client.force_login(user)
        url = reverse("file_upload", args=[self.project.pk])
        if folder:
            url += f"?folder={folder.pk}"
        data = {
            "file": SimpleUploadedFile("minutes.pdf", b"%PDF"),
            "batch": self.batch,
        } | data
        return self.client.post(url, data)

    def test_the_name_keeps_its_extension(self):
        response = self.send(self.ada, folder=self.public, title="Kick-off")
        self.assertEqual(response.status_code, 201)
        item = Item.objects.get(pk=response.json()["id"])
        self.assertEqual(item.title, "Kick-off.pdf")
        self.assertEqual(response.json()["url"], item.get_absolute_url())
        self.assertEqual(item.parent, self.public)
        self.assertTrue(item.is_client_visible)
        event = Event.objects.get(item=item, action=Action.CREATED)
        self.assertEqual(event.data["batch"], self.batch)
        response = self.send(self.ada, title="Agenda.PDF")
        self.assertEqual(response.json()["title"], "Agenda.PDF")
        response = self.send(self.ada, title=" ")
        self.assertEqual(response.json()["title"], "minutes.pdf")

    def test_more_files_follow(self):
        """All but the batch's last file say so (frontend/upload.js): its
        mail waits for the rest (specs/files.md)"""
        response = self.send(self.ada, more="1")
        event = Event.objects.get(item=response.json()["id"], action=Action.CREATED)
        self.assertTrue(event.data["more"])
        response = self.send(self.ada)
        event = Event.objects.get(item=response.json()["id"], action=Action.CREATED)
        self.assertNotIn("more", event.data)

    def test_errors(self):
        self.assertEqual(self.send(self.ada, batch="nope").status_code, 400)
        with patch.object(attachments, "MAX_SIZE", 3):
            response = self.send(self.ada)
        self.assertEqual(response.status_code, 413)
        self.assertIn("Files can be at most", response.json()["detail"])
        self.assertFalse(Item.objects.filter(title="minutes.pdf").exists())

    def test_clients(self):
        self.assertEqual(self.send(self.cleo, folder=self.public).status_code, 403)
        self.assertEqual(self.send(self.cleo, folder=self.private).status_code, 404)
        self.client.force_login(self.ada)
        url = reverse("file_upload", args=[self.project.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertFalse(Item.objects.filter(title="minutes.pdf").exists())


class FilePageTest(Fixture, TestCase):
    def page(self, user, item=None, name="file"):
        return self.get(user, reverse(name, args=[(item or self.shared_file).pk]))

    def test_staff_and_client_see_a_visible_file(self):
        for user in [self.ada, self.cleo]:
            response = self.page(user)
            self.assertContains(response, "shared.txt")
            self.assertContains(response, "Clients can see this")
            self.assertContains(
                response, reverse("file_download", args=[self.shared_file.pk])
            )

    def test_a_client_gets_404_for_internal_files_everywhere(self):
        self.client.force_login(self.cleo)
        for item in [self.secret_file, self.root_secret]:
            pk = item.pk
            for name in ["file", "file_edit", "file_download", "file_preview"]:
                with self.subTest(name=name, item=item.title):
                    self.assertEqual(
                        self.client.get(reverse(name, args=[pk])).status_code, 404
                    )
            for name in ["file", "file_replace"]:
                self.assertEqual(
                    self.client.post(reverse(name, args=[pk])).status_code, 404
                )
        version = self.secret_file.upload.versions.get()
        for name in ["file_version_download", "file_version_preview"]:
            url = reverse(name, args=[self.secret_file.pk, version.pk])
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_the_preview_is_shown_for_images_only(self):
        image = self.upload("pic.png", content=png(), visible=True)
        self.assertContains(
            self.page(self.cleo, image), reverse("file_preview", args=[image.pk])
        )
        self.assertNotContains(
            self.page(self.cleo), reverse("file_preview", args=[self.shared_file.pk])
        )

    def test_comments(self):
        self.client.force_login(self.cleo)
        url = self.shared_file.get_absolute_url()
        self.client.post(url, {"form": "comment", "content": "Looks good"})
        self.assertContains(self.client.get(url), "Looks good")
        self.assertEqual(self.shared_file.comments.count(), 1)

    def test_description_and_editing(self):
        self.client.force_login(self.ada)
        url = reverse("file_edit", args=[self.secret_file.pk])
        response = self.client.post(
            url, {"title": "Renamed", "description": "Says **it**"}
        )
        self.assertRedirects(response, self.secret_file.get_absolute_url())
        self.assertContains(
            self.client.get(self.secret_file.get_absolute_url()), "<strong>it</strong>"
        )
        self.assertEqual(Item.objects.get(pk=self.secret_file.pk).title, "Renamed")

    def test_clients_edit_only_their_files(self):
        self.client.force_login(self.cleo)
        self.assertEqual(
            self.client.get(
                reverse("file_edit", args=[self.shared_file.pk])
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                reverse("file_replace", args=[self.shared_file.pk])
            ).status_code,
            403,
        )
        mine = ops.create_upload(
            project=self.project,
            file=file("mine.txt"),
            creator=self.cleo,
            parent=self.public,
        )
        self.assertEqual(
            self.client.get(reverse("file_edit", args=[mine.pk])).status_code, 200
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
            file=file("cleo.txt"),
            creator=self.cleo,
            parent=self.public,
        )
        # Finn and Eve both have no organization: they don't match each other
        by_nobody = ops.create_upload(
            project=self.project,
            file=file("eve.txt"),
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
            self.client.force_login(user)
            for name, method in [("file_edit", "get"), ("file_replace", "post")]:
                with self.subTest(user=user.email, item=item.title, name=name):
                    response = getattr(self.client, method)(
                        reverse(name, args=[item.pk])
                    )
                    self.assertEqual(response.status_code != 403, allowed)
        self.client.force_login(colleague)
        response = self.client.post(
            reverse("file_edit", args=[theirs.pk]), {"title": "Renamed"}
        )
        self.assertRedirects(response, theirs.get_absolute_url())
        response = self.client.post(
            reverse("file_replace", args=[theirs.pk]),
            {"file": SimpleUploadedFile("two.txt", b"Two")},
        )
        self.assertRedirects(response, theirs.get_absolute_url())
        theirs.refresh_from_db()
        self.assertEqual(theirs.title, "Renamed")
        self.assertEqual(theirs.upload.versions.count(), 2)

    def test_replacing_keeps_the_url_comments_and_versions(self):
        ops.add_comment(self.shared_file, author=self.bob, content="Comment")
        self.client.force_login(self.ada)
        response = self.client.post(
            reverse("file_replace", args=[self.shared_file.pk]),
            {"file": SimpleUploadedFile("shared-2.txt", b"Two")},
        )
        self.assertRedirects(response, self.shared_file.get_absolute_url())
        self.assertEqual(
            [v.name for v in self.shared_file.upload.versions.all()],
            ["shared-2.txt", "shared.txt"],
        )
        self.assertEqual(self.shared_file.comments.count(), 1)
        download = self.client.get(reverse("file_download", args=[self.shared_file.pk]))
        self.assertEqual(read(download), b"Two")
        self.assertTrue(
            Event.objects.filter(item=self.shared_file, action=Action.EDITED).exists()
        )

    def test_older_versions_are_for_staff(self):
        operations.replace_upload(
            self.shared_file, file("shared-2.txt", b"Two"), actor=self.ada
        )
        old = self.shared_file.upload.versions.last()
        old_url = reverse("file_version_download", args=[self.shared_file.pk, old.pk])
        response = self.page(self.ada)
        self.assertContains(response, old_url)
        self.assertEqual(read(self.client.get(old_url)), b"Plan")
        response = self.page(self.cleo)
        self.assertNotContains(response, old_url)
        self.assertNotContains(response, "Earlier versions")
        self.assertEqual(self.client.get(old_url).status_code, 403)
        preview = reverse("file_version_preview", args=[self.shared_file.pk, old.pk])
        self.assertEqual(self.client.get(preview).status_code, 403)

    def test_a_version_of_another_file_is_a_404(self):
        other = self.shared_file.upload.versions.get()
        url = reverse("file_version_download", args=[self.root_shared.pk, other.pk])
        self.assertEqual(self.get(self.ada, url).status_code, 404)

    def test_replacing_too_large(self):
        big = SimpleUploadedFile("big.bin", b"xxxx")
        self.client.force_login(self.ada)
        with patch.object(attachments, "MAX_SIZE", 3):
            response = self.client.post(
                reverse("file_replace", args=[self.shared_file.pk]), {"file": big}
            )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.shared_file.upload.versions.count(), 1)

    def test_replacing_without_a_file(self):
        self.client.force_login(self.ada)
        response = self.client.post(reverse("file_replace", args=[self.shared_file.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.shared_file.upload.versions.count(), 1)

    def test_trashing_and_restoring(self):
        self.client.force_login(self.ada)
        self.client.post(reverse("item_trash", args=[self.shared_file.pk]))
        self.assertEqual(
            self.get(self.ada, self.shared_file.get_absolute_url()).status_code, 404
        )
        self.assertEqual(
            self.get(
                self.ada, reverse("file_download", args=[self.shared_file.pk])
            ).status_code,
            404,
        )
        self.client.post(reverse("item_restore", args=[self.shared_file.pk]))
        self.assertEqual(
            self.get(self.ada, self.shared_file.get_absolute_url()).status_code, 200
        )


class DownloadTest(Fixture, TestCase):
    def download(self, user, item):
        self.client.force_login(user)
        response = self.client.get(reverse("file_download", args=[item.pk]))
        body = read(response)
        return response, body

    def test_download(self):
        response, body = self.download(self.cleo, self.shared_file)
        self.assertEqual(body, b"Plan")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertIn("private", response["Cache-Control"])

    def test_images_and_pdfs_are_inline_everything_else_a_download(self):
        for name, content, inline in [
            ("a.png", png(), True),
            ("a.pdf", pdf(), True),
            ("a.html", b"<script>alert(1)</script>", False),
            ("a.svg", b"<svg onload=alert(1)/>", False),
            ("a.zip", b"PK", False),
        ]:
            item = self.upload(name, content=content, visible=True)
            response, _body = self.download(self.cleo, item)
            with self.subTest(name=name):
                self.assertEqual(
                    response["Content-Disposition"].startswith("inline"), inline
                )
                self.assertEqual(response["X-Content-Type-Options"], "nosniff")

    def test_a_client_gets_404_for_internal_files(self):
        for item in [self.secret_file, self.root_secret]:
            response, _body = self.download(self.cleo, item)
            self.assertEqual(response.status_code, 404)

    def test_staff_download_internal_files(self):
        _response, body = self.download(self.ada, self.secret_file)
        self.assertEqual(body, b"Plan")

    def test_anonymous_people_are_sent_to_the_login(self):
        self.client.logout()
        response = self.client.get(reverse("file_download", args=[self.shared_file.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

    def test_limited_projects_hide_their_files_from_other_staff(self):
        limited = project("Limited", members=[self.ada], all_access=False)
        item = ops.create_upload(project=limited, file=file("hr.txt"), creator=self.ada)
        response, _body = self.download(self.bob, item)
        self.assertEqual(response.status_code, 404)
        response, _body = self.download(self.ada, item)
        self.assertEqual(response.status_code, 200)

    def test_a_visibility_switch_changes_downloads(self):
        ops.set_visibility(self.root_secret, visible=True, actor=self.ada)
        self.assertEqual(self.download(self.cleo, self.root_secret)[0].status_code, 200)
        ops.set_visibility(self.root_secret, visible=False, actor=self.ada)
        self.assertEqual(self.download(self.cleo, self.root_secret)[0].status_code, 404)


class PreviewTest(Fixture, TestCase):
    def preview(self, user, item):
        self.client.force_login(user)
        response = self.client.get(reverse("file_preview", args=[item.pk]))
        return response, read(response)

    def test_an_image_gets_a_webp_400_pixels_wide(self):
        item = self.upload("pic.png", content=png(800, 400), visible=True)
        response, body = self.preview(self.cleo, item)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/webp")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        image = Image.open(io.BytesIO(body))
        self.assertEqual(image.format, "WEBP")
        self.assertEqual(image.size, (400, 200))

    def test_small_images_are_not_enlarged(self):
        item = self.upload("small.png", content=png(100, 50), visible=True)
        _response, body = self.preview(self.ada, item)
        self.assertEqual(Image.open(io.BytesIO(body)).size, (100, 50))

    def test_the_first_page_of_a_pdf(self):
        item = self.upload("doc.pdf", content=pdf(), visible=True)
        response, body = self.preview(self.cleo, item)
        self.assertEqual(response.status_code, 200)
        image = Image.open(io.BytesIO(body))
        self.assertEqual(image.size[0], 400)
        self.assertEqual(image.size[1], 800)

    def test_made_on_the_first_request_and_stored_next_to_the_file(self):
        item = self.upload("pic.png", content=png(), visible=True)
        version = item.upload.versions.get()
        storage = version.file.storage
        name = preview_name(version.file.name)
        self.assertTrue(name.startswith(version.file.name.rsplit("/", 1)[0] + "/"))
        self.assertFalse(storage.exists(name))
        self.preview(self.ada, item)
        self.assertTrue(storage.exists(name))
        # The second request serves the stored one
        calls = []
        original = previews.render
        previews.render = lambda version: calls.append(version) or original(version)
        try:
            self.assertEqual(self.preview(self.ada, item)[0].status_code, 200)
        finally:
            previews.render = original
        self.assertEqual(calls, [])

    def test_a_file_named_preview_webp_still_gets_a_preview(self):
        item = self.upload("preview.webp", content=png(800, 400), visible=True)
        version = item.upload.versions.get()
        self.assertNotEqual(preview_name(version.file.name), version.file.name)
        _response, body = self.preview(self.ada, item)
        self.assertEqual(Image.open(io.BytesIO(body)).size, (400, 200))
        with self.captureOnCommitCallbacks(execute=True):
            item.delete()
        self.assertFalse(version.file.storage.exists(version.file.name))

    def test_two_first_requests_leave_one_preview(self):
        item = self.upload("pic.png", content=png(), visible=True)
        version = item.upload.versions.get()
        storage = version.file.storage
        name = preview_name(version.file.name)
        real = previews.render

        def render(version):
            # The other request saves its preview while this one renders
            data = real(version)
            storage.save(name, ContentFile(data))
            return data

        with patch.object(previews, "render", render):
            self.assertEqual(previews.preview_for(version), name)
        folder = name.rsplit("/", 1)[0]
        self.assertEqual(storage.listdir(folder)[1], ["preview.webp"])

    def test_a_failed_preview_is_not_rendered_again(self):
        item = self.upload("broken.png", content=b"not an image", visible=True)
        with self.assertLogs("biwak.files.previews", "WARNING"):
            self.assertEqual(self.preview(self.ada, item)[0].status_code, 404)
        with patch.object(previews, "render", return_value=None) as render:
            self.assertEqual(self.preview(self.ada, item)[0].status_code, 404)
        render.assert_not_called()

    def test_the_failure_marker_is_deleted_with_the_file(self):
        item = self.upload("broken.png", content=b"not an image", visible=True)
        version = item.upload.versions.get()
        with self.assertLogs("biwak.files.previews", "WARNING"):
            self.preview(self.ada, item)
        folder = preview_name(version.file.name).rsplit("/", 1)[0]
        self.assertTrue(version.file.storage.listdir(folder)[1])
        with self.captureOnCommitCallbacks(execute=True):
            item.delete()
        self.assertEqual(version.file.storage.listdir(folder)[1], [])

    def test_the_preview_is_deleted_with_the_file(self):
        item = self.upload("pic.png", content=png(), visible=True)
        version = item.upload.versions.get()
        self.preview(self.ada, item)
        storage, name = version.file.storage, preview_name(version.file.name)
        with self.captureOnCommitCallbacks(execute=True):
            item.delete()
        self.assertFalse(storage.exists(name))

    def test_other_files_have_none(self):
        response, _body = self.preview(self.ada, self.shared_file)
        self.assertEqual(response.status_code, 404)

    def test_broken_files_have_none(self):
        item = self.upload("broken.png", content=b"not an image", visible=True)
        with self.assertLogs("biwak.files.previews", "WARNING"):
            response, _body = self.preview(self.ada, item)
        self.assertEqual(response.status_code, 404)
        item = self.upload("broken.pdf", content=b"not a pdf", visible=True)
        with self.assertLogs("biwak.files.previews", "WARNING"):
            self.assertEqual(self.preview(self.ada, item)[0].status_code, 404)

    def test_visibility(self):
        internal = self.upload("hidden.png", content=png())
        self.assertEqual(self.preview(self.cleo, internal)[0].status_code, 404)
        self.assertEqual(self.preview(self.ada, internal)[0].status_code, 200)
        self.client.logout()
        response = self.client.get(reverse("file_preview", args=[internal.pk]))
        self.assertEqual(response.status_code, 302)

    def test_internal_previews_do_not_leak_after_the_switch_goes_off(self):
        item = self.upload("pic.png", content=png(), visible=True)
        self.assertEqual(self.preview(self.cleo, item)[0].status_code, 200)
        ops.set_visibility(item, visible=False, actor=self.ada)
        self.assertEqual(self.preview(self.cleo, item)[0].status_code, 404)

    def test_a_new_version_gets_its_own_preview(self):
        item = self.upload("pic.png", content=png(800, 400, "red"), visible=True)
        self.preview(self.ada, item)
        operations.replace_upload(
            item, file("pic2.png", png(1000, 1000, "blue")), actor=self.ada
        )
        _response, body = self.preview(self.ada, item)
        self.assertEqual(Image.open(io.BytesIO(body)).size, (400, 400))


@mock_aws
@override_settings(
    STORAGES={
        "default": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                "bucket_name": "biwak-test",
                "access_key": "testing",
                "secret_key": "testing",
                "region_name": "us-east-1",
                "default_acl": None,
                "querystring_auth": True,
                "file_overwrite": False,
                "signature_version": "s3v4",
            },
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        },
    }
)
class BucketTest(Fixture, TestCase):
    def setUp(self):
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="biwak-test")
        super().setUp()

    def test_downloads_and_previews_redirect_to_presigned_urls(self):
        item = self.upload("pic.png", content=png(), visible=True)
        self.client.force_login(self.cleo)
        response = self.client.get(reverse("file_download", args=[item.pk]))
        self.assertEqual(response.status_code, 302)
        query = parse_qs(urlsplit(response["Location"]).query)
        self.assertEqual(query["X-Amz-Expires"], ["300"])
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        response = self.client.get(reverse("file_preview", args=[item.pk]))
        self.assertEqual(response.status_code, 302)
        query = parse_qs(urlsplit(response["Location"]).query)
        self.assertEqual(query["response-content-type"], ["image/webp"])
        keys = [
            o["Key"]
            for o in boto3.client("s3", region_name="us-east-1").list_objects_v2(
                Bucket="biwak-test"
            )["Contents"]
        ]
        self.assertTrue(any(key.endswith("/preview.webp") for key in keys))

    def test_internal_files_are_404_for_clients_in_the_bucket_too(self):
        self.client.force_login(self.cleo)
        for name in ["file_download", "file_preview"]:
            response = self.client.get(reverse(name, args=[self.secret_file.pk]))
            self.assertEqual(response.status_code, 404)


class ProjectPageTest(Fixture, TestCase):
    def test_the_docs_and_files_section_counts_what_the_person_sees(self):
        url = reverse("project", args=[self.project.pk])
        for user, counts in [
            (self.ada, "2 folders, 0 docs, 2 files"),
            (self.cleo, "1 folder, 0 docs, 1 file"),
        ]:
            html = self.get(user, url).content.decode()
            self.assertIn(counts, " ".join(html.split()))


class BreadcrumbsTest(Fixture, TestCase):
    def test_two_queries_however_deep(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from biwak.files.library import breadcrumbs

        folder = self.public
        for title in ["One", "Two", "Three", "Four"]:
            folder = ops.create_folder(
                project=self.project, title=title, creator=self.ada, parent=folder
            )
        folder = Item.objects.get(pk=folder.pk)
        with CaptureQueriesContext(connection) as queries:
            crumbs = breadcrumbs(folder)
        self.assertEqual([c.title for c in crumbs], ["Public", "One", "Two", "Three"])
        self.assertLessEqual(len(queries), 2)
        self.assertEqual(breadcrumbs(self.public), [])
        self.assertEqual(breadcrumbs(None), [])


class FolderParamTest(TestCase):
    def test_a_folder_which_is_no_number(self):
        from biwak.test_utils import person, project

        ada = person("Ada")
        website = project(members=[ada])
        self.client.force_login(ada)
        response = self.client.get(f"/projects/{website.pk}/docs/new/?folder=x")
        self.assertEqual(response.status_code, 404)
