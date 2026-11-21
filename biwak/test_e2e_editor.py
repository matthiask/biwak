"""Task lists, the toolbar and pasting in the browser (specs/editor.md)"""

from pathlib import Path

from django.urls import reverse

from biwak.items import operations as ops
from biwak.items.models import Todo
from biwak.test_e2e import E2ETestCase, expect
from biwak.test_paste import GOOGLE_DOCS, MAIL


NOTES = "Packing\n\n- [ ] tent\n- [x] stove\n- [ ] rope"


class TicksTest(E2ETestCase):
    def setUp(self):
        super().setUp()
        self.todolist = ops.create_list(
            project=self.project, title="Camp", creator=self.ada, visible=True
        )
        self.todo = ops.create_todo(
            todolist=self.todolist, title="Pack", creator=self.ada, notes=NOTES
        )

    def notes(self):
        return Todo.objects.get(pk=self.todo.pk).notes

    def test_staff_ticks_in_place(self):
        page = self.page
        self.goto(page, self.todo)
        page.evaluate("window.marker = 1")
        boxes = page.locator(".wb-checklist input[type=checkbox]")
        self.assertEqual(boxes.count(), 3)
        boxes.nth(0).check()
        expect(boxes.nth(0)).to_be_enabled()
        self.assertEqual(self.notes(), NOTES.replace("[ ] tent", "[x] tent"))
        # The version moved on: the next one works without a reload
        boxes.nth(1).uncheck()
        expect(boxes.nth(1)).to_be_enabled()
        self.assertEqual(self.notes(), "Packing\n\n- [x] tent\n- [ ] stove\n- [ ] rope")
        self.assertEqual(page.evaluate("window.marker"), 1)
        self.assertEqual(self.errors, [])

    def test_a_changed_text_reloads_the_page(self):
        page = self.page
        self.goto(page, self.todo)
        ops.update_todo(self.todo, actor=self.bob, notes="- [ ] new one")
        with page.expect_navigation():
            page.locator(".wb-checklist input[type=checkbox]").first.check()
        boxes = page.locator(".wb-checklist input[type=checkbox]")
        self.assertEqual(boxes.count(), 1)
        self.assertFalse(boxes.first.is_checked())
        self.assertEqual(self.notes(), "- [ ] new one")

    def test_a_client_ticks_a_todo_but_not_a_message(self):
        message = ops.create_message(
            project=self.project,
            title="Camp",
            creator=self.ada,
            content=NOTES,
            visible=True,
        )
        page = self.login(self.cleo)
        self.goto(page, self.todo)
        box = page.locator(".wb-checklist input[type=checkbox]").first
        box.check()
        expect(box).to_be_enabled()
        self.assertEqual(self.notes(), NOTES.replace("[ ] tent", "[x] tent"))
        self.goto(page, message)
        self.assertEqual(page.locator(".wb-checklist").count(), 0)
        boxes = page.locator("input.task-list-item-checkbox")
        self.assertEqual(boxes.count(), 3)
        expect(boxes.first).to_be_disabled()


class ToolbarTest(E2ETestCase):
    def setUp(self):
        super().setUp()
        self.page.set_viewport_size({"width": 1000, "height": 800})
        self.goto(self.page, reverse("message_new", args=[self.project.pk]))
        self.field = self.page.locator("textarea[name=content]")
        self.bar = self.page.locator(".wb-toolbar")

    def button(self, name):
        return self.bar.locator(f'[data-toolbar-action="{name}"]')

    def put(self, text, start=None, end=None):
        """The field with this text, the selection from ``start`` to ``end``
        (default: all)"""
        self.field.fill(text)
        self.select(0 if start is None else start, len(text) if end is None else end)

    def select(self, start, end=None):
        self.field.evaluate(
            "(el, [s, e]) => { el.focus(); el.setSelectionRange(s, e) }",
            [start, start if end is None else end],
        )

    def value(self):
        return self.field.input_value()

    def test_the_toolbar_is_always_there(self):
        expect(self.bar).to_be_visible()
        for name in [
            "bold",
            "italic",
            "link",
            "heading",
            "bullets",
            "numbers",
            "tasks",
            "quote",
            "code",
            "mention",
        ]:
            expect(self.button(name)).to_be_visible()
        # The attach button moved into it
        expect(self.bar.locator("button", has_text="Attach")).to_be_visible()
        self.assertEqual(self.page.locator(".wb-toolbar").count(), 1)

    def test_inline_buttons_wrap_and_unwrap(self):
        self.put("make this bold", 5, 9)
        self.button("bold").click()
        self.assertEqual(self.value(), "make **this** bold")
        self.button("bold").click()
        self.assertEqual(self.value(), "make this bold")
        self.button("italic").click()
        self.assertEqual(self.value(), "make _this_ bold")
        self.put("x", 1, 1)
        self.button("code").click()
        self.assertEqual(self.value(), "x``")
        self.field.fill("")
        self.button("bold").click()
        self.assertEqual(self.value(), "**bold**")
        self.assertEqual(
            self.field.evaluate(
                "el => el.value.slice(el.selectionStart, el.selectionEnd)"
            ),
            "bold",
        )

    def test_undo_after_a_button(self):
        self.put("make this bold", 5, 9)
        self.button("bold").click()
        self.assertEqual(self.value(), "make **this** bold")
        self.field.press("Control+z")
        self.assertEqual(self.value(), "make this bold")

    def test_links(self):
        self.put("see docs", 4, 8)
        self.button("link").click()
        self.assertEqual(self.value(), "see [docs](url)")
        self.assertEqual(
            self.field.evaluate(
                "el => el.value.slice(el.selectionStart, el.selectionEnd)"
            ),
            "url",
        )
        self.put("https://example.org/a")
        self.button("link").click()
        self.assertEqual(self.value(), "[](https://example.org/a)")

    def test_line_buttons(self):
        self.put("one\ntwo")
        self.button("bullets").click()
        self.assertEqual(self.value(), "- one\n- two")
        self.button("bullets").click()
        self.assertEqual(self.value(), "one\ntwo")
        self.button("numbers").click()
        self.assertEqual(self.value(), "1. one\n2. two")
        self.button("tasks").click()
        self.assertEqual(self.value(), "- [ ] one\n- [ ] two")
        self.button("tasks").click()
        self.assertEqual(self.value(), "one\ntwo")
        self.button("quote").click()
        self.assertEqual(self.value(), "> one\n> two")
        self.button("quote").click()
        self.button("heading").click()
        self.assertEqual(self.value(), "## one\n## two")
        self.button("heading").click()
        self.assertEqual(self.value(), "one\ntwo")
        # The current line only, by the caret
        self.put("one\ntwo", 5, 5)
        self.button("bullets").click()
        self.assertEqual(self.value(), "one\n- two")

    def test_code_block_for_several_lines(self):
        self.put("a\nb")
        self.button("code").click()
        self.assertEqual(self.value(), "```\na\nb\n```")

    def test_mention_starts_one(self):
        self.put("hello ", 6, 6)
        self.button("mention").click()
        self.assertEqual(self.value(), "hello @")

    def test_keys(self):
        self.put("word", 0, 4)
        self.field.press("Control+b")
        self.assertEqual(self.value(), "**word**")
        self.put("word", 0, 4)
        self.field.press("Control+i")
        self.assertEqual(self.value(), "_word_")
        self.put("word", 0, 4)
        self.field.press("Control+Shift+8")
        self.assertEqual(self.value(), "- word")
        self.put("word", 0, 4)
        self.field.press("Control+Shift+7")
        self.assertEqual(self.value(), "1. word")
        self.put("word", 0, 4)
        self.field.press("Control+Shift+9")
        self.assertEqual(self.value(), "- [ ] word")

    def test_tab_indents_list_items(self):
        self.put("- one\n- two", 8, 8)
        self.field.press("Tab")
        self.assertEqual(self.value(), "- one\n  - two")
        self.field.press("Shift+Tab")
        self.assertEqual(self.value(), "- one\n- two")
        # Elsewhere Tab leaves the field, as it does
        self.put("plain", 0, 0)
        self.field.press("Tab")
        self.assertEqual(self.value(), "plain")
        expect(self.field).not_to_be_focused()

    def test_ctrl_k_is_a_link_in_a_field_and_the_palette_elsewhere(self):
        palette = self.page.locator("dialog[open]")
        self.put("see docs", 4, 8)
        self.field.press("Control+k")
        self.assertEqual(self.value(), "see [docs](url)")
        self.assertEqual(palette.count(), 0)
        # Escape leaves the field, then Ctrl+K opens the palette
        self.field.press("Escape")
        expect(self.field).not_to_be_focused()
        self.page.keyboard.press("Control+k")
        expect(palette).to_be_visible()
        self.assertEqual(self.value(), "see [docs](url)")
        self.assertEqual(self.errors, [])

    def test_the_toolbar_scrolls_on_a_phone(self):
        self.page.set_viewport_size({"width": 320, "height": 600})
        height = self.bar.evaluate("el => el.getBoundingClientRect().height")
        self.assertLess(height, 60)
        self.assertTrue(self.bar.evaluate("el => el.scrollWidth > el.clientWidth"))
        self.assertTrue(
            self.page.evaluate(
                "() => document.documentElement.scrollWidth <= window.innerWidth"
            )
        )


FIXTURES = Path(__file__).parent / "test_fixtures"


class PasteTest(E2ETestCase):
    def setUp(self):
        super().setUp()
        self.page = self.login(
            self.ada, permissions=["clipboard-read", "clipboard-write"]
        )
        self.goto(self.page, reverse("message_new", args=[self.project.pk]))
        self.field = self.page.locator("textarea[name=content]")

    def copy(self, html="", text=""):
        """Puts HTML and text on the clipboard like a page would"""
        self.page.evaluate(
            """async ([html, text]) => {
                const item = {"text/plain": new Blob([text], {type: "text/plain"})}
                if (html) item["text/html"] = new Blob([html], {type: "text/html"})
                await navigator.clipboard.write([new ClipboardItem(item)])
            }""",
            [html, text],
        )

    def paste(self, key="Control+v"):
        self.field.focus()
        self.field.press(key)

    def test_a_mail_keeps_its_formatting(self):
        self.copy((FIXTURES / "paste_mail.html").read_text(), "Hi team, plain")
        self.paste()
        expect(self.field).to_have_value(MAIL)
        self.assertEqual(self.errors, [])

    def test_google_docs(self):
        self.copy((FIXTURES / "paste_google_docs.html").read_text(), "Camp plan")
        self.paste()
        expect(self.field).to_have_value(GOOGLE_DOCS)

    def test_it_goes_where_the_caret_is_and_can_be_undone(self):
        self.field.fill("Before  after")
        self.field.evaluate("el => el.setSelectionRange(7, 7)")
        self.copy("<p>some <b>bold</b></p>", "some bold")
        self.paste()
        expect(self.field).to_have_value("Before some **bold** after")
        self.field.press("Control+z")
        expect(self.field).to_have_value("Before  after")

    def test_plain_text_pastes_as_it_is(self):
        self.copy("", "just *text*\nand more")
        self.paste()
        expect(self.field).to_have_value("just *text*\nand more")

    def test_html_without_formatting_is_left_alone(self):
        # What editors put on the clipboard for code: a div per line
        self.copy(
            "<div style='font-family:monospace'><div><span>a = 1</span></div>"
            "<div><span>b = 2</span></div></div>",
            "a = 1\nb = 2",
        )
        self.paste()
        expect(self.field).to_have_value("a = 1\nb = 2")

    def test_ctrl_shift_v_pastes_plain_text(self):
        self.copy("<p>some <b>bold</b></p>", "some bold")
        self.paste("Control+Shift+v")
        expect(self.field).to_have_value("some bold")

    def test_a_url_over_selected_text_makes_a_link(self):
        self.field.fill("see the docs here")
        self.field.evaluate("el => el.setSelectionRange(4, 12)")
        self.copy("", "https://example.org/docs")
        self.paste()
        expect(self.field).to_have_value(
            "see [the docs](https://example.org/docs) here"
        )
        # Without a selection the URL is pasted as it is
        self.field.fill("")
        self.paste()
        expect(self.field).to_have_value("https://example.org/docs")

    def test_a_failing_endpoint_pastes_the_text(self):
        self.page.route("**/paste/markdown/", lambda route: route.abort())
        self.copy("<p>some <b>bold</b></p>", "some bold")
        self.paste()
        expect(self.field).to_have_value("some bold")
