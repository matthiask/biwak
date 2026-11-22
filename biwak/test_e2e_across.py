"""Copying a list and moving it to another project in the browser: the
project combobox in the modal, the question coming back into the dialog
(htmx), then the page of the copy or the moved list
(specs/lists-across-projects.md)"""

from biwak.items import operations as ops
from biwak.items.models import Item, Kind
from biwak.test_e2e import E2ETestCase, expect
from biwak.test_utils import person, project


class AcrossTest(E2ETestCase):
    def setUp(self):
        super().setUp()
        self.dan = person("Dan", client=True, organization="Example Shop Ltd")
        self.shop = project("Shop", members=[self.ada, self.dan])
        project("Archive drawer", members=[self.ada])
        self.list = ops.create_list(
            project=self.project, title="Launch", creator=self.ada, visible=True
        )
        ops.create_todo(
            todolist=self.list,
            title="Order the tent",
            creator=self.ada,
            assignees=[self.cleo],
        )

    def choose(self, dialog, name, text, option):
        field = dialog.get_by_role("combobox", name=name)
        field.click()
        field.fill(text)
        dialog.get_by_role("option", name=option).click()
        expect(field).to_have_value(option)

    def test_copying_into_another_project(self):
        page = self.page
        self.goto(page, self.list.get_absolute_url())
        page.get_by_text("More", exact=True).click()
        page.get_by_role("link", name="Copy…").click()
        dialog = page.get_by_role("dialog", name="Copy…")
        # This project first
        expect(dialog.get_by_role("combobox", name="Project")).to_have_value("Website")
        self.choose(dialog, "Project", "sho", "Shop")
        dialog.get_by_role("button", name="Copy").click()
        # Asked in the dialog: Cleo isn't in Shop
        expect(dialog.locator("[data-dropped]")).to_contain_text(
            "Cleo Example isn't in Shop: left unassigned."
        )
        expect(dialog.get_by_role("combobox", name="Project")).to_have_value("Shop")
        dialog.get_by_role("button", name="Copy").click()
        expect(dialog).to_be_hidden()
        expect(page.get_by_role("navigation", name="Breadcrumbs")).to_contain_text(
            "Shop"
        )
        copy = Item.objects.get(project=self.shop, kind=Kind.LIST)
        expect(page).to_have_url(f"{self.live_server_url}{copy.get_absolute_url()}")
        expect(page.get_by_text("Order the tent")).to_be_visible()
        self.assertEqual(self.errors, [])

    def test_moving_to_another_project(self):
        page = self.page
        self.goto(page, self.list.get_absolute_url())
        page.get_by_text("More", exact=True).click()
        page.get_by_role("link", name="Move to…").click()
        dialog = page.get_by_role("dialog", name="Move to…")
        self.choose(dialog, "Project", "shop", "Shop")
        dialog.get_by_role("button", name="Move").click()
        expect(dialog.locator("[data-new-clients]")).to_contain_text(
            "visible to 1 client"
        )
        dialog.get_by_role("button", name="Move").click()
        expect(dialog).to_be_hidden()
        expect(page.get_by_role("navigation", name="Breadcrumbs")).to_contain_text(
            "Shop"
        )
        self.list.refresh_from_db()
        self.assertEqual(self.list.project, self.shop)
        self.assertEqual(self.errors, [])
