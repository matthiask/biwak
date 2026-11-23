"""The settings page saving itself (frontend/save-on-change.js, specs/ui.md
"Saving on change"): choices when they change, text fields when they're
left, without Save buttons; "Saved" at the field, errors below it"""

import datetime as dt

from biwak.test_e2e import E2ETestCase, expect


def answered(path):
    """The form's POST to ``path`` answered"""
    return lambda response: (
        response.request.method == "POST" and response.url.endswith(path)
    )


class SettingsSaveTest(E2ETestCase):
    def setUp(self):
        super().setUp()
        self.goto(self.page, "/accounts/settings/")
        # Set before anything is saved: still there, so nothing reloaded
        self.page.evaluate("window.marker = 1")

    def assertNotReloaded(self):
        self.assertEqual(self.page.evaluate("window.marker"), 1)

    def test_a_choice_saves_when_it_changes(self):
        page = self.page
        # Save is for people without JavaScript
        for form in ("name", "appearance", "notifications", "away"):
            expect(
                page.locator(
                    f'form[action="/accounts/settings/{form}/"] [data-save-button]'
                )
            ).to_be_hidden()
        digest = page.locator('input[name="mail_delivery"][value="digest"]')
        with page.expect_response(answered("/accounts/settings/notifications/")):
            digest.check()
        self.ada.refresh_from_db()
        self.assertEqual(self.ada.mail_delivery, "digest")
        # "Saved" in the group's corner, for screen readers in the live region
        group = page.locator("fieldset", has=digest)
        expect(group.locator(".wb-saved.is-shown")).to_be_visible()
        expect(page.locator("[data-save-status]")).to_have_text("Saved")
        # And gone again
        expect(group.locator(".wb-saved.is-shown")).to_have_count(0, timeout=5000)
        self.assertNotReloaded()
        # A checkbox the same way
        with page.expect_response(answered("/accounts/settings/notifications/")):
            page.get_by_label(
                "A dot on the tab's icon while there are unread notifications"
            ).uncheck()
        self.ada.refresh_from_db()
        self.assertFalse(self.ada.lantern_in_favicon)
        self.assertEqual(self.errors, [])

    def test_a_text_saves_when_it_is_left(self):
        page = self.page
        name = page.get_by_label("Full name")
        name.fill("Ada Lovelace")
        # Typing alone saves nothing
        self.ada.refresh_from_db()
        self.assertNotEqual(self.ada.full_name, "Ada Lovelace")
        with page.expect_response(answered("/accounts/settings/name/")):
            name.blur()
        self.ada.refresh_from_db()
        self.assertEqual(self.ada.full_name, "Ada Lovelace")
        # Leaving it unchanged sends nothing
        posts = []
        page.on(
            "request", lambda r: posts.append(r.url) if r.method == "POST" else None
        )
        name.focus()
        name.blur()
        page.get_by_label("Short name").focus()
        page.get_by_label("Short name").blur()
        page.wait_for_timeout(300)
        self.assertEqual(posts, [])
        # Enter saves too, without leaving the page
        short = page.get_by_label("Short name")
        short.fill("Countess")
        with page.expect_response(answered("/accounts/settings/name/")):
            short.press("Enter")
        self.ada.refresh_from_db()
        self.assertEqual(self.ada.short_name, "Countess")
        self.assertNotReloaded()
        self.assertEqual(self.errors, [])

    def test_an_error_is_shown_at_the_field_until_fixed(self):
        page = self.page
        name = page.get_by_label("Full name")
        name.fill("")
        with page.expect_response(answered("/accounts/settings/name/")):
            name.blur()
        error = page.locator("[data-save-error]")
        expect(error).to_have_text("This field is required.")
        expect(name).to_have_attribute("aria-invalid", "true")
        self.ada.refresh_from_db()
        self.assertNotEqual(self.ada.full_name, "")
        # What was typed stays; fixed, the error goes
        name.fill("Ada Example")
        with page.expect_response(answered("/accounts/settings/name/")):
            name.blur()
        expect(error).to_have_count(0)
        expect(name).not_to_have_attribute("aria-invalid", "true")
        # The browser logs the 400
        self.errors.clear()

    def test_a_required_field_still_empty_waits(self):
        page = self.page
        posts = []
        page.on(
            "request", lambda r: posts.append(r.url) if r.method == "POST" else None
        )
        note = page.get_by_label("Note")
        note.fill("Hiking")
        note.blur()
        page.wait_for_timeout(300)
        self.assertEqual(posts, [])
        # With the day, both are saved
        tomorrow = dt.date.today() + dt.timedelta(days=1)
        until = page.get_by_label("Away until")
        until.fill(tomorrow.isoformat())
        with page.expect_response(answered("/accounts/settings/away/")):
            until.blur()
        self.ada.refresh_from_db()
        self.assertEqual(
            (self.ada.away_until, self.ada.away_note), (tomorrow, "Hiking")
        )
        self.assertEqual(self.errors, [])

    def test_a_failed_save_shakes_and_a_choice_goes_back(self):
        page = self.page
        self.watch_classes(page)
        self.goto(page, "/accounts/settings/")
        page.route("**/accounts/settings/notifications/", lambda route: route.abort())
        digest = page.locator('input[name="mail_delivery"][value="digest"]')
        stored = page.locator('input[name="mail_delivery"]:checked').get_attribute(
            "value"
        )
        digest.click()
        self.seen_class(page, "wb-shake")
        expect(page.locator('input[name="mail_delivery"]:checked')).to_have_attribute(
            "value", stored
        )
        # A text keeps what was typed and is saved when it's left again
        page.route("**/accounts/settings/name/", lambda route: route.abort())
        name = page.get_by_label("Full name")
        name.fill("Ada Lovelace")
        name.blur()
        page.wait_for_timeout(300)
        expect(name).to_have_value("Ada Lovelace")
        page.unroute("**/accounts/settings/name/")
        name.focus()
        with page.expect_response(answered("/accounts/settings/name/")):
            name.blur()
        self.ada.refresh_from_db()
        self.assertEqual(self.ada.full_name, "Ada Lovelace")
        # The browser logs the failed requests
        self.errors.clear()

    def test_the_appearance_applies_and_saves_at_once(self):
        page = self.page
        root = "document.documentElement.dataset"
        accent = "lake" if self.ada.accent != "lake" else "berry"
        with page.expect_response(answered("/accounts/settings/appearance/")):
            page.locator(f'input[name="accent"][value="{accent}"]').check()
        self.assertEqual(page.evaluate(f"{root}.accent"), accent)
        with page.expect_response(answered("/accounts/settings/appearance/")):
            page.locator('input[name="theme"][value="dark"]').check()
        self.assertEqual(page.evaluate(f"{root}.themeMode"), "dark")
        self.ada.refresh_from_db()
        self.assertEqual((self.ada.theme, self.ada.accent), ("dark", accent))
        # Failing, the stored choice comes back and is shown again
        page.route("**/accounts/settings/appearance/", lambda route: route.abort())
        # A click: check() complains when the choice goes back
        page.locator('input[name="theme"][value="light"]').click()
        page.wait_for_function(f"() => {root}.themeMode === 'dark'")
        expect(page.locator('input[name="theme"][value="dark"]')).to_be_checked()
        self.errors.clear()

    def test_the_language_reloads_the_page_in_it(self):
        page = self.page
        with page.expect_navigation():
            page.locator('input[name="language"][value="de"]').click()
        expect(page.locator("h1")).to_have_text("Einstellungen")
        self.ada.refresh_from_db()
        self.assertEqual(self.ada.language, "de")
        self.assertEqual(self.errors, [])
