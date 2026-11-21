"""A folder's tiles in the browser (frontend/files.js, specs/files.md,
"Moving and selecting"): dragging onto folders, "..", breadcrumbs; selecting several with Ctrl- and
Shift-click and moving them"""

import re
import time

from django.core.files.base import ContentFile
from django.urls import reverse

from biwak.activity.models import Event
from biwak.items import operations as ops
from biwak.items.models import Item
from biwak.projects.models import Membership
from biwak.test_e2e import ASGIServerThread, E2ETestCase, expect, uvicorn
from biwak.test_utils import person


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


DROP = """([selector, names]) => {
    const transfer = new DataTransfer()
    for (const name of names)
        transfer.items.add(new File(["Plan"], name, { type: "text/plain" }))
    const target = document.querySelector(selector)
    for (const type of ["dragenter", "dragover", "drop"])
        target.dispatchEvent(new DragEvent(type, {
            bubbles: true, cancelable: true, dataTransfer: transfer,
        }))
}"""


class UploadTest(E2ETestCase):
    """Uploading several files (specs/files.md, "Uploading files")"""

    def setUp(self):
        super().setUp()
        self.minutes = ops.create_folder(
            project=self.project, title="Minutes", creator=self.ada, visible=True
        )
        self.inner = ops.create_folder(
            project=self.project, title="Inner", creator=self.ada, parent=self.minutes
        )

    def files_in(self, folder):
        return sorted(
            Item.objects.filter(parent=folder, kind="file").values_list(
                "title", flat=True
            )
        )

    def test_dropping_files_into_the_folder(self):
        page = self.page
        self.goto(page, self.minutes)
        page.wait_for_load_state("networkidle")
        page.evaluate(DROP, [".wb-tiles", ["one.txt", "two.txt"]])
        dialog = page.get_by_role("dialog", name="Upload files")
        expect(dialog).to_be_visible()
        rows = dialog.locator(".wb-upload-row")
        expect(rows).to_have_count(2)
        # More dropped onto the modal, one removed, one renamed
        page.evaluate(DROP, ["#modal form", ["three.txt"]])
        expect(rows).to_have_count(3)
        rows.nth(1).get_by_role("button", name="Remove: two.txt").click()
        expect(rows).to_have_count(2)
        rows.nth(0).get_by_label("Name").fill("Kick-off")
        dialog.get_by_role("button", name="Upload").click()
        expect(page.locator(".wb-tile-file")).to_have_count(2)
        self.assertEqual(self.files_in(self.minutes), ["Kick-off.txt", "three.txt"])
        events = {
            e.data["batch"]
            for e in Event.objects.filter(
                item__parent=self.minutes, item__kind="file", action="created"
            )
        }
        self.assertEqual(len(events), 1)
        # All but the last say more follow: the mail waits for the rest
        self.assertEqual(
            [
                e.data.get("more", False)
                for e in Event.objects.filter(
                    item__parent=self.minutes, item__kind="file", action="created"
                ).order_by("pk")
            ],
            [True, False],
        )
        self.assertEqual(self.errors, [])

    def test_dropping_onto_a_folder_tile_and_the_button(self):
        page = self.page
        self.goto(page, self.minutes)
        page.wait_for_load_state("networkidle")
        page.evaluate(DROP, [f'[data-tile="{self.inner.pk}"]', ["deep.txt"]])
        dialog = page.get_by_role("dialog", name="Upload files")
        expect(dialog.locator(".wb-upload-row")).to_have_count(1)
        dialog.get_by_role("button", name="Upload").click()
        expect(dialog).to_be_hidden()
        page.wait_for_load_state("networkidle")
        self.assertEqual(self.files_in(self.inner), ["deep.txt"])
        self.assertTrue(page.url.endswith(self.minutes.get_absolute_url()))

        # The button: a file input taking several
        page.get_by_role("link", name="Upload files").click()
        dialog = page.get_by_role("dialog", name="Upload files")
        dialog.get_by_label("Files").set_input_files([
            {"name": "a.txt", "mimeType": "text/plain", "buffer": b"A"},
            {"name": "b.txt", "mimeType": "text/plain", "buffer": b"B"},
        ])
        expect(dialog.locator(".wb-upload-row")).to_have_count(2)
        dialog.get_by_role("button", name="Upload").click()
        expect(page.locator(".wb-tile-file")).to_have_count(2)
        self.assertEqual(self.files_in(self.minutes), ["a.txt", "b.txt"])
        self.assertEqual(self.errors, [])

    def test_also_tell(self):
        """A line saying who will be told, "Also tell…" adds others, nothing
        preselected (decided 2026-11-21: additive)"""
        dan = person("Dan")
        dan.notification_level = "concerns_me"
        dan.save()
        Membership.objects.create(project=self.project, user=dan)
        page = self.page
        self.goto(page, self.minutes)
        page.get_by_role("link", name="Upload files").click()
        dialog = page.get_by_role("dialog", name="Upload files")
        dialog.get_by_label("Files").set_input_files([
            {"name": "a.txt", "mimeType": "text/plain", "buffer": b"A"},
        ])
        # Cleo sees the visible folder and hears of everything; Ada posts
        expect(dialog.get_by_text("Cleo will be told.")).to_be_visible()
        pills = dialog.locator(".wb-pill")
        expect(pills).to_have_count(0)
        dialog.locator(".wb-picker-input").fill("da")
        dialog.locator(".wb-picker-input").press("Enter")
        expect(pills).to_have_text([re.compile("Dan")])
        # Nobody left to pick: the button under the list takes the click
        dialog.get_by_role("button", name="Upload").click(timeout=2000)
        expect(page.locator(".wb-tile-file")).to_have_count(1)
        upload = Item.objects.get(parent=self.minutes, kind="file")
        self.assertEqual(
            set(upload.subscriptions.values_list("user", flat=True)),
            {self.ada.pk, self.cleo.pk, dan.pk},
        )
        self.assertEqual(self.errors, [])

    def test_an_error_stays_on_its_row(self):
        page = self.page
        self.goto(page, self.minutes)
        page.wait_for_load_state("networkidle")
        page.get_by_role("link", name="Upload files").click()
        dialog = page.get_by_role("dialog", name="Upload files")
        # Over the limit the page says (a smaller one for the test)
        dialog.locator("[data-upload]").evaluate(
            "(el) => { el.dataset.uploadMax = '3' }"
        )
        dialog.get_by_label("Files").set_input_files([
            {"name": "ok.txt", "mimeType": "text/plain", "buffer": b"OK"},
            {"name": "big.txt", "mimeType": "text/plain", "buffer": b"Too big"},
        ])
        dialog.get_by_role("button", name="Upload").click()
        expect(dialog.locator(".wb-upload-row.is-failed")).to_contain_text(
            "Files can be at most"
        )
        expect(dialog.locator(".wb-upload-row.is-done")).to_have_count(1)
        self.assertEqual(self.files_in(self.minutes), ["ok.txt"])
        # The last one sent: nothing more follows (the big one never goes)
        self.assertNotIn(
            "more", Event.objects.get(item__title="ok.txt", action="created").data
        )
        # Closing shows what went up
        dialog.get_by_role("button", name="Cancel").click()
        expect(page.locator(".wb-tile-file")).to_have_count(1)


class NewDocTest(E2ETestCase):
    """New docs as drafts (specs/files.md, "Docs"): the address
    replaced once there's text, "Tell people about it?" at the first Done"""

    host = "127.0.0.1"
    server_thread_class = ASGIServerThread

    @classmethod
    def setUpClass(cls):
        if uvicorn is None:  # pragma: no cover
            raise cls.skipTest(cls, "uvicorn isn't installed")
        super().setUpClass()

    def setUp(self):
        super().setUp()
        self.minutes = ops.create_folder(
            project=self.project, title="Minutes", creator=self.ada, visible=True
        )

    def new_doc(self):
        page = self.page
        self.goto(page, self.minutes)
        page.get_by_role("link", name="New doc").click()
        page.wait_for_url("**/docs/new/**")
        expect(page.locator("[data-collab]")).to_have_attribute(
            "data-collab-state", "connected"
        )
        draft = Item.objects.filter(is_draft=True).latest("pk")
        # The cursor after "# ": the title is typed first
        expect(page.locator(".cm-content")).to_be_focused()
        return page, draft

    def wait_for_doc(self, draft):
        """Saved a few seconds after the last keystroke"""
        for _ in range(100):
            if not Item.objects.get(pk=draft.pk).is_draft:
                return
            time.sleep(0.1)
        self.fail("Still a draft")

    def test_the_address_is_the_docs_once_written(self):
        page, draft = self.new_doc()
        history = page.evaluate("history.length")
        page.keyboard.type("Kick-off")
        page.wait_for_url(f"**{reverse('doc_edit', args=[draft.pk])}")
        # Replaced, not added
        self.assertEqual(page.evaluate("history.length"), history)
        self.wait_for_doc(draft)
        doc = Item.objects.get(pk=draft.pk)
        self.assertEqual(doc.title, "Kick-off")
        self.assertEqual(doc.doc.content, "# Kick-off")
        # Reloading opens the doc, not a new draft
        page.reload()
        expect(page.locator(".cm-content")).to_contain_text("Kick-off")
        self.assertEqual(Item.objects.filter(kind="doc").count(), 1)
        self.assertEqual(self.errors, [])

    def test_telling_people_at_the_first_done(self):
        page, draft = self.new_doc()
        page.keyboard.type("Plan")
        page.wait_for_url(f"**{reverse('doc_edit', args=[draft.pk])}")
        page.get_by_role("link", name="Done").click()
        dialog = page.get_by_role("dialog", name="Tell people about it?")
        expect(dialog).to_be_visible()
        # Who wants to hear is told; nobody preselected to add
        expect(dialog.get_by_text("Cleo will be told.")).to_be_visible()
        expect(dialog.locator(".wb-pill")).to_have_count(0)
        dialog.get_by_label("Note").fill("Our plan")
        dialog.get_by_role("button", name="Tell them").click()
        page.wait_for_url(f"**{draft.get_absolute_url()}")
        event = Event.objects.get(item=draft, action="shared")
        self.assertEqual(event.data["note"], "Our plan")
        self.assertEqual(event.data["people"], [self.cleo.pk])
        # Asked once: "Done" now just leaves
        page.goto(f"{self.live_server_url}{reverse('doc_edit', args=[draft.pk])}")
        page.get_by_role("link", name="Done").click()
        page.wait_for_url(f"**{draft.get_absolute_url()}")
        expect(page.get_by_role("dialog")).to_have_count(0)
        self.assertEqual(self.errors, [])

    def test_not_now_and_done_on_an_empty_draft(self):
        page, draft = self.new_doc()
        # Nothing written: back to the folder, no question
        page.get_by_role("link", name="Done").click()
        page.wait_for_url(f"**{self.minutes.get_absolute_url()}")
        expect(page.get_by_role("dialog")).to_have_count(0)
        expect(page.get_by_text("Nothing here yet.")).to_be_visible()

        page, draft = self.new_doc()
        page.keyboard.type("Plan")
        page.wait_for_url(f"**{reverse('doc_edit', args=[draft.pk])}")
        page.get_by_role("link", name="Done").click()
        dialog = page.get_by_role("dialog", name="Tell people about it?")
        dialog.get_by_role("button", name="Not now").click()
        page.wait_for_url(f"**{draft.get_absolute_url()}")
        self.assertFalse(Item.objects.get(pk=draft.pk).doc.tell_pending)
        # Nobody else: Cleo, who wants to hear, is told anyway
        event = Event.objects.get(action="shared")
        self.assertEqual(event.data["people"], [self.cleo.pk])
        self.assertNotIn("note", event.data)
        self.assertEqual(self.errors, [])
