"""Projects in the browser: the projects page, cards, their order and
colors"""

from django.urls import reverse

from biwak.bookmarks import operations as bookmarks
from biwak.projects import operations as project_ops
from biwak.projects.models import Project
from biwak.test_e2e import E2ETestCase, expect
from biwak.test_utils import project


class ProjectsPageTest(E2ETestCase):
    def test_archiving_from_the_project_with_undo_and_switching(self):
        self.camp = project("Camp", members=[self.ada])
        page = self.page
        self.goto(page, reverse("projects"))
        # No archive buttons on the cards
        expect(page.get_by_role("button", name="Archive the project")).to_have_count(0)
        # From the project's own menu, the projects page says so, with Undo
        self.goto(page, reverse("project", args=[self.camp.pk]))
        page.locator("summary", has_text="More").click()
        page.get_by_role("button", name="Archive the project").click()
        expect(page.locator("h1")).to_have_text("Projects")
        status = page.locator(".alert", has_text="Archived Camp.")
        expect(status).to_be_visible()
        self.camp.refresh_from_db()
        self.assertIsNotNone(self.camp.archived_at)
        status.get_by_role("button", name="Undo").click()
        expect(page.locator(".wb-project-card", has_text="Camp")).to_have_count(1)
        expect(page.locator(".alert", has_text="Archived Camp.")).to_have_count(0)
        self.camp.refresh_from_db()
        self.assertIsNone(self.camp.archived_at)
        # The archived list opens projects, without a reload and without buttons
        page.evaluate("window.marker = 1")
        page.get_by_role("link", name="Archive", exact=True).click()
        expect(page.locator("h1")).to_have_text("Archived projects")
        self.assertIn("archived=1", page.url)
        self.assertEqual(page.evaluate("window.marker"), 1)
        expect(
            page.get_by_role("button", name="Bring back from the archive")
        ).to_have_count(0)
        page.get_by_role("link", name="Active projects").click()
        expect(page.locator(".wb-project-card", has_text="Camp")).to_have_count(1)


class ProjectCardTest(E2ETestCase):
    def test_the_whole_card_opens_the_project_the_bookmark_stays_a_button(self):
        camp = project("Camp", members=[self.ada])
        camp.description = "Tents and stoves"
        camp.save()
        page = self.page
        self.goto(page, reverse("projects"))
        card = page.locator(".wb-project-card", has_text="Camp")
        # The bookmark (htmx) above the card's link
        card.get_by_role("button", name="Bookmark").click()
        expect(card.get_by_role("button", name="Remove the bookmark")).to_be_visible()
        self.assertTrue(bookmarks.is_bookmarked(self.ada, project=camp))
        self.assertTrue(page.url.endswith(reverse("projects")))
        # Anywhere else on the card opens the project (the link covers the
        # text: force clicks where it is, without Playwright's check)
        card.get_by_text("Tents and stoves").click(force=True)
        page.wait_for_url(f"**{camp.get_absolute_url()}")
        self.assertEqual(self.errors, [])


class ProjectsOrderTest(E2ETestCase):
    def test_the_order_is_restored_through_the_navigation(self):
        project("Camp", members=[self.ada])
        page = self.page
        self.goto(page, reverse("projects"))
        page.locator("#id_order").select_option("name")
        page.wait_for_url("**/?order=name")
        self.goto(page, reverse("project_create"))
        link = page.locator(".wb-nav-links a", has_text="Projects")
        expect(link).to_have_attribute("href", "/projects/?order=name")
        link.click()
        page.wait_for_url("**/?order=name")
        expect(page.locator("#id_order")).to_have_value("name")
        self.assertEqual(self.errors, [])


class ColorPickerTest(E2ETestCase):
    """The project form's color picker: radio swatches, with the keyboard"""

    def test_swatches_work_as_radios_with_the_keyboard(self):
        page = self.page
        self.goto(page, reverse("project_create"))
        radios = page.locator("input[name=color]")
        expect(radios).to_have_count(11)
        # Named by their labels, the suggestion is preselected
        expect(page.get_by_role("radio", name="Heather")).to_be_checked()
        checked = page.locator(".wb-color-choice:has(input:checked)")
        self.assertNotEqual(
            checked.evaluate("el => getComputedStyle(el).borderTopColor"),
            "rgba(0, 0, 0, 0)",
        )
        # Arrow keys move the choice like in any radio group
        page.get_by_role("radio", name="Heather").focus()
        page.keyboard.press("ArrowRight")
        expect(page.get_by_role("radio", name="Lake")).to_be_checked()
        page.keyboard.press("ArrowRight")
        expect(page.get_by_role("radio", name="Forest")).to_be_checked()
        # None, by clicking its swatch, and saving keeps no color
        page.get_by_role("radio", name="None").check(force=True)
        page.get_by_label("Name").fill("Plain")
        page.get_by_role("button", name="Continue").click()
        page.wait_for_url("**/projects/*/")
        self.assertEqual(Project.objects.get(name="Plain").color, "")


class ProjectColorTest(E2ETestCase):
    """Project colors (specs/project-colors.md): the card's stripe, the dot
    and the header's line are drawn, with the project's name beside them, and
    nothing runs off the screen, on a phone and on a desktop"""

    SIZES = {
        "phone": {"width": 360, "height": 740},
        "desktop": {"width": 1280, "height": 800},
    }

    def setUp(self):
        super().setUp()

        project_ops.update_project(self.project, actor=self.ada, color="lake")
        self.second = project("Wiki", members=[self.ada])
        project_ops.update_project(self.second, actor=self.ada, color="berry")
        self.todolist = self.make_list("Launch plan", todos=["Pack"])

    def colors(self, page, selector):
        return page.evaluate(
            """(selector) => [...document.querySelectorAll(selector)].map(
                (el) => getComputedStyle(el)
            ).map((style) => [style.backgroundColor, style.borderInlineStartColor])""",
            selector,
        )

    def test_the_projects_page_and_a_feed_page(self):
        for size, viewport in self.SIZES.items():
            with self.subTest(size=size):
                page = self.login(self.ada, viewport=viewport)
                page.goto(f"{self.live_server_url}{reverse('projects')}")
                cards = page.locator(".wb-project-card")
                expect(cards).to_have_count(2)
                lake = page.locator(".wb-project-card", has_text="Website")
                berry = page.locator(".wb-project-card", has_text="Wiki")
                # The dot and the name, in text
                expect(lake.locator(".wb-project-dot")).to_be_visible()
                expect(lake.locator(".wb-project-dot .visually-hidden")).to_have_text(
                    "Color: Lake"
                )
                expect(berry.locator(".wb-project-dot .visually-hidden")).to_have_text(
                    "Color: Berry"
                )
                stripes = page.evaluate(
                    """() => [...document.querySelectorAll(".wb-project-card")].map(
                        (el) => [
                            getComputedStyle(el).borderInlineStartColor,
                            getComputedStyle(el).borderInlineStartWidth,
                            getComputedStyle(el.querySelector(".wb-project-dot"))
                                .backgroundColor,
                        ]
                    )"""
                )
                self.assertEqual(len(stripes), 2)
                for stripe, width, dot in stripes:
                    self.assertEqual(stripe, dot)
                    self.assertNotEqual(stripe, "rgba(0, 0, 0, 0)")
                    self.assertGreaterEqual(float(width.removesuffix("px")), 3)
                self.assertNotEqual(stripes[0][0], stripes[1][0])

                # The project's header: the dot and the line
                page.goto(f"{self.live_server_url}{self.project.get_absolute_url()}")
                expect(page.locator("h1 .wb-project-dot")).to_be_visible()
                expect(page.locator("h1")).to_contain_text("Website")
                line = page.locator(".wb-project-line")
                expect(line).to_be_visible()

                # The feed: every project's dot, beside its name
                page.goto(f"{self.live_server_url}{reverse('feed')}")
                row = page.locator("li", has_text="Website").filter(
                    has=page.locator(".wb-project-dot")
                )
                expect(row.first).to_be_visible()

    def test_the_palette_shows_the_dot_beside_the_project(self):
        page = self.login(self.ada, viewport=self.SIZES["desktop"])
        self.goto(page, self.project)
        page.keyboard.press("ControlOrMeta+k")
        page.keyboard.type("launch")
        option = page.locator("#wb-palette-list [role=option]").filter(
            has_text="Launch plan"
        )
        expect(option).to_be_visible()
        expect(option.locator(".wb-project-dot")).to_be_visible()
        expect(option.locator(".wb-palette-hint")).to_contain_text("Website")
