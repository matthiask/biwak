"""Public links in the browser (specs/public-links.md): the "Share…" modal
creating, copying and stopping in the dialog, Escape with its two forms,
and stopping in place on the page of all public links"""

from biwak.items import operations as ops
from biwak.public_links import operations as link_ops
from biwak.public_links.models import PublicLink
from biwak.test_e2e import E2ETestCase, expect


class PublicLinksTest(E2ETestCase):
    def setUp(self):
        super().setUp()
        self.todolist = ops.create_list(
            project=self.project, title="Gear", creator=self.ada
        )
        self.todo = ops.create_todo(
            todolist=self.todolist, title="Pitch the tent", creator=self.ada
        )

    def open_share(self):
        page = self.page
        self.goto(page, self.todo)
        page.locator("summary", has_text="More").click()
        page.get_by_role("link", name="Share…").click()
        dialog = page.get_by_role("dialog", name="Share “Pitch the tent”")
        expect(dialog).to_be_visible()
        return dialog

    def test_create_copy_and_stop_in_the_dialog(self):
        page = self.page
        page.context.grant_permissions(
            ["clipboard-read", "clipboard-write"], origin=self.live_server_url
        )
        dialog = self.open_share()
        dialog.get_by_label("Expires after").select_option("3")
        dialog.get_by_role("button", name="Create public link").click()
        field = dialog.locator("#public-link")
        expect(field).to_be_focused()
        link = PublicLink.objects.get()
        self.assertTrue(field.input_value().endswith(f"/p/{link.token}/"))
        # Still on the item's page, the dialog open
        self.assertTrue(page.url.endswith(self.todo.get_absolute_url()))
        dialog.locator("[data-copy='#public-link']").click()
        page.wait_for_function(
            "url => navigator.clipboard.readText().then(text => text === url)",
            arg=field.input_value(),
        )
        dialog.get_by_role("button", name="Stop sharing").click()
        expect(dialog.locator("#public-link")).to_have_count(0)
        expect(dialog).to_be_visible()
        self.assertFalse(PublicLink.objects.exists())
        self.assertEqual(self.errors, [])

    def test_escape_sees_the_changed_expiry(self):
        """With a live link the dialog has two forms: changing the second
        one's expiry still needs Escape twice"""
        link_ops.create_public_link(self.todo, days=7, actor=self.ada)
        dialog = self.open_share()
        dialog.get_by_label("Expires after").select_option("30")
        dialog.get_by_label("Expires after").press("Escape")
        expect(dialog).to_be_visible()
        dialog.get_by_label("Expires after").press("Escape")
        expect(dialog).to_be_hidden()
        self.assertEqual(self.errors, [])

    def test_stop_in_place_on_the_page_of_all_public_links(self):
        page = self.page
        message = ops.create_message(
            project=self.project, title="Route", creator=self.ada
        )
        link_ops.create_public_link(self.todo, days=1, actor=self.ada)
        link_ops.create_public_link(message, days=30, actor=self.ada)
        self.goto(page, "/public-links/")
        rows = page.locator("[data-public-link]")
        expect(rows).to_have_count(2)
        rows.first.get_by_role("button", name="Stop sharing").click()
        expect(rows).to_have_count(1)
        expect(rows.first).to_contain_text("Route")
        self.assertTrue(page.url.endswith("/public-links/"))
        self.assertEqual(
            list(PublicLink.objects.values_list("item", flat=True)), [message.pk]
        )
        rows.first.get_by_role("button", name="Stop sharing").click()
        expect(page.get_by_text("Nothing is shared publicly.")).to_be_visible()
        self.assertEqual(self.errors, [])

    def test_the_public_page_without_a_session(self):
        link = link_ops.create_public_link(self.todo, days=7, actor=self.ada)
        page = self.browser.new_context()
        self.contexts.append(page)
        tab = page.new_page()
        errors = []
        tab.on("pageerror", lambda exc: errors.append(str(exc)))
        tab.goto(f"{self.live_server_url}/p/{link.token}/")
        expect(tab.get_by_role("heading", name="Pitch the tent")).to_be_visible()
        self.assertEqual(errors, [])
