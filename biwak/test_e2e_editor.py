"""Task lists, the toolbar and pasting in the browser (specs/editor.md)"""

import time
from pathlib import Path

from django.urls import reverse

from biwak.items import operations as ops
from biwak.items.models import Editing, Message, Todo
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

    def test_a_changed_text_is_loaded_again_and_says_who(self):
        page = self.page
        self.goto(page, self.todo)
        page.evaluate("window.marker = 1")
        ops.update_todo(self.todo, actor=self.bob, notes="- [ ] new one")
        page.locator(".wb-checklist input[type=checkbox]").first.check()
        status = page.locator(".wb-tick-note[role=status]")
        expect(status).to_have_text("Changed by Bob a moment ago.")
        boxes = page.locator(".wb-checklist input[type=checkbox]")
        self.assertEqual(boxes.count(), 1)
        self.assertFalse(boxes.first.is_checked())
        self.assertEqual(self.notes(), "- [ ] new one")
        # No navigation: the page is the same, with the new text
        self.assertEqual(page.evaluate("window.marker"), 1)
        # And ticking works on the new text
        boxes.first.check()
        expect(boxes.first).to_be_enabled()
        self.assertEqual(self.notes(), "- [x] new one")
        self.assertEqual(self.errors, [])

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


class EditingTest(E2ETestCase):
    """Two browsers: one editing, one ticking"""

    def setUp(self):
        super().setUp()
        self.message = ops.create_message(
            project=self.project,
            title="Camp",
            creator=self.ada,
            content=NOTES,
            visible=True,
        )
        self.ticking = self.login(self.bob)
        self.goto(self.ticking, self.message)

    def content(self):
        return Message.objects.get(pk=self.message.pk).content

    def tick(self):
        box = self.ticking.locator(".wb-checklist input[type=checkbox]").first
        box.check()
        return box

    def test_ticks_wait_while_the_edit_form_is_open(self):
        page = self.page
        self.goto(page, reverse("message_edit", args=[self.message.pk]))
        box = self.tick()
        expect(self.ticking.locator(".wb-tick-note[role=status]")).to_have_text(
            "Ada is editing this; try again when they're done."
        )
        expect(box).to_be_enabled()
        self.assertFalse(box.is_checked())
        self.assertEqual(self.content(), NOTES)
        # Cancelling gives the text back
        page.get_by_role("link", name="Cancel").click()
        page.wait_for_url(f"**{self.message.get_absolute_url()}")
        box = self.tick()
        expect(box).to_be_enabled()
        self.assertTrue(box.is_checked())
        self.assertEqual(self.content(), NOTES.replace("[ ] tent", "[x] tent"))
        self.assertEqual(self.errors, [])

    def test_the_to_do_form_announces_itself_when_shown(self):
        todolist = ops.create_list(
            project=self.project, title="Camp", creator=self.ada, visible=True
        )
        todo = ops.create_todo(
            todolist=todolist, title="Pack", creator=self.ada, notes=NOTES
        )
        self.goto(self.ticking, todo)
        self.goto(self.page, todo)
        # Just looking at the to-do doesn't block it
        self.assertFalse(Editing.objects.exists())
        # The form shown in place announces itself
        self.page.get_by_role("link", name="Edit").click()
        expect(self.editor(self.page.locator("textarea[name=notes]"))).to_be_visible()
        for _ in range(50):
            if Editing.objects.filter(item=todo).exists():
                break
            time.sleep(0.1)
        box = self.ticking.locator(".wb-checklist input[type=checkbox]").first
        box.check()
        expect(self.ticking.locator(".wb-tick-note[role=status]")).to_have_text(
            "Ada is editing this; try again when they're done."
        )
        self.assertEqual(Todo.objects.get(pk=todo.pk).notes, NOTES)
        self.assertEqual(self.errors, [])


# Selects the first occurrence of a text in the rich editor (all: the
# whole document)
SELECT = """(el, text) => {
    const view = el.richEditor.view
    const doc = view.state.doc
    let from = 1, to = doc.content.size - 1
    if (text !== null) {
        from = 0
        doc.descendants((node, pos) => {
            if (from || !node.isText) return !from
            const i = node.text.indexOf(text)
            if (i >= 0) { from = pos + i; to = from + text.length }
        })
    }
    const sel = view.state.selection.constructor
    view.dispatch(view.state.tr.setSelection(sel.create(doc, from, to)))
    view.focus()
}"""


class ToolbarTest(E2ETestCase):
    """The toolbar's buttons and keys in the rich editor (specs/editor.md,
    specs/rich-editor.md)"""

    def setUp(self):
        super().setUp()
        self.page.set_viewport_size({"width": 1000, "height": 800})
        self.goto(self.page, reverse("message_new", args=[self.project.pk]))
        self.field = self.page.locator("textarea[name=content]")
        self.box = self.editor(self.field)
        self.bar = self.page.locator(".wb-toolbar")

    def button(self, name):
        return self.bar.locator(f'[data-toolbar-action="{name}"]')

    def put(self, text, selected=None):
        """The editor with this Markdown, ``selected`` (default: all)
        selected"""
        self.set_markdown(self.field, text)
        self.select(selected)

    def select(self, text=None):
        self.field.evaluate(SELECT, text)

    def caret_at_end(self):
        self.box.press("ControlOrMeta+End")

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
            "source",
        ]:
            expect(self.button(name)).to_be_visible()
        # The attach button moved into it, before "Markdown"
        expect(self.bar.locator("button", has_text="Attach")).to_be_visible()
        self.assertEqual(self.page.locator(".wb-toolbar").count(), 1)
        self.assertEqual(
            self.bar.locator("button:visible").last.get_attribute(
                "data-toolbar-action"
            ),
            "source",
        )
        expect(self.field).to_be_hidden()

    def test_inline_buttons_toggle_and_show_what_is_on(self):
        self.put("make this bold", "this")
        self.button("bold").click()
        self.assertEqual(self.value(), "make **this** bold")
        expect(self.button("bold")).to_have_attribute("aria-pressed", "true")
        self.button("bold").click()
        self.assertEqual(self.value(), "make this bold")
        expect(self.button("bold")).to_have_attribute("aria-pressed", "false")
        self.button("italic").click()
        self.assertEqual(self.value(), "make *this* bold")
        self.put("x y", "y")
        self.button("code").click()
        self.assertEqual(self.value(), "x `y`")
        # Nothing selected: what's typed next
        self.put("")
        self.button("bold").click()
        self.box.press_sequentially("loud")
        self.assertEqual(self.value(), "**loud**")

    def test_undo_after_a_button(self):
        self.put("make this bold", "this")
        self.button("bold").click()
        self.assertEqual(self.value(), "make **this** bold")
        self.box.press("ControlOrMeta+z")
        self.assertEqual(self.value(), "make this bold")
        self.box.press("ControlOrMeta+Shift+z")
        self.assertEqual(self.value(), "make **this** bold")

    def test_links(self):
        self.put("see docs", "docs")
        self.button("link").click()
        address = self.page.locator(".wb-link-ask input")
        expect(address).to_be_focused()
        address.fill("https://example.org/docs")
        address.press("Enter")
        self.assertEqual(self.value(), "see [docs](https://example.org/docs)")
        expect(self.box).to_be_focused()
        # On the link: its address to change, empty removes it
        self.select("docs")
        self.box.press("ControlOrMeta+k")
        expect(address).to_have_value("https://example.org/docs")
        address.fill("")
        address.press("Enter")
        self.assertEqual(self.value(), "see docs")
        # Escape keeps it as it was
        self.select("docs")
        self.button("link").click()
        address.press("Escape")
        expect(address).to_have_count(0)
        self.assertEqual(self.value(), "see docs")

    def test_line_buttons(self):
        self.put("one\n\ntwo")
        self.button("bullets").click()
        self.assertEqual(self.value(), "- one\n- two")
        expect(self.button("bullets")).to_have_attribute("aria-pressed", "true")
        self.button("bullets").click()
        self.assertEqual(self.value(), "one\n\ntwo")
        self.button("numbers").click()
        self.assertEqual(self.value(), "1. one\n2. two")
        self.button("tasks").click()
        self.assertEqual(self.value(), "- [ ] one\n- [ ] two")
        self.button("tasks").click()
        self.assertEqual(self.value(), "one\n\ntwo")
        self.button("quote").click()
        self.assertEqual(self.value(), "> one\n>\n> two")
        self.button("quote").click()
        self.assertEqual(self.value(), "one\n\ntwo")
        # The current block only, by the caret
        self.put("one\n\ntwo", "two")
        self.button("heading").click()
        self.assertEqual(self.value(), "one\n\n## two")
        self.button("heading").click()
        self.assertEqual(self.value(), "one\n\ntwo")

    def test_code_block_for_several_blocks(self):
        self.put("a\n\nb")
        self.button("code").click()
        self.assertEqual(self.value(), "```\na\nb\n```")

    def test_mention_starts_one(self):
        self.put("hello")
        self.caret_at_end()
        self.button("mention").click()
        self.assertEqual(self.value(), "hello @")

    def test_keys(self):
        for key, expected in [
            ("ControlOrMeta+b", "**word**"),
            ("ControlOrMeta+i", "*word*"),
            ("ControlOrMeta+Shift+8", "- word"),
            ("ControlOrMeta+Shift+7", "1. word"),
            ("ControlOrMeta+Shift+9", "- [ ] word"),
        ]:
            self.put("word")
            self.box.press(key)
            self.assertEqual(self.value(), expected, key)

    def test_tab_indents_list_items(self):
        self.put("- one\n- two", "two")
        self.box.press("Tab")
        self.assertEqual(self.value(), "- one\n  - two")
        self.box.press("Shift+Tab")
        self.assertEqual(self.value(), "- one\n- two")
        # Elsewhere Tab leaves the field, as it does
        self.put("plain", "plain")
        self.box.press("Tab")
        self.assertEqual(self.value(), "plain")
        expect(self.box).not_to_be_focused()

    def test_ctrl_k_is_a_link_in_a_field_and_the_palette_elsewhere(self):
        palette = self.page.locator("dialog[open]")
        self.put("see docs", "docs")
        self.box.press("ControlOrMeta+k")
        expect(self.page.locator(".wb-link-ask input")).to_be_focused()
        self.assertEqual(palette.count(), 0)
        self.page.keyboard.press("Escape")
        # Escape leaves the field, then Ctrl+K opens the palette
        self.box.press("Escape")
        expect(self.box).not_to_be_focused()
        self.page.keyboard.press("ControlOrMeta+k")
        expect(palette).to_be_visible()
        self.assertEqual(self.value(), "see docs")
        self.assertEqual(self.errors, [])


class TypingTest(E2ETestCase):
    """Enter, Shift+Enter, typing Markdown (specs/rich-editor.md)"""

    def setUp(self):
        super().setUp()
        self.goto(self.page, reverse("message_new", args=[self.project.pk]))
        self.field = self.page.locator("textarea[name=content]")
        self.box = self.editor(self.field)
        self.box.click()

    def type(self, *parts):
        """Types the texts, pressing the keys in between (tuples)"""
        for part in parts:
            if isinstance(part, tuple):
                for key in part:
                    self.box.press(key)
            else:
                self.box.press_sequentially(part)

    def test_enter_and_shift_enter(self):
        self.type("one", ("Enter",), "two", ("Shift+Enter",), "three")
        self.assertEqual(self.field.input_value(), "one\n\ntwo\nthree")

    def test_typing_markdown(self):
        self.type(
            "# Title",
            ("Enter",),
            "Some **bold**, *soft* and `code` ~~gone~~ text",
            ("Enter",),
            "- one",
            ("Enter",),
            "two",
            ("Enter", "Enter"),
            "1. first",
            ("Enter", "Enter"),
            "> quoted",
            ("Enter", "Enter"),
            "```",
            ("Enter",),
            "x = 1",
        )
        self.assertEqual(
            self.field.input_value(),
            "# Title\n\nSome **bold**, *soft* and `code` ~~gone~~ text\n\n"
            "- one\n- two\n\n1. first\n\n> quoted\n\n```\nx = 1\n```",
        )

    def test_task_items(self):
        self.type("- [ ] tent", ("Enter",), "stove")
        self.assertEqual(self.field.input_value(), "- [ ] tent\n- [ ] stove")
        # Its box ticks it
        self.box.locator("input.task-list-item-checkbox").first.click()
        self.assertEqual(self.field.input_value(), "- [x] tent\n- [ ] stove")
        self.type(("Enter", "Enter"), "[ ] alone")
        self.assertEqual(
            self.field.input_value(), "- [x] tent\n- [ ] stove\n\n\n* [ ] alone"
        )

    def test_backspace_takes_a_rule_back(self):
        self.type("- ", ("Backspace",))
        self.assertEqual(self.field.input_value(), "\\- ")

    def test_bare_urls_become_links(self):
        self.type("see www.example.org now")
        link = self.box.locator("a")
        expect(link).to_have_attribute("href", "http://www.example.org")
        expect(link).to_have_text("www.example.org")
        self.assertEqual(self.field.input_value(), "see www.example.org now")

    def test_ctrl_enter_submits(self):
        self.page.locator("[name=title]").fill("Camp")
        self.box.click()
        self.type("Bring a *tent*")
        self.box.press("ControlOrMeta+Enter")
        self.page.wait_for_url("**/messages/*/")
        self.assertEqual(Message.objects.get().content, "Bring a *tent*")
        self.assertEqual(self.errors, [])


class UnchangedTest(E2ETestCase):
    """Texts nobody edited stay as they were (specs/rich-editor.md)"""

    OLD = "Intro with __old__ style\n* a\n* b\n\nEnd"

    def setUp(self):
        super().setUp()
        self.message = ops.create_message(
            project=self.project, title="Camp", creator=self.ada, content=self.OLD
        )
        self.goto(self.page, reverse("message_edit", args=[self.message.pk]))
        self.field = self.page.locator("textarea[name=content]")
        self.box = self.editor(self.field)

    def content(self):
        return Message.objects.get(pk=self.message.pk).content

    def test_saving_unchanged(self):
        self.assertEqual(self.field.input_value(), self.OLD)
        self.box.click()
        self.box.press("ControlOrMeta+End")
        self.box.press_sequentially("x")
        self.box.press("Backspace")
        self.assertEqual(self.field.input_value(), self.OLD)
        self.box.press("ControlOrMeta+Enter")
        self.page.wait_for_url(f"**{self.message.get_absolute_url()}")
        self.assertEqual(self.content(), self.OLD)

    def test_an_edit_keeps_the_other_blocks(self):
        self.box.click()
        self.box.press("ControlOrMeta+End")
        self.box.press_sequentially("ing")
        self.box.press("ControlOrMeta+Enter")
        self.page.wait_for_url(f"**{self.message.get_absolute_url()}")
        self.assertEqual(self.content(), "Intro with __old__ style\n* a\n* b\n\nEnding")

    def test_the_source(self):
        source = self.page.locator('[data-toolbar-action="source"]')
        source.click()
        expect(self.field).to_be_visible()
        expect(self.field).to_be_focused()
        expect(source).to_have_attribute("aria-pressed", "true")
        self.assertEqual(self.field.input_value(), self.OLD)
        # Unchanged there and back: the original
        source.click()
        expect(self.field).to_be_hidden()
        expect(self.box).to_be_focused()
        self.assertEqual(self.field.input_value(), self.OLD)
        # Changed in the source: parsed again
        source.click()
        self.field.fill("Now **bold**\n\n| a | b |\n| --- | --- |\n| 1 | 2 |")
        source.click()
        expect(self.box.locator("strong")).to_have_text("bold")
        expect(self.box.locator("td")).to_have_count(2)
        self.assertEqual(
            self.field.input_value(),
            "Now **bold**\n\n| a | b |\n| --- | --- |\n| 1 | 2 |",
        )
        # The source's toolbar works on the source
        source.click()
        self.field.evaluate("el => el.setSelectionRange(0, 3)")
        self.page.locator('[data-toolbar-action="italic"]').click()
        self.assertTrue(self.field.input_value().startswith("_Now_"))
        self.assertEqual(self.errors, [])


FIXTURES = Path(__file__).parent / "test_fixtures"


class PasteTest(E2ETestCase):
    """Pasting into the rich editor (specs/editor.md, "Pasting")"""

    def setUp(self):
        super().setUp()
        self.page = self.login(
            self.ada, permissions=["clipboard-read", "clipboard-write"]
        )
        self.goto(self.page, reverse("message_new", args=[self.project.pk]))
        self.field = self.page.locator("textarea[name=content]")
        self.box = self.editor(self.field)

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
        self.box.focus()
        self.box.press(key)

    def put(self, text, selected=None):
        self.set_markdown(self.field, text)
        self.field.evaluate(SELECT, selected)

    def test_a_mail_keeps_its_formatting(self):
        self.copy((FIXTURES / "paste_mail.txt").read_text(), "Hi team, plain")
        self.paste()
        # A line starting with "--" is escaped (it could start a list)
        expect(self.field).to_have_value(MAIL.replace("\n--\n", "\n\\--\n"))
        self.assertEqual(self.errors, [])

    def test_google_docs(self):
        self.copy((FIXTURES / "paste_google_docs.txt").read_text(), "Camp plan")
        self.paste()
        expect(self.field).to_have_value(GOOGLE_DOCS)

    def test_it_goes_where_the_caret_is_and_can_be_undone(self):
        self.put("Before after", "after")
        self.box.press("ArrowLeft")
        self.copy("<p>some <b>bold</b></p>", "some bold")
        self.paste()
        expect(self.field).to_have_value("Before some **bold**after")
        self.box.press("ControlOrMeta+z")
        expect(self.field).to_have_value("Before after")

    def test_blocks_go_in_as_blocks(self):
        self.put("Intro")
        self.box.press("ControlOrMeta+End")
        self.copy("<ul><li>one</li><li><b>two</b></li></ul>", "one two")
        self.paste()
        expect(self.field).to_have_value("Intro\n\n- one\n- **two**")

    def test_into_a_list_and_a_table(self):
        self.put("- first\n- second", "second")
        self.copy("<p>more <i>here</i></p>", "more here")
        self.paste()
        expect(self.field).to_have_value("- first\n- more *here*")
        self.put("| a | b |\n| --- | --- |\n| 1 | 2 |", "1")
        self.copy("<p>one <b>x</b></p>", "one x")
        self.paste()
        expect(self.field).to_have_value("| a | b |\n| --- | --- |\n| one **x** | 2 |")

    def test_plain_text_pastes_as_text(self):
        """Not parsed as Markdown: lines are breaks, blank lines paragraphs"""
        self.copy("", "just *text*\nand more\n\nnext")
        self.paste()
        expect(self.field).to_have_value("just \\*text\\*\nand more\n\nnext")

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
        self.put("see the docs here", "the docs")
        self.copy("", "https://example.org/docs")
        self.paste()
        expect(self.field).to_have_value(
            "see [the docs](https://example.org/docs) here"
        )
        # Without a selection the URL is pasted as it is
        self.put("")
        self.paste()
        expect(self.field).to_have_value("https://example.org/docs")

    def test_copying_within_the_editor_keeps_mentions(self):
        self.put(f"Hi [@Bob](person:{self.bob.pk}) **there**")
        self.box.press("ControlOrMeta+a")
        self.box.press("ControlOrMeta+c")
        self.box.press("ControlOrMeta+End")
        self.box.press("Enter")
        self.box.press("ControlOrMeta+v")
        line = f"Hi [@Bob](person:{self.bob.pk}) **there**"
        expect(self.field).to_have_value(f"{line}\n\n{line}")

    def test_a_failing_endpoint_pastes_the_text(self):
        self.page.route("**/paste/markdown/", lambda route: route.abort())
        self.copy("<p>some <b>bold</b></p>", "some bold")
        self.paste()
        expect(self.field).to_have_value("some bold")


def compose(page, steps, final):
    """Composition through Chromium's input method protocol: the texts
    being composed, then the committed one"""
    cdp = page.context.new_cdp_session(page)
    for text in steps:
        cdp.send(
            "Input.imeSetComposition",
            {"text": text, "selectionStart": len(text), "selectionEnd": len(text)},
        )
    cdp.send("Input.insertText", {"text": final})
    cdp.detach()


class CompositionTest(E2ETestCase):
    """Input methods (IME): what Chromium's protocol can simulate of them
    (specs/rich-editor.md, "The code")"""

    def setUp(self):
        super().setUp()
        self.goto(self.page, reverse("message_new", args=[self.project.pk]))
        self.field = self.page.locator("textarea[name=content]")
        self.box = self.editor(self.field)
        self.box.click()

    def test_composing_text(self):
        self.box.press_sequentially("Hello ")
        compose(self.page, ["に", "にほ", "にほん"], "日本")
        self.box.press_sequentially(" and **more**")
        self.assertEqual(self.field.input_value(), "Hello 日本 and **more**")

    def test_composing_in_a_list_and_bold(self):
        self.box.press_sequentially("- ")
        self.box.press("ControlOrMeta+b")
        compose(self.page, ["ü"], "ü")
        compose(self.page, ["さ", "さく"], "作")
        self.assertEqual(self.field.input_value(), "- **ü作**")
        self.assertEqual(self.errors, [])


class TableTest(E2ETestCase):
    """Inserting tables and the table's bar (specs/rich-editor.md,
    "Tables")"""

    def setUp(self):
        super().setUp()
        self.goto(self.page, reverse("message_new", args=[self.project.pk]))
        self.field = self.page.locator("textarea[name=content]")
        self.box = self.editor(self.field)
        self.bar = self.page.locator(".wb-table-bar")

    def action(self, name):
        return self.bar.locator(f'[data-table-action="{name}"]')

    def test_inserting_and_changing_a_table(self):
        self.box.click()
        self.box.press_sequentially("Plan")
        self.box.press("Enter")
        self.page.locator('[data-toolbar-action="table"]').click()
        expect(self.bar).to_be_visible()
        expect(self.bar).to_have_attribute("role", "toolbar")
        self.box.press_sequentially("Day")
        self.assertEqual(
            self.field.input_value(), "Plan\n\n| Day |  |\n| --- | --- |\n|  |  |"
        )
        # In the header row: no deleting it, no row above it
        expect(self.action("delete-row")).to_have_attribute("aria-disabled", "true")
        expect(self.action("row-above")).to_have_attribute("aria-disabled", "true")
        self.action("delete-row").click(force=True)
        self.action("row-below").click()
        self.action("column-right").click()
        self.action("align-right").click()
        expect(self.action("align-right")).to_have_attribute("aria-pressed", "true")
        self.assertEqual(
            self.field.input_value(),
            "Plan\n\n| Day |  |  |\n| ---: | --- | --- |\n|  |  |  |\n|  |  |  |",
        )
        self.action("align-right").click()
        expect(self.action("align-right")).to_have_attribute("aria-pressed", "false")
        self.action("delete-table").click()
        expect(self.bar).to_be_hidden()
        self.assertEqual(self.field.input_value(), "Plan")
        self.assertEqual(self.errors, [])

    def test_the_bar_by_keyboard(self):
        self.set_markdown(self.field, "| a | b |\n| --- | --- |\n| 1 | 2 |")
        self.box.locator("td").first.click()
        expect(self.bar).to_be_visible()
        # Alt+F10 goes to the bar, the arrows move
        self.box.press("Alt+F10")
        first = self.action("row-above")
        expect(first).to_be_focused()
        self.page.keyboard.press("ArrowRight")
        expect(self.action("row-below")).to_be_focused()
        self.page.keyboard.press("Enter")
        self.assertEqual(
            self.field.input_value(), "| a | b |\n| --- | --- |\n| 1 | 2 |\n|  |  |"
        )
        expect(self.bar).to_be_visible()
        self.page.keyboard.press("End")
        expect(self.action("align-right")).to_be_focused()
        self.page.keyboard.press("Escape")
        expect(self.box).to_be_focused()
        # Back where it was
        self.box.press("Alt+F10")
        expect(self.action("align-right")).to_be_focused()
        self.page.keyboard.press("Escape")
        # Tab leaves the field as everywhere, past the bar
        self.box.press("Tab")
        expect(self.box).not_to_be_focused()
        for button in self.bar.locator("button").all():
            expect(button).not_to_be_focused()
        # Out of the table: no bar
        self.box.press("ControlOrMeta+Home")
        self.set_markdown(self.field, "Text only")
        expect(self.bar).to_be_hidden()

    def test_the_source_gets_a_table_too(self):
        self.set_markdown(self.field, "Plan")
        self.page.locator('[data-toolbar-action="source"]').click()
        self.field.evaluate("el => el.setSelectionRange(4, 4)")
        self.page.locator('[data-toolbar-action="table"]').click()
        self.assertEqual(
            self.field.input_value(), "Plan\n\n|  |  |\n| --- | --- |\n|  |  |\n"
        )


class PasteMarkdownTest(E2ETestCase):
    """Plain text that is clearly Markdown is parsed when pasted
    (specs/rich-editor.md); detect.test.js has the detection's cases"""

    def setUp(self):
        super().setUp()
        self.page = self.login(
            self.ada, permissions=["clipboard-read", "clipboard-write"]
        )
        self.goto(self.page, reverse("message_new", args=[self.project.pk]))
        self.field = self.page.locator("textarea[name=content]")
        self.box = self.editor(self.field)

    def paste(self, text, key="Control+v"):
        self.page.evaluate("text => navigator.clipboard.writeText(text)", text)
        self.box.focus()
        self.box.press(key)

    def test_markdown_is_parsed_and_undo_makes_it_text(self):
        self.paste("## Packing\n\n- tent\n- stove")
        expect(self.box.locator("h2")).to_have_text("Packing")
        expect(self.field).to_have_value("## Packing\n\n- tent\n- stove")
        self.box.press("ControlOrMeta+z")
        expect(self.box.locator("h2")).to_have_count(0)
        expect(self.field).to_have_value("\\## Packing\n\n\\- tent\n\\- stove")
        self.box.press("ControlOrMeta+z")
        expect(self.field).to_have_value("")

    def test_a_table_and_links(self):
        self.paste("| a | b |\n| :--- | --- |\n| 1 | 2 |")
        expect(self.box.locator("table")).to_have_count(1)
        self.box.press("ControlOrMeta+End")
        self.paste("See [the plan](https://example.org/plan).")
        expect(self.box.locator("a")).to_have_text("the plan")

    def test_code_and_mails_stay_text(self):
        self.paste("# set up\nx = pitch(tent)")
        expect(self.box.locator("h1")).to_have_count(0)
        expect(self.field).to_have_value("\\# set up\nx = pitch(tent)")
        self.set_markdown(self.field, "")
        self.paste("Hi,\n* the tent is ordered\nBob")
        expect(self.box.locator("ul")).to_have_count(0)

    def test_ctrl_shift_v_is_always_text(self):
        self.paste("- tent\n- stove", key="Control+Shift+v")
        expect(self.box.locator("ul")).to_have_count(0)
