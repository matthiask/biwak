"""The combobox in front of long selects in the browser
(frontend/combobox.js, specs/ui-round-6.md, part A)"""

import re

from biwak.test_e2e import E2ETestCase, expect
from biwak.test_utils import person


class ComboboxTest(E2ETestCase):
    def test_filtering_and_choosing_with_the_keyboard(self):
        dora = person("Dora", client=True)
        person("Eve", client=True, organization="Other Client Ltd")
        page = self.page
        self.goto(page, f"/projects/{self.project.pk}/people/")
        page.get_by_role("link", name="Add someone").click()
        dialog = page.get_by_role("dialog", name="Add someone")
        field = dialog.get_by_role("combobox", name="Person")
        expect(field).to_be_visible()
        listbox = dialog.get_by_role("listbox")
        expect(listbox).to_be_hidden()

        # A click lists everybody, with their organization
        field.click()
        expect(listbox).to_be_visible()
        expect(
            listbox.get_by_role("option", name="Bob Example · Our organization")
        ).to_be_visible()
        options = listbox.get_by_role("option")
        expect(options.filter(has_text="Example Client Ltd")).to_have_count(1)
        # Words anywhere: the organization and the name, in any order
        field.fill("client dora")
        expect(options).to_have_count(1)
        expect(options).to_have_text("Dora Example · Example Client Ltd")
        # The address finds people too
        field.fill("eve@")
        expect(options).to_have_text("Eve Example · Other Client Ltd")
        field.fill("nobody here")
        expect(options).to_have_count(0)
        expect(listbox).to_contain_text("Nothing found")

        # Escape closes the list, not the dialog
        field.press("Escape")
        expect(listbox).to_be_hidden()
        expect(dialog).to_be_visible()

        # The arrow keys move, Enter chooses without submitting
        field.fill("example client")
        field.press("ArrowDown")
        field.press("ArrowUp")
        expect(options).to_have_count(2)
        expect(options.first).to_have_class(re.compile(r"\bactive\b"))
        field.press("Enter")
        expect(listbox).to_be_hidden()
        expect(field).to_have_value("Dora Example · Example Client Ltd")
        expect(dialog).to_be_visible()
        dialog.get_by_role("button", name="Add").click()
        # The people page again, with Dora
        expect(dialog).to_be_hidden()
        expect(
            page.get_by_role("link", name="Dora Example, Example Client Ltd")
        ).to_be_visible()
        self.assertTrue(self.project.is_member(dora))
        self.assertEqual(self.errors, [])
