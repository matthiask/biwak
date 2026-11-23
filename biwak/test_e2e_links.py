"""Links (bookmarks) in the browser"""

from biwak.bookmarks.models import Link
from biwak.items.models import Item, Kind
from biwak.test_e2e import E2ETestCase, expect


class LinksTest(E2ETestCase):
    def test_dragging_the_lists_of_a_project(self):
        self.make_list("First")
        self.make_list("Second")
        page = self.page
        self.goto(page, self.project)
        with page.expect_response("**/lists/order/"):
            page.locator("[data-sortable-item]", has_text="Second").locator(
                "[data-sortable-handle]"
            ).drag_to(
                page.locator("[data-sortable-item]", has_text="First"),
                target_position={"x": 40, "y": 3},
            )
        self.assertEqual(
            list(
                Item.objects
                .filter(project=self.project, kind=Kind.LIST)
                .order_by("position", "pk")
                .values_list("title", flat=True)
            ),
            ["Second", "First"],
        )
        self.assertEqual(self.errors, [])

    def test_adding_and_dragging_links(self):
        page = self.page
        self.goto(page, self.project)
        for url, title in [
            ("https://example.com/one", "One"),
            ("https://example.com/two", "Two"),
        ]:
            page.get_by_role("link", name="Add a link").click()
            dialog = page.locator("dialog#modal")
            expect(dialog).to_be_visible()
            dialog.get_by_label("URL").fill(url)
            dialog.get_by_label("Title").fill(title)
            dialog.get_by_role("button", name="Add").click()
            page.locator("[data-sortable-item]", has_text=title).wait_for()
            expect(page.locator("dialog#modal[open]")).to_have_count(0)
            self.wait_for_sortables(page)
        self.assertEqual(
            list(Link.objects.order_by("position").values_list("title", flat=True)),
            ["One", "Two"],
        )

        with page.expect_response("**/links/order/"):
            page.locator("[data-sortable-item]", has_text="Two").locator(
                "[data-sortable-handle]"
            ).drag_to(
                page.locator("[data-sortable-item]", has_text="One"),
                target_position={"x": 5, "y": 5},
            )
        self.assertEqual(
            list(Link.objects.order_by("position").values_list("title", flat=True)),
            ["Two", "One"],
        )
        self.assertEqual(self.errors, [])
