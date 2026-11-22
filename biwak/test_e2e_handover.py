"""Selecting to-dos and assigning them at once in the browser
(frontend/select-rows.js, specs/handover.md): Ctrl- and Shift-click, x and
Shift+arrows, Shift+x completing, the bar and the "Assign…" modal"""

import re

from biwak.items import operations as ops
from biwak.items.models import Item
from biwak.test_e2e import E2ETestCase, expect


SELECTED = re.compile(r"\bis-selected\b")


class SelectingTodosTest(E2ETestCase):
    def setUp(self):
        super().setUp()
        self.todolist = self.make_list(
            "Launch",
            visible=True,
            groups=["Later"],
            todos=["One", "Two", "Three", ("Four", "Later")],
        )

    def row(self, page, title):
        return page.locator("[data-select-row]", has_text=title)

    def todo(self, title):
        return Item.objects.get(title=title)

    def test_the_mouse_on_a_list(self):
        page = self.page
        self.goto(page, self.todolist)
        bar = page.locator("[data-row-selection-bar]")
        expect(bar).to_be_hidden()
        title = self.row(page, "One").locator("[data-kb-open]")
        title.click(modifiers=["ControlOrMeta"])
        expect(bar).to_contain_text("1 selected")
        expect(self.row(page, "One")).to_have_class(SELECTED)
        # Shift-click: the range from the last one, across groups
        self.row(page, "Four").locator("[data-kb-open]").click(modifiers=["Shift"])
        expect(bar).to_contain_text("4 selected")
        # Ctrl-click takes one out; still on the page
        self.row(page, "Two").locator("[data-kb-open]").click(
            modifiers=["ControlOrMeta"]
        )
        expect(bar).to_contain_text("3 selected")
        self.assertTrue(page.url.endswith(self.todolist.get_absolute_url()))
        # Escape deselects
        page.keyboard.press("Escape")
        expect(bar).to_be_hidden()
        # So does "Deselect"
        title.click(modifiers=["ControlOrMeta"])
        bar.get_by_role("button", name="Deselect").click()
        expect(bar).to_be_hidden()
        expect(page.locator(".is-selected")).to_have_count(0)
        # A plain click opens the to-do as always
        title.click()
        page.wait_for_url(f"**{self.todo('One').get_absolute_url()}")
        self.assertEqual(self.errors, [])

    def test_grips_count_too(self):
        """Clicking grips selects for dragging with the same class: the bar
        counts them, and clicking the bar doesn't deselect them"""
        page = self.page
        self.goto(page, self.todolist)
        bar = page.locator("[data-row-selection-bar]")
        self.row(page, "One").locator("[data-handle]").click()
        expect(bar).to_contain_text("1 selected")
        bar.locator("[data-selection-count]").click()
        expect(bar).to_contain_text("1 selected")
        page.keyboard.press("Escape")
        expect(bar).to_be_hidden()
        expect(page.locator(".is-selected")).to_have_count(0)

    def test_the_keyboard(self):
        page = self.page
        self.goto(page, self.todolist)
        bar = page.locator("[data-row-selection-bar]")
        page.keyboard.press("j")
        page.keyboard.press("x")
        expect(bar).to_contain_text("1 selected")
        expect(self.row(page, "One")).to_have_class(SELECTED)
        page.keyboard.press("x")
        expect(bar).to_be_hidden()
        # Shift with the arrows selects on
        page.keyboard.press("x")
        page.keyboard.press("Shift+ArrowDown")
        page.keyboard.press("Shift+ArrowDown")
        expect(bar).to_contain_text("3 selected")
        expect(page.locator(".wb-kb-current")).to_contain_text("Three")
        page.keyboard.press("Shift+ArrowUp")
        expect(bar).to_contain_text("2 selected")
        # x didn't complete anything; Shift+x does
        self.assertFalse(self.todo("One").todo.is_completed)
        with page.expect_navigation():
            page.keyboard.press("Shift+x")
        self.assertTrue(self.todo("Two").todo.is_completed)
        self.assertEqual(self.errors, [])

    def test_assigning_on_the_todos_page(self):
        page = self.page
        self.goto(page, "/todos/?assignee=anybody")
        bar = page.locator("[data-row-selection-bar]")
        self.row(page, "One").locator("[data-kb-open]").click(
            modifiers=["ControlOrMeta"]
        )
        self.row(page, "Three").locator("[data-kb-open]").click(modifiers=["Shift"])
        expect(bar).to_contain_text("3 selected")
        bar.get_by_role("link", name="Assign…").click()
        dialog = page.get_by_role("dialog", name="Assign…")
        expect(dialog).to_contain_text("3 to-dos")
        dialog.locator(".wb-picker-input").click()
        dialog.locator(".wb-picker-list li", has_text="Cleo").click()
        dialog.get_by_role("button", name="Assign").click()
        expect(self.row(page, "One")).to_contain_text("Cleo")
        self.assertTrue(page.url.endswith("/todos/?assignee=anybody"))
        for title in ["One", "Two", "Three"]:
            self.assertEqual(list(self.todo(title).todo.assignees.all()), [self.cleo])
        self.assertEqual(list(self.todo("Four").todo.assignees.all()), [])
        self.assertEqual(self.errors, [])

    def test_a_client_assigns_too(self):
        page = self.login(self.cleo)
        self.goto(page, self.todolist)
        page.keyboard.press("j")
        page.keyboard.press("x")
        page.keyboard.press("Shift+ArrowDown")
        bar = page.locator("[data-row-selection-bar]")
        expect(bar).to_contain_text("2 selected")
        bar.get_by_role("link", name="Assign…").click()
        dialog = page.get_by_role("dialog", name="Assign…")
        expect(dialog).to_contain_text("2 to-dos")
        expect(
            dialog.get_by_label("Instead of the current assignees")
        ).not_to_be_checked()

    def test_on_the_board(self):
        ops.update_list(self.todolist, actor=self.ada, view="board")
        page = self.page
        self.goto(page, self.todolist)
        bar = page.locator("[data-row-selection-bar]")
        self.row(page, "One").locator("[data-kb-open]").click(
            modifiers=["ControlOrMeta"]
        )
        self.row(page, "Four").locator("[data-kb-open]").click(
            modifiers=["ControlOrMeta"]
        )
        expect(bar).to_contain_text("2 selected")
