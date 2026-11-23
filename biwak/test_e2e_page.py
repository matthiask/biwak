"""The page shell in the browser: layout, phones, menus, the
navigation's search, htmx, keyboard shortcuts, filters and the home page"""

import re

from django.urls import reverse

from biwak import schedules, test_e2e_modals
from biwak.accounts.models import CalendarToken
from biwak.items import operations as ops
from biwak.items.models import Comment, Item
from biwak.projects import operations as project_ops
from biwak.test_e2e import E2ETestCase, emoji_rows, expect


class PageTest(E2ETestCase):
    def test_menu(self):
        page = self.page
        self.goto(page, self.project)
        menu = page.locator("details.wb-menu").first
        menu.locator("summary").click()
        self.assertTrue(menu.evaluate("el => el.open"))
        page.locator("h1").first.click()
        self.assertFalse(menu.evaluate("el => el.open"))
        menu.locator("summary").click()
        page.keyboard.press("Escape")
        # Escape from within the menu (focus on its summary)
        menu.locator("summary").focus()
        menu.locator("summary").press("Escape")
        self.assertFalse(menu.evaluate("el => el.open"))
        expect(menu.locator("summary")).to_be_focused()

    def test_disclosures_close_like_menus(self):
        """The reaction picker closes with a click elsewhere and with Escape"""
        todo = self.make_list(todos=["Plan"])
        todo = Item.objects.get(title="Plan")
        page = self.page
        self.goto(page, todo)
        picker = page.locator("details.wb-reaction-add").first
        picker.locator("summary").click()
        self.assertTrue(picker.evaluate("el => el.open"))
        # Empty space: the to-do's heading opens the form (view mode)
        page.mouse.click(2, page.viewport_size["height"] - 2)
        self.assertFalse(picker.evaluate("el => el.open"))
        picker.locator("summary").click()
        picker.locator("input[type=text]").focus()
        picker.locator("input[type=text]").press("Escape")
        self.assertFalse(picker.evaluate("el => el.open"))
        expect(picker.locator("summary")).to_be_focused()

    def test_theme(self):
        page = self.page
        self.goto(page, self.project)
        toggle = page.locator("[data-theme-toggle]")
        html = page.locator("html")
        self.assertEqual(toggle.get_attribute("title"), "Theme: Auto")
        shown = toggle.locator("[data-theme-icon]:not([hidden])")
        self.assertEqual(shown.get_attribute("data-theme-icon"), "auto")
        toggle.click()
        self.assertEqual(html.get_attribute("data-bs-theme"), "light")
        self.assertEqual(toggle.get_attribute("title"), "Theme: Light")
        self.assertEqual(shown.get_attribute("data-theme-icon"), "light")
        toggle.click()
        self.assertEqual(html.get_attribute("data-bs-theme"), "dark")
        # Saved for the person, not the browser (it follows them)
        self.wait_for_theme("dark")
        self.assertIsNone(page.evaluate("localStorage.getItem('theme')"))
        # Remembered on the next page, before it renders
        page.reload()
        self.assertEqual(html.get_attribute("data-bs-theme"), "dark")
        toggle.click()
        self.assertEqual(toggle.get_attribute("title"), "Theme: Auto")
        self.wait_for_theme("auto")

    def wait_for_theme(self, theme):
        self.page.wait_for_function(
            "theme => fetch('/api/v1/me/').then(r => r.json()).then(m => m.theme === theme)",
            arg=theme,
        )

    def test_copy(self):
        CalendarToken.renew(self.ada)
        self.page.context.grant_permissions(
            ["clipboard-read", "clipboard-write"], origin=self.live_server_url
        )
        self.goto(self.page, reverse("calendar_link"))
        field = self.page.locator("#calendar-url")
        self.page.locator("[data-copy]").first.click()
        self.page.wait_for_function(
            "url => navigator.clipboard.readText().then(text => text === url)",
            arg=field.input_value(),
        )
        self.assertEqual(self.errors, [])


class PhoneTest(E2ETestCase):
    """What runs off the edge of a phone's screen"""

    def setUp(self):
        super().setUp()
        self.page = self.login(self.ada, viewport={"width": 360, "height": 740})
        self.todolist = self.make_list(todos=["Plan"])
        self.todo = Item.objects.get(title="Plan")

    def phone(self, width=390):
        return self.login(self.ada, viewport={"width": width, "height": 800})

    def test_the_reaction_picker_stays_on_the_screen(self):
        from biwak.reactions import operations as reaction_ops

        # Enough reactions to push the button to the right
        for word in ["Looks good", "On it", "Thanks a lot", "Agreed"]:
            reaction_ops.add_reaction(self.ada, word, item=self.todo)
        self.goto(self.page, self.todo)
        reactions = self.page.locator(".wb-reactions").first
        reactions.locator(".wb-reaction-add summary").click()
        box = reactions.locator(".wb-reaction-picker").bounding_box()
        self.assertGreaterEqual(box["x"], 0)
        self.assertLessEqual(box["x"] + box["width"], 360)
        self.assertEqual(
            emoji_rows(reactions.locator(".wb-reaction-quick")), [8, 8, 8, 8]
        )


class MenuPlacementTest(E2ETestCase):
    """Menus stay on the screen however far from its edge the button is"""

    def settle(self, page):
        # The toggle event comes after the click
        page.evaluate(
            "new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))"
        )

    def assertMenuFits(self, page, menu):
        menu.locator("summary").click()
        popup = menu.locator(".dropdown-menu")
        expect(popup).to_be_visible()
        self.settle(page)
        box = popup.bounding_box()
        width = page.evaluate("document.documentElement.clientWidth")
        self.assertGreaterEqual(box["x"], 0, box)
        self.assertLessEqual(box["x"] + box["width"], width, box)

    def test_menus_fit_on_phones_and_desktops(self):
        todolist = self.make_list(groups=["Phase one"], todos=[("Plan", "Phase one")])
        for width in [360, 280, 1280]:
            with self.subTest(width=width):
                page = self.login(self.ada, viewport={"width": width, "height": 740})
                self.goto(page, self.project)
                menus = page.locator("details.wb-menu")
                self.assertMenuFits(
                    page,
                    page.locator(".wb-page-header details.wb-menu").filter(
                        has_text="More"
                    ),
                )
                self.assertMenuFits(page, menus.filter(has_text="Ada"))
                self.goto(page, todolist)
                self.assertMenuFits(
                    page, page.locator("details.wb-menu:has(.wb-group-menu)")
                )

    def test_menu_follows_a_resize(self):
        self.page = self.login(self.ada, viewport={"width": 1280, "height": 740})
        self.goto(self.page, self.project)
        menu = self.page.locator(".wb-page-header details.wb-menu").filter(
            has_text="More"
        )
        self.assertMenuFits(self.page, menu)
        self.page.set_viewport_size({"width": 360, "height": 740})
        self.page.wait_for_function(
            """() => document.querySelector(
                "details.wb-menu[open] > .dropdown-menu"
            ).getBoundingClientRect().left >= 0"""
        )

    def test_menu_by_keyboard(self):
        self.page = self.login(self.ada, viewport={"width": 360, "height": 740})
        self.goto(self.page, self.project)
        menu = self.page.locator(".wb-page-header details.wb-menu").filter(
            has_text="More"
        )
        menu.locator("summary").focus()
        self.page.keyboard.press("Enter")
        popup = menu.locator(".dropdown-menu")
        expect(popup).to_be_visible()
        self.settle(self.page)
        self.assertGreaterEqual(popup.bounding_box()["x"], 0)


class NavSearchTest(E2ETestCase):
    def check(self, page, *, hint_visible):
        self.goto(page, self.project)
        button = page.locator("[data-palette-open]")
        expect(button).to_be_visible()
        expect(button).to_have_accessible_name(re.compile(r"^Search or jump to…"))
        self.assertEqual(page.locator(".wb-nav-search-hint").is_visible(), hint_visible)
        button.click()
        expect(page.locator("dialog.wb-dialog[open]")).to_be_visible()
        page.keyboard.press("Escape")
        expect(button).to_be_focused()

    def test_the_magnifier_with_the_hint_on_a_desktop_only(self):
        with self.subTest("desktop"):
            page = self.page
            self.check(page, hint_visible=True)
            expect(page.locator(".wb-nav-search-hint")).to_have_text("Ctrl+K")
        with self.subTest("phone"):
            page = self.login(self.ada, viewport={"width": 360, "height": 740})
            self.check(page, hint_visible=False)

    def test_a_modifier_click_is_the_link_to_the_search_page(self):
        page = self.page
        self.goto(page, self.project)
        self.assertEqual(
            page.locator("[data-palette-open]").get_attribute("href"), "/search/"
        )
        self.assertFalse(
            test_e2e_modals.MoreMenuModalTest.modifier_click_is_prevented(
                self, page, "[data-palette-open]"
            )
        )
        expect(page.locator("dialog.wb-dialog[open]")).to_have_count(0)


class HtmxTest(E2ETestCase):
    def test_a_request_of_any_element_carries_the_csrf_token(self):
        """Not only forms: htmx 4 inherits headers only when told to"""
        page = self.page
        self.goto(page, self.project)
        page.evaluate("""() => {
            document.body.insertAdjacentHTML(
              "beforeend", '<button id="x" hx-post="/nowhere/">x</button>')
            htmx.process(document.getElementById("x"))
        }""")
        with page.expect_request("**/nowhere/") as request:
            page.locator("#x").click()
        self.assertTrue(request.value.headers.get("x-csrftoken"))


class KeyboardTest(E2ETestCase):
    """The command palette and the shortcuts (specs/keyboard.md)"""

    def open_palette(self, page, key="Control+k"):
        page.keyboard.press(key)
        expect(page.locator("#wb-palette")).to_be_visible()
        expect(page.locator("#wb-palette-input")).to_be_focused()

    def options(self, page):
        return page.locator("#wb-palette-list [role=option]")

    def test_ctrl_k_and_slash_open_the_palette(self):
        page = self.page
        self.goto(page, self.project)
        self.open_palette(page)
        # The actions of the page come first, and it has a role for screen
        # readers
        expect(self.options(page).first).to_contain_text("New list")
        self.assertEqual(
            page.locator("#wb-palette-input").get_attribute("role"), "combobox"
        )
        page.keyboard.press("Escape")
        expect(page.locator("#wb-palette")).not_to_be_visible()
        self.open_palette(page, "/")
        # "/" typed into the open palette is just a character
        page.keyboard.type("/")
        self.assertEqual(page.locator("#wb-palette-input").input_value(), "/")
        self.assertEqual(self.errors, [])

    def test_ctrl_enter_submits_the_form_once(self):
        """Every form (decided 2026-11-22): a comment, a modal's form; the
        people picker's Enter still picks"""
        self.make_list(todos=["Plan"])
        todo = Item.objects.get(title="Plan")
        page = self.page
        self.goto(page, todo)
        textarea = page.locator("form:has([name=form][value=comment]) textarea")
        self.set_markdown(textarea, "Looks good")
        # Twice quickly, or held: one comment
        self.editor(textarea).press("ControlOrMeta+Enter")
        self.editor(textarea).press("ControlOrMeta+Enter")
        expect(page.locator(".wb-markdown", has_text="Looks good")).to_have_count(1)
        self.assertEqual(Comment.objects.filter(item=todo).count(), 1)
        # A modal's form, from any field of it
        self.goto(page, self.project)
        page.get_by_role("link", name="New list").click()
        dialog = page.get_by_role("dialog", name="New list")
        dialog.get_by_label("Title").fill("Packing")
        dialog.get_by_label("Title").press("ControlOrMeta+Enter")
        expect(page.locator("main h1")).to_contain_text("Packing")
        self.assertEqual(Item.objects.filter(title="Packing").count(), 1)
        # The picker picks with the list open, then the form submits
        # Bob hears only when tagged: offered in "Also tell…"
        project_ops.add_member(self.project, self.bob, actor=self.ada, notify="tagged")
        page.goto(self.live_server_url + reverse("message_new", args=[self.project.pk]))
        page.get_by_label("Title").fill("Kickoff")
        picker = page.locator(".wb-picker-input")
        picker.press_sequentially("bob")
        expect(page.locator(".wb-picker-list li").first).to_be_visible()
        picker.press("Enter")
        expect(page.locator(".wb-pill")).to_have_count(1)
        picker.press("ControlOrMeta+Enter")
        page.wait_for_url(re.compile(r"/messages/\d+/"))
        self.assertEqual(Item.objects.filter(title="Kickoff").count(), 1)
        self.assertEqual(self.errors, [])

    def test_focus_returns_where_it_was(self):
        page = self.page
        self.goto(page, self.project)
        page.locator("a.navbar-brand").focus()
        self.open_palette(page)
        page.keyboard.press("Escape")
        expect(page.locator("a.navbar-brand")).to_be_focused()

    def test_jumping_by_typing(self):
        self.make_list("Launch plan", todos=["Pack"])
        self.make_list("Secret plan")  # visible to nobody but staff
        page = self.page
        self.goto(page, self.project)
        self.open_palette(page)
        page.keyboard.type("laun")
        option = self.options(page).filter(has_text="Launch plan")
        expect(option).to_be_visible()
        # The search is always the last entry
        expect(self.options(page).last).to_contain_text("Search for “laun”")
        # Arrow keys move, Enter runs
        page.keyboard.press("ArrowDown")
        expect(option).to_have_attribute("aria-selected", "true")
        page.keyboard.press("Enter")
        page.wait_for_url("**/lists/*/")
        expect(page.locator("h1")).to_contain_text("Launch plan")

    def test_every_button_shows_the_keyboards_focus(self):
        """A ring in the accent's color, white on the bar (specs/ui.md)"""
        page = self.page
        todolist = self.make_list(todos=["Pack"])
        self.goto(page, todolist)
        ring = """el => {
          const style = getComputedStyle(el)
          return [el.matches(":focus-visible"), style.outlineStyle,
                  style.outlineWidth, style.outlineColor]
        }"""
        for selector, color in [
            # Quiet buttons on the page and as a menu's summary
            (".wb-page-header a.btn-quiet[title=Edit]", "rgb(103, 65, 196)"),
            (".wb-page-header .wb-menu > summary", "rgb(103, 65, 196)"),
            (".wb-navbar .wb-lantern-button", "rgb(255, 255, 255)"),
        ]:
            with self.subTest(selector):
                button = page.locator(selector).first
                page.keyboard.press("Escape")
                button.focus()
                self.assertEqual(button.evaluate(ring), [True, "solid", "2px", color])
        # The skip link shows when the keyboard reaches it, first
        self.goto(page, todolist)
        page.keyboard.press("Tab")
        skip = page.get_by_role("link", name="Skip to content")
        expect(skip).to_be_focused()
        expect(skip).to_be_in_viewport()
        # Tab goes on in the content, not in the bar
        page.keyboard.press("Enter")
        page.keyboard.press("Tab")
        self.assertTrue(page.evaluate("!!document.activeElement.closest('main')"))

    def test_the_clients_badge_is_the_pages_badge(self):
        """Yellow "Clients" like everywhere on the pages"""
        self.make_list("Launch plan for the hut with a rather long title", visible=True)
        page = self.page
        self.goto(page, self.project)
        self.open_palette(page)
        page.keyboard.type("launch")
        option = self.options(page).filter(has_text="Launch plan")
        badge = option.locator(".badge")
        expect(badge).to_have_text("Clients")
        expect(badge).to_have_class(re.compile(r"\bwb-client-badge\b"))

    def test_search_is_an_entry(self):
        page = self.page
        self.goto(page, self.project)
        self.open_palette(page)
        page.keyboard.type("zebra")
        expect(self.options(page).last).to_contain_text("Search for “zebra”")
        page.keyboard.press("Enter")
        page.wait_for_url("**/search/?q=zebra")

    def test_a_new_to_do_through_the_palette(self):
        todolist = self.make_list()
        page = self.page
        self.goto(page, todolist)
        self.open_palette(page)
        page.keyboard.type("new to-do")
        page.keyboard.press("Enter")
        title = page.locator("[data-add-todo] [name=title]").first
        expect(title).to_be_focused()
        title.fill("From the palette")
        title.press("ControlOrMeta+Enter")
        page.locator("[data-todo]").filter(has_text="From the palette").wait_for()
        self.assertTrue(
            Item.objects.filter(title="From the palette", creator=self.ada).exists()
        )

    def test_completing_a_to_do_through_the_palette(self):
        todo = ops.create_todo(
            todolist=self.make_list(), title="Pack the tent", creator=self.ada
        )
        page = self.page
        self.goto(page, todo)
        self.open_palette(page)
        page.keyboard.type("complete")
        page.keyboard.press("Enter")
        expect(page.locator("main")).to_contain_text("Completed by")
        todo.todo.refresh_from_db()
        self.assertTrue(todo.todo.is_completed)

    def test_rows_with_j_k_o_and_x(self):
        todolist = self.make_list(todos=["One", "Two", "Three"])
        page = self.page
        self.goto(page, todolist)
        current = page.locator(".wb-kb-current")
        page.keyboard.press("j")
        expect(current).to_contain_text("One")
        # Focus follows, to the row's link
        expect(page.locator("[data-todo] a[data-kb-open]").first).to_be_focused()
        page.keyboard.press("j")
        expect(current).to_contain_text("Two")
        page.keyboard.press("j")
        page.keyboard.press("j")  # The last row stays
        expect(current).to_contain_text("Three")
        page.keyboard.press("k")
        expect(current).to_contain_text("Two")
        page.keyboard.press("Escape")
        self.assertEqual(current.count(), 0)
        # Shift+x completes the current row (x selects it, specs/handover.md)
        page.keyboard.press("j")
        page.keyboard.press("j")
        expect(current).to_contain_text("Two")
        # The check fills at once, the page follows the animation
        with page.expect_navigation():
            page.keyboard.press("Shift+x")
        self.assertEqual(Item.objects.get(title="Two").todo.is_completed, True)
        self.assertEqual(Item.objects.get(title="One").todo.is_completed, False)
        # o opens it
        page.keyboard.press("j")
        page.keyboard.press("o")
        page.wait_for_url("**/todos/*/")

    def test_shift_x_on_a_todos_page_does_what_it_says(self):
        self.make_list("Launch", todos=["Plan"])
        item = Item.objects.get(title="Plan")
        page = self.page
        self.goto(page, item)
        # Someone else completes it meanwhile: Shift+x said "Complete", so it
        # stays completed instead of being reopened
        ops.complete(item, actor=self.bob)
        with page.expect_navigation():
            page.keyboard.press("Shift+x")
        item.todo.refresh_from_db()
        self.assertEqual(item.todo.completed_by, self.bob)
        # Now it says "Reopen"
        expect(page.get_by_role("button", name="Reopen")).to_be_visible()
        with page.expect_navigation():
            page.keyboard.press("Shift+x")
        item.todo.refresh_from_db()
        self.assertIsNone(item.todo.completed_at)
        self.assertEqual(self.errors, [])

    def test_rows_of_my_todos_and_the_feed_and_search(self):
        ops.create_todo(todolist=self.make_list(), title="Alpha", creator=self.ada)
        page = self.page
        for url, row in [
            ("/todos/?assignee=anybody", "[data-kb-row]"),
            ("/feed/", "[data-kb-row]"),
            ("/search/?q=alpha", "[data-kb-row]"),
        ]:
            self.goto(page, url)
            page.keyboard.press("j")
            expect(page.locator(".wb-kb-current")).to_have_count(1)
            self.assertTrue(
                page.locator(".wb-kb-current").first.evaluate(
                    "el => el.matches('" + row + "')"
                )
            )

    def test_g_then_t_goes_to_the_todos(self):
        page = self.page
        self.goto(page, self.project)
        page.keyboard.press("g")
        page.keyboard.press("t")
        page.wait_for_url("**/todos/")
        page.keyboard.press("g")
        page.keyboard.press("p")
        page.wait_for_url(f"{self.live_server_url}/projects/")
        page.keyboard.press("g")
        page.keyboard.press("h")
        page.wait_for_url(f"{self.live_server_url}/")

    def test_a_question_mark_lists_the_shortcuts(self):
        page = self.page
        self.goto(page, self.project)
        page.keyboard.press("?")
        dialog = page.locator("#wb-shortcuts")
        expect(dialog).to_be_visible()
        expect(dialog).to_contain_text("command palette")
        page.keyboard.press("Escape")
        expect(dialog).not_to_be_visible()
        # The dialog ends with a link to the help
        page.keyboard.press("?")
        expect(dialog).to_be_visible()
        dialog.get_by_role("link", name="Help").click()
        page.wait_for_url(f"{self.live_server_url}/help/keyboard/")
        expect(page.locator("#shortcuts")).to_contain_text("command palette")
        self.assertEqual(self.errors, [])

    def test_shortcuts_of_an_item_page(self):
        todo = ops.create_todo(
            todolist=self.make_list(), title="Pack", creator=self.ada
        )
        page = self.page
        self.goto(page, todo)
        page.keyboard.press("c")
        expect(self.editor(page.locator("#comments ~ form textarea"))).to_be_focused()
        page.locator("h1").click()
        page.keyboard.press("b")
        page.wait_for_function(
            "() => !!document.querySelector('[title=\"Remove the bookmark\"]')"
        )

    def test_nothing_fires_while_typing(self):
        todolist = self.make_list(todos=["One", "Two"])
        page = self.page
        self.goto(page, todolist)
        add = page.locator("[data-add-todo]").first
        add.locator("summary").click()
        title = add.locator("[name=title]")
        expect(title).to_be_focused()
        page.keyboard.type("jkx?/gt c")
        self.assertEqual(title.input_value(), "jkx?/gt c")
        self.assertEqual(page.locator(".wb-kb-current").count(), 0)
        expect(page.locator("#wb-palette")).not_to_be_visible()
        expect(page.locator("#wb-shortcuts")).not_to_be_visible()
        self.assertEqual(
            page.url, f"{self.live_server_url}{todolist.get_absolute_url()}"
        )
        # Ctrl+K works while typing
        self.open_palette(page)

    def test_with_the_setting_off_only_ctrl_k_works(self):
        self.ada.keyboard_shortcuts = False
        self.ada.save()
        todolist = self.make_list(todos=["One"])
        page = self.page
        self.goto(page, todolist)
        for key in ["j", "/", "?", "x"]:
            page.keyboard.press(key)
        self.assertEqual(page.locator(".wb-kb-current").count(), 0)
        expect(page.locator("#wb-palette")).not_to_be_visible()
        expect(page.locator("#wb-shortcuts")).not_to_be_visible()
        page.keyboard.press("g")
        page.keyboard.press("t")
        self.assertEqual(
            page.url, f"{self.live_server_url}{todolist.get_absolute_url()}"
        )
        self.open_palette(page)
        # The actions still run from the palette
        page.keyboard.type("go to to-dos")
        page.keyboard.press("Enter")
        page.wait_for_url("**/todos/")

    def test_the_theme_action_and_the_stored_theme(self):
        page = self.page
        self.goto(page, self.project)
        self.open_palette(page)
        page.keyboard.type("switch the theme")
        page.keyboard.press("Enter")
        page.wait_for_function(
            "() => document.documentElement.dataset.themeMode === 'light'"
        )
        # Saved for the person, so that it follows them
        page.wait_for_function(
            "() => fetch('/api/v1/me/').then(r => r.json()).then(m => m.theme === 'light')"
        )
        self.ada.refresh_from_db()
        self.assertEqual(self.ada.theme, "light")
        self.assertEqual(self.errors, [])

    def test_the_settings_page_previews_the_appearance(self):
        page = self.page
        root = "document.documentElement.dataset"
        self.goto(page, "/accounts/settings/")
        stored = page.evaluate(f"[{root}.themeMode, {root}.accent]")
        accent = "lake" if stored[1] != "lake" else "berry"
        page.locator(f'input[name="accent"][value="{accent}"]').check()
        page.wait_for_function(f"() => {root}.accent === '{accent}'")
        # The page's background takes a hint of the accent color at once
        background = "getComputedStyle(document.body).backgroundColor"
        tinted = page.evaluate(background)
        page.locator(f'input[name="accent"][value="{stored[1]}"]').check()
        page.wait_for_function(f"() => {root}.accent === '{stored[1]}'")
        self.assertNotEqual(page.evaluate(background), tinted)
        page.locator(f'input[name="accent"][value="{accent}"]').check()
        page.locator('input[name="theme"][value="dark"]').check()
        page.wait_for_function(f"() => {root}.accent === '{accent}'")
        self.assertEqual(page.evaluate(f"{root}.themeMode"), "dark")
        self.assertEqual(
            page.evaluate("document.documentElement.dataset.bsTheme"), "dark"
        )
        self.ada.refresh_from_db()
        self.assertNotEqual(self.ada.accent, accent)
        # Reset goes back to the stored choice
        reset = page.locator("[data-appearance-reset]")
        expect(reset).to_be_visible()
        reset.click()
        self.assertEqual(page.evaluate(f"[{root}.themeMode, {root}.accent]"), stored)
        expect(reset).to_be_hidden()
        # Reloading without saving shows the stored choice
        page.locator(f'input[name="accent"][value="{accent}"]').check()
        page.locator('input[name="theme"][value="dark"]').check()
        page.reload()
        self.assertEqual(page.evaluate(f"[{root}.themeMode, {root}.accent]"), stored)
        # Saving stores it
        page.locator(f'input[name="accent"][value="{accent}"]').check()
        page.locator('input[name="theme"][value="dark"]').check()
        page.locator("[data-appearance-preview] button[type=submit]").click()
        page.wait_for_load_state()
        self.ada.refresh_from_db()
        self.assertEqual((self.ada.theme, self.ada.accent), ("dark", accent))
        self.assertEqual(
            page.evaluate(f"[{root}.themeMode, {root}.accent]"), ["dark", accent]
        )
        self.assertEqual(self.errors, [])


class FiltersTest(E2ETestCase):
    """Filter forms apply themselves and are remembered (specs/ui.md, "Filters and
    view choices")"""

    def setUp(self):
        super().setUp()
        self.make_list("Launch", todos=["Plan"])

    def test_a_select_applies_the_filter_and_keeps_the_focus(self):
        page = self.page
        self.goto(page, "/todos/")
        # Without JavaScript's help the button would be the way; here it's gone
        expect(page.locator("[data-autosubmit-button]")).to_be_hidden()
        page.locator("#id_assignee").select_option("nobody")
        # Without the empty values (the defaults)
        page.wait_for_url("**/todos/?assignee=nobody")
        page.wait_for_function("document.activeElement.name === 'assignee'")
        page.locator("#id_state").select_option("completed")
        page.wait_for_url("**state=completed*")
        page.wait_for_function("document.activeElement.name === 'state'")
        expect(page.locator("#id_assignee")).to_have_value("nobody")
        self.assertEqual(self.errors, [])

    def test_a_form_with_a_field_named_action_applies_itself(self):
        """The activity's filter has a field named "action", which hides the
        form's own action from scripts: the filter still applies"""
        page = self.page
        self.goto(page, "/feed/")
        page.locator("#id_action").select_option(index=1)
        page.wait_for_url("**/feed/?action=*")
        self.assertEqual(self.errors, [])

    def test_a_checkbox_applies_the_lantern_filter(self):
        page = self.page
        self.goto(page, "/lantern/")
        page.locator('input[name="unread"]').check()
        page.wait_for_url("**/lantern/?unread=1")
        expect(page.locator('input[name="unread"]')).to_be_checked()
        page.wait_for_function("document.activeElement.name === 'unread'")

    def test_search_keeps_its_button_and_waits_for_enter(self):
        page = self.page
        self.goto(page, "/search/")
        expect(
            page.locator("form[data-autosubmit] button[type=submit]")
        ).to_be_visible()
        page.locator('input[name="q"]').fill("Plan")
        page.wait_for_timeout(700)
        self.assertNotIn("q=", page.url)
        page.locator('input[name="q"]').press("Enter")
        page.wait_for_url("**q=Plan*")

    def test_filters_are_restored_through_the_navigation_and_reset(self):
        page = self.page
        self.goto(page, "/todos/?assignee=nobody&state=completed")
        # The link of the top bar goes to the stored filters
        self.goto(page, "/")
        link = page.locator(".wb-nav-links a", has_text="To-dos")
        expect(link).to_have_attribute(
            "href", "/todos/?assignee=nobody&state=completed"
        )
        link.click()
        page.wait_for_url("**/todos/?assignee=nobody&state=completed")
        expect(page.locator("#id_state")).to_have_value("completed")
        # Opening the page by another link uses its own query
        self.goto(page, "/todos/?assignee=anybody")
        expect(page.locator("#id_assignee")).to_have_value("anybody")
        # Reset clears what is stored
        page.get_by_role("link", name="Reset filters").click()
        page.wait_for_url("**/todos/")
        self.goto(page, "/")
        expect(page.locator(".wb-nav-links a", has_text="To-dos")).to_have_attribute(
            "href", "/todos/"
        )
        # The palette's link too
        self.goto(page, "/todos/?assignee=nobody")
        self.goto(page, "/")
        page.keyboard.press("ControlOrMeta+k")
        page.locator("#wb-palette-input").fill("go to to-dos")
        page.keyboard.press("Enter")
        page.wait_for_url("**/todos/?assignee=nobody")
        self.assertEqual(self.errors, [])

    def test_the_grouping_is_restored_through_the_navigation(self):
        page = self.page
        self.goto(page, "/todos/?assignee=me")
        page.locator("#id_grouping").select_option("due")
        page.wait_for_url("**grouping=due*")
        self.goto(page, "/")
        link = page.locator(".wb-nav-links a", has_text="To-dos")
        expect(link).to_have_attribute("href", re.compile(r"grouping=due"))
        link.click()
        page.wait_for_url("**grouping=due*")
        expect(page.locator("#id_grouping")).to_have_value("due")
        self.assertEqual(self.errors, [])

    def test_going_back_to_the_defaults_is_remembered(self):
        page = self.page
        link = page.locator(".wb-nav-links a", has_text="To-dos")
        # Back to "Me", the empty choice
        self.goto(page, "/todos/?assignee=anybody")
        page.locator("#id_assignee").select_option("")
        page.wait_for_url("**/todos/")
        self.goto(page, "/")
        expect(link).to_have_attribute("href", "/todos/")
        # Back to grouping by project, which shows no "Reset filters"
        self.goto(page, "/todos/?grouping=due")
        expect(page.get_by_role("link", name="Reset filters")).to_have_count(0)
        page.locator("#id_grouping").select_option("")
        page.wait_for_url("**/todos/")
        self.goto(page, "/")
        expect(link).to_have_attribute("href", "/todos/")
        # The lantern's and the feed's too
        for path, query in [("/lantern/", "unread=1"), ("/feed/", "kind=todo")]:
            self.goto(page, f"{path}?{query}")
            self.assertEqual(
                page.evaluate(f"localStorage.getItem('filters:{path}')"), query
            )
            self.goto(page, path)
            self.assertIsNone(page.evaluate(f"localStorage.getItem('filters:{path}')"))
        self.assertEqual(self.errors, [])

    def test_the_projects_all_todos_button_restores_the_filters(self):
        page = self.page
        todos = f"/projects/{self.project.pk}/todos/"
        # The page's own links keep their query, and the page remembers it
        self.goto(page, self.project)
        page.get_by_role("link", name="by due date").click()
        page.wait_for_url("**/todos/?grouping=due")
        # The header's button restores what the page remembered
        self.goto(page, self.project)
        button = page.locator(".wb-page-actions a.btn", has_text="All to-dos")
        expect(button).to_have_attribute("href", todos + "?grouping=due")
        button.click()
        page.wait_for_url("**grouping=due*")
        expect(page.locator("#id_grouping")).to_have_value("due")
        # Not by the link next to the heading
        self.goto(page, self.project)
        expect(page.get_by_role("link", name="by list")).to_have_attribute(
            "href", todos
        )
        self.assertEqual(self.errors, [])

    def test_assigned_by_is_remembered_and_the_palette_opens_it_exactly(self):
        page = self.page
        self.goto(page, "/todos/")
        page.locator("#id_assigned_by").select_option("me")
        page.wait_for_url("**assigned_by=me*")
        page.wait_for_function("document.activeElement.name === 'assigned_by'")
        # The top bar's link restores it
        self.goto(page, "/")
        link = page.locator(".wb-nav-links a", has_text="To-dos")
        expect(link).to_have_attribute("href", re.compile(r"assigned_by=me"))
        link.click()
        page.wait_for_url("**assigned_by=me*")
        expect(page.locator("#id_assigned_by")).to_have_value("me")
        # The palette's "To-dos I assigned" goes to its own query, whatever
        # is remembered for the page
        self.goto(page, "/todos/?assignee=nobody")
        self.goto(page, "/")
        page.keyboard.press("ControlOrMeta+k")
        page.locator("#wb-palette-input").fill("to-dos i assigned")
        page.keyboard.press("Enter")
        page.wait_for_url("**/todos/?assigned_by=me")
        expect(page.locator("#id_assigned_by")).to_have_value("me")
        # Assigned to anybody (else), the empty choice then
        expect(page.locator("#id_assignee")).to_have_value("")
        expect(page.locator("#id_assignee option:checked")).to_have_text("Anybody")
        self.assertEqual(self.errors, [])

    def test_search_is_not_remembered(self):
        page = self.page
        self.goto(page, "/search/?q=Plan")
        self.assertIsNone(page.evaluate("localStorage.getItem('filters:/search/')"))
        self.assertEqual(self.errors, [])


class HomeTest(E2ETestCase):
    """Completing a to-do on Home (specs/dashboard.md): the page stays Home,
    and the row is gone"""

    def test_completing_a_to_do_stays_on_home(self):
        page = self.page
        todolist = self.make_list("Launch", todos=["Plan", "Pack"])
        for todo in Item.objects.filter(parent=todolist):
            ops.update_todo(todo, actor=self.ada, due_on=schedules.today())
            ops.assign(todo, [self.ada], actor=self.ada)
        self.goto(page, "/")
        row = page.locator(".wb-todo", has_text="Plan")
        expect(row).to_be_visible()
        row.get_by_role("button", name="Complete").click()
        expect(row).to_have_count(0)
        self.assertEqual(page.url, f"{self.live_server_url}/")
        expect(page.locator("[data-home=due]")).to_contain_text("Pack")
        self.assertEqual(Item.objects.get(title="Plan").todo.is_completed, True)
        self.assertEqual(self.errors, [])

    def test_the_shortcuts_link_opens_the_help(self):
        page = self.page
        self.goto(page, "/")
        link = page.get_by_role("link", name="Keyboard shortcuts")
        expect(link).to_be_visible()
        expect(page.locator("[data-shortcuts-hint]")).to_be_hidden()
        link.click()
        expect(page.locator("#wb-shortcuts")).to_be_visible()
        page.keyboard.press("Escape")
        expect(page.locator("#wb-shortcuts")).not_to_be_visible()
        self.assertEqual(page.url, f"{self.live_server_url}/")
        self.assertEqual(self.errors, [])
