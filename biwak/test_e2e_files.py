"""A folder's tiles in the browser (frontend/files.js, specs/ui-round-7.md):
dragging onto folders, "..", breadcrumbs; selecting several with Ctrl- and
Shift-click and moving them"""

import re

from django.core.files.base import ContentFile
from django.urls import reverse

from biwak.items import operations as ops
from biwak.items.models import Item
from biwak.test_e2e import E2ETestCase, expect


class TilesTest(E2ETestCase):
    def setUp(self):
        super().setUp()
        self.specs = ops.create_folder(
            project=self.project, title="Specs", creator=self.ada, visible=True
        )
        self.inner = ops.create_folder(
            project=self.project, title="Inner", creator=self.ada, parent=self.specs
        )
        self.files = [
            ops.create_upload(
                project=self.project,
                file=ContentFile(b"Plan", name=name),
                creator=self.ada,
            )
            for name in ["a.txt", "b.txt", "c.txt", "d.txt"]
        ]

    def root(self):
        return reverse("project_files", args=[self.project.pk])

    def tile(self, page, item):
        return page.locator(f'[data-tile="{item.pk}"]')

    def parent_of(self, item):
        return Item.objects.get(pk=item.pk).parent

    def wait_for_files(self, page):
        page.wait_for_function("() => !!document.querySelector('[data-tiles]')")
        # The chunk with the script is loaded after the page
        page.wait_for_load_state("networkidle")

    def test_dragging_onto_a_folder_up_and_a_breadcrumb(self):
        page = self.page
        self.goto(page, self.root())
        self.wait_for_files(page)
        a = self.files[0]
        self.tile(page, a).drag_to(self.tile(page, self.specs))
        expect(self.tile(page, a)).to_have_count(0)
        page.wait_for_load_state("networkidle")
        self.assertEqual(self.parent_of(a), self.specs)
        # Inside Inner: ".." leads to Specs, the breadcrumb to the top level
        b = self.files[1]
        ops.move_item(b, parent=self.inner, actor=self.ada)
        self.goto(page, self.inner)
        self.wait_for_files(page)
        self.tile(page, b).drag_to(page.locator(".wb-tile-up"))
        expect(self.tile(page, b)).to_have_count(0)
        page.wait_for_load_state("networkidle")
        self.assertEqual(self.parent_of(b), self.specs)
        ops.move_item(b, parent=self.inner, actor=self.ada)
        self.goto(page, self.inner)
        self.wait_for_files(page)
        self.tile(page, b).drag_to(page.get_by_role("link", name="Docs and files"))
        expect(self.tile(page, b)).to_have_count(0)
        page.wait_for_load_state("networkidle")
        self.assertIsNone(self.parent_of(b))
        self.assertEqual(self.errors, [])

    def test_selecting_several_and_moving_them(self):
        page = self.page
        self.goto(page, self.root())
        self.wait_for_files(page)
        a, b, c, _d = self.files
        bar = page.locator("[data-selection-bar]")
        expect(bar).to_be_hidden()
        self.tile(page, a).click(modifiers=["ControlOrMeta"])
        expect(bar).to_be_visible()
        expect(bar).to_contain_text("1 selected")
        # Shift-click: the range from the last one
        self.tile(page, c).click(modifiers=["Shift"])
        expect(bar).to_contain_text("3 selected")
        for item in [a, b, c]:
            expect(self.tile(page, item)).to_have_class(re.compile("is-selected"))
        # Ctrl-click takes one out again; still on the page
        self.tile(page, b).click(modifiers=["ControlOrMeta"])
        expect(bar).to_contain_text("2 selected")
        self.assertTrue(page.url.endswith(self.root()))
        # Escape deselects
        page.keyboard.press("Escape")
        expect(bar).to_be_hidden()

        # The keyboard: Ctrl+Space and Shift+arrows on the focused tile
        self.tile(page, a).focus()
        page.keyboard.press("ControlOrMeta+Space")
        expect(bar).to_contain_text("1 selected")
        page.keyboard.press("Shift+ArrowRight")
        expect(bar).to_contain_text("2 selected")
        expect(self.tile(page, b)).to_have_class(re.compile("is-selected"))

        # "Move to…" for the selection
        bar.get_by_role("link", name="Move to…").click()
        dialog = page.get_by_role("dialog", name="Move to…")
        expect(dialog).to_contain_text("2 items")
        dialog.get_by_label("Folder").select_option(
            label="Specs (clients can see this)"
        )
        dialog.get_by_role("button", name="Move").click()
        expect(self.tile(page, a)).to_have_count(0)
        self.assertEqual(self.parent_of(a), self.specs)
        self.assertEqual(self.parent_of(b), self.specs)
        self.assertIsNone(self.parent_of(c))
        self.assertEqual(self.errors, [])

    def test_dragging_the_selection(self):
        page = self.page
        self.goto(page, self.root())
        self.wait_for_files(page)
        a, b, _c, d = self.files
        self.tile(page, a).click(modifiers=["ControlOrMeta"])
        self.tile(page, d).click(modifiers=["ControlOrMeta"])
        self.tile(page, d).drag_to(self.tile(page, self.specs))
        expect(self.tile(page, d)).to_have_count(0)
        expect(self.tile(page, a)).to_have_count(0)
        page.wait_for_load_state("networkidle")
        self.assertEqual(self.parent_of(a), self.specs)
        self.assertEqual(self.parent_of(d), self.specs)
        self.assertIsNone(self.parent_of(b))
        self.assertEqual(self.errors, [])

    def test_the_trash_for_the_selection(self):
        page = self.page
        self.goto(page, self.root())
        self.wait_for_files(page)
        _a, b, c, _d = self.files
        self.tile(page, b).click(modifiers=["ControlOrMeta"])
        self.tile(page, c).click(modifiers=["ControlOrMeta"])
        page.locator("[data-selection-bar]").get_by_role(
            "link", name="Move to trash"
        ).click()
        dialog = page.get_by_role("dialog", name="Move to the trash?")
        dialog.get_by_role("button", name="Move to the trash").click()
        expect(page.get_by_text("2 items are in the trash")).to_be_visible()
        self.assertEqual(
            {i.status for i in Item.objects.filter(pk__in=[b.pk, c.pk])}, {"trashed"}
        )

    def test_a_client_drags_nothing_of_others(self):
        page = self.login(self.cleo)
        self.goto(page, self.specs)
        self.wait_for_files(page)
        self.tile(page, self.inner).drag_to(page.locator(".wb-tile-up"))
        page.wait_for_load_state("networkidle")
        expect(self.tile(page, self.inner)).to_be_visible()
        self.assertEqual(self.parent_of(self.inner), self.specs)
        self.assertEqual(self.errors, [])
