"""Forms in a modal in the browser (biwak/modals.py, frontend/modal.js):
opening, saving, errors, Escape and the focus"""

from biwak.items.models import Item, Kind
from biwak.test_e2e import E2ETestCase, expect


class ModalTest(E2ETestCase):
    def test_new_list(self):
        page = self.page
        self.goto(page, self.project)
        button = page.get_by_role("link", name="New list")
        button.click()
        dialog = page.get_by_role("dialog", name="New list")
        expect(dialog).to_be_visible()
        expect(dialog.locator("[name=title]")).to_be_focused()
        # No page around the form, and the page's own URL didn't change
        self.assertEqual(dialog.locator("nav").count(), 0)
        self.assertTrue(page.url.endswith(f"/projects/{self.project.pk}/"))

        # Errors: the form again in the dialog
        dialog.locator("[name=title]").fill("   ")
        dialog.get_by_role("button", name="Add list").click()
        expect(dialog.get_by_text("This field is required.")).to_be_visible()
        expect(dialog).to_be_visible()

        dialog.locator("[name=title]").fill("Launch plan")
        dialog.get_by_role("button", name="Add list").click()
        page.wait_for_url("**/lists/*/")
        item = Item.objects.get(kind=Kind.LIST, title="Launch plan")
        self.assertTrue(page.url.endswith(item.get_absolute_url()))
        self.assertEqual(self.errors, [])

    def test_escape_and_the_focus(self):
        """Escape closes an unchanged form, a changed one needs it twice;
        the focus goes back to the link"""
        page = self.page
        self.goto(page, self.project)
        button = page.get_by_role("link", name="New list")
        button.focus()
        button.press("Enter")
        dialog = page.get_by_role("dialog", name="New list")
        expect(dialog).to_be_visible()
        page.keyboard.press("Escape")
        expect(dialog).to_be_hidden()
        expect(button).to_be_focused()

        button.click()
        field = dialog.locator("[name=title]")
        expect(field).to_be_focused()
        field.fill("Half")
        page.keyboard.press("Escape")
        expect(dialog).to_be_visible()
        page.keyboard.press("Escape")
        expect(dialog).to_be_hidden()
        expect(button).to_be_focused()
        self.assertFalse(Item.objects.filter(kind=Kind.LIST).exists())

        # Cancel closes it too
        button.click()
        dialog.get_by_role("button", name="Cancel").click()
        expect(dialog).to_be_hidden()
        self.assertEqual(self.errors, [])

    def test_a_modifier_key_opens_the_page(self):
        page = self.page
        self.goto(page, self.project)
        # A new window, with the form's own page
        with page.context.expect_page() as opened:
            page.get_by_role("link", name="New list").click(modifiers=["Shift"])
        popup = opened.value
        popup.wait_for_load_state()
        self.assertTrue(popup.url.endswith("/lists/new/"))
        expect(popup.get_by_role("heading", name="New list")).to_be_visible()

    def test_the_palette_opens_the_modal(self):
        page = self.page
        self.goto(page, self.project)
        page.keyboard.press("Control+k")
        page.locator("#wb-palette-input").fill("New list")
        page.locator("#wb-palette-list [role=option]").first.press("Enter")
        expect(page.get_by_role("dialog", name="New list")).to_be_visible()
        self.assertEqual(self.errors, [])


class GroupModalsTest(E2ETestCase):
    def test_new_group_and_renaming_it(self):
        todolist = self.make_list(groups=["Later"])
        page = self.page
        self.goto(page, todolist)
        page.get_by_role("link", name="New group").click()
        dialog = page.get_by_role("dialog", name="New group")
        expect(dialog.locator("[name=title]")).to_be_focused()
        dialog.locator("[name=title]").fill("Soon")
        dialog.get_by_role("button", name="Add group").click()
        expect(page.locator(".wb-group-name", has_text="Soon")).to_be_visible()
        expect(dialog).to_be_hidden()

        # The pencil's menu has the modal, which closes the menu
        menu = page.locator("details.wb-menu:has(.wb-group-menu)").first
        menu.locator("summary").click()
        menu.get_by_role("link", name="Rename the group").click()
        dialog = page.get_by_role("dialog", name="Rename the group")
        expect(dialog.locator("[name=title]")).to_have_value("Later")
        self.assertFalse(menu.evaluate("el => el.open"))
        dialog.locator("[name=title]").fill("Next week")
        dialog.get_by_role("button", name="Rename").click()
        expect(page.locator(".wb-group-name", has_text="Next week")).to_be_visible()
        self.assertEqual(
            list(todolist.todolist.groups.values_list("title", flat=True)),
            ["Next week", "Soon"],
        )

        # Escape: the focus goes back to the menu's button
        menu.locator("summary").click()
        menu.get_by_role("link", name="Rename the group").click()
        expect(page.get_by_role("dialog")).to_be_visible()
        page.keyboard.press("Escape")
        expect(page.get_by_role("dialog")).to_be_hidden()
        expect(menu.locator("summary")).to_be_focused()
        self.assertEqual(self.errors, [])
