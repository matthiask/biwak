"""Adding to-dos from text (specs/todos-from-text.md): dropping files onto
a list and onto a list on the project's page, the preview"""

from biwak.items import operations as ops
from biwak.items.models import Item, Kind
from biwak.test_e2e import E2ETestCase, expect


# Files of ``[name, type, text]`` dropped onto the selector's element
DROP = """([selector, files]) => {
    const transfer = new DataTransfer()
    for (const [name, type, text] of files)
        transfer.items.add(new File([text], name, { type }))
    const target = document.querySelector(selector)
    for (const type of ["dragenter", "dragover", "drop"])
        target.dispatchEvent(new DragEvent(type, {
            bubbles: true, cancelable: true, dataTransfer: transfer,
        }))
}"""

PLAN = "# Design\n- Logo\n  - colors\n  - [x] fonts\n- [x] Flyers\n"


class FromTextTest(E2ETestCase):
    def setUp(self):
        super().setUp()
        self.list = ops.create_list(
            project=self.project, title="Launch", creator=self.ada, visible=True
        )
        self.design = ops.create_group(todolist=self.list.todolist, title="Design")
        self.other = ops.create_list(
            project=self.project, title="Later", creator=self.ada
        )

    def titles(self, todolist):
        return list(
            Item.objects
            .filter(parent=todolist, kind=Kind.TODO)
            .order_by("pk")
            .values_list("title", flat=True)
        )

    def test_dropping_files_onto_the_lists_page(self):
        page = self.page
        self.goto(page, self.list)
        page.wait_for_load_state("networkidle")
        page.evaluate(
            DROP,
            [
                ".wb-todolist",
                [
                    ["plan.md", "", PLAN],
                    ["more.txt", "text/plain", "- Party\n"],
                ],
            ],
        )
        dialog = page.get_by_role("dialog", name="Add from text…")
        expect(dialog).to_be_visible()
        expect(dialog.get_by_label("Text")).to_have_value(PLAN.rstrip() + "\n\n- Party")
        preview = dialog.locator("[data-from-text-preview]")
        expect(preview).to_contain_text("Design")
        expect(preview).to_contain_text("existing")
        expect(preview.locator(".wb-signal")).to_have_text("1/2")
        button = dialog.get_by_role("button", name="Add 3 to-dos")
        expect(button).to_be_enabled()
        button.click()
        expect(page.locator(".wb-todolist")).to_contain_text("Party")
        self.assertEqual(self.titles(self.list), ["Logo", "Flyers", "Party"])
        self.assertEqual(self.errors, [])

    def test_other_files_are_refused(self):
        page = self.page
        self.goto(page, self.list)
        page.wait_for_load_state("networkidle")
        page.evaluate(DROP, [".wb-todolist", [["photo.png", "image/png", "x"]]])
        expect(page.get_by_role("alert")).to_have_text(
            "Only text files can be added as to-dos."
        )
        expect(page.get_by_role("dialog")).to_have_count(0)

    def test_dropping_onto_a_list_on_the_projects_page(self):
        page = self.page
        self.goto(page, self.project)
        page.wait_for_load_state("networkidle")
        page.evaluate(
            DROP,
            [
                f'[data-drop-text$="/lists/{self.other.pk}/from-text/"]',
                [["plan.md", "text/markdown", "- One\n- Two\n"]],
            ],
        )
        dialog = page.get_by_role("dialog", name="Add from text…")
        dialog.get_by_role("button", name="Add 2 to-dos").click()
        page.wait_for_url(f"**{self.other.get_absolute_url()}")
        self.assertEqual(self.titles(self.other), ["One", "Two"])
        self.assertEqual(self.titles(self.list), [])

    def test_the_preview_follows_the_text_and_the_list(self):
        page = self.page
        self.goto(page, self.list)
        page.locator("summary", has_text="More").click()
        page.get_by_role("link", name="Add from text…").click()
        dialog = page.get_by_role("dialog", name="Add from text…")
        button = dialog.locator("button[type=submit]")
        expect(button).to_be_disabled()
        expect(dialog).to_contain_text("Paste a text or choose a file.")
        dialog.get_by_label("Text").fill("# Design\n- Logo\n")
        expect(dialog.locator("[data-from-text-preview]")).to_contain_text("existing")
        expect(button).to_have_text("Add 1 to-do")
        expect(button).to_be_enabled()
        # Another list: the heading is a new group there
        dialog.locator(".wb-combobox input").click()
        dialog.get_by_role("option", name="Later").click()
        expect(dialog.locator("[data-from-text-preview]")).to_contain_text("new")
        dialog.get_by_label("Text").fill("# Design\n")
        expect(dialog).to_contain_text("This text has no to-dos.")
        expect(button).to_be_disabled()
        # A file chosen is read into the field
        dialog.get_by_label("Or a file").set_input_files(
            files=[{"name": "a.md", "mimeType": "text/markdown", "buffer": b"- A\n"}]
        )
        expect(dialog.get_by_label("Text")).to_have_value("# Design\n\n- A")
        expect(button).to_have_text("Add 1 to-do")
        button.click()
        page.wait_for_url(f"**{self.other.get_absolute_url()}")
        self.assertEqual(self.titles(self.other), ["A"])
        self.assertEqual(self.errors, [])
