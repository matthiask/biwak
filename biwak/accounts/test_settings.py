"""The settings page's keyboard, appearance and sign-in sections and the
API's ``me/`` preferences (specs/keyboard.md)"""

from django.test import TestCase

from biwak.accounts.models import PALETTE, Accent, APIToken, Theme
from biwak.test_utils import person


class PreferencesTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.cleo = person("Cleo", client=True)

    def test_defaults(self):
        self.assertTrue(self.ada.keyboard_shortcuts)
        self.assertEqual(self.ada.theme, Theme.AUTO)
        self.assertEqual(self.ada.accent, Accent.HEATHER)

    def test_the_accent_colors_are_in_the_palette_without_amber(self):
        self.assertTrue(set(Accent.values) <= set(PALETTE))
        self.assertNotIn("amber", PALETTE)
        self.assertEqual(len(PALETTE), 10)

    def test_login_required(self):
        for action in ["keyboard", "appearance", "notifications"]:
            response = self.client.post(f"/accounts/settings/{action}/")
            self.assertEqual(response.status_code, 302)

    def test_settings_page_sections(self):
        for user in [self.ada, self.cleo]:
            with self.subTest(user=user):
                self.client.force_login(user)
                response = self.client.get("/accounts/settings/")
                for text in [
                    "Notifications",
                    "Keyboard",
                    "Appearance",
                    "Heather",
                    "Alpenglow",
                    "/accounts/2fa/",
                    "/accounts/sessions/",
                    "/accounts/api-tokens/",
                ]:
                    self.assertContains(response, text)
                self.assertNotContains(response, "Amber")

    def test_keyboard_section(self):
        self.client.force_login(self.ada)
        response = self.client.post("/accounts/settings/keyboard/", {})
        self.assertRedirects(response, "/accounts/settings/")
        self.ada.refresh_from_db()
        self.assertFalse(self.ada.keyboard_shortcuts)
        self.client.post("/accounts/settings/keyboard/", {"keyboard_shortcuts": "on"})
        self.ada.refresh_from_db()
        self.assertTrue(self.ada.keyboard_shortcuts)

    def test_appearance_section(self):
        self.client.force_login(self.cleo)
        response = self.client.post(
            "/accounts/settings/appearance/", {"theme": "dark", "accent": "lake"}
        )
        self.assertRedirects(response, "/accounts/settings/")
        self.cleo.refresh_from_db()
        self.assertEqual((self.cleo.theme, self.cleo.accent), ("dark", "lake"))
        # The toggle posts the theme alone and changes nothing else
        response = self.client.post(
            "/accounts/settings/appearance/",
            {"theme": "light"},
            headers={"x-biwak-fragment": "1"},
        )
        self.assertEqual(response.status_code, 204)
        self.cleo.refresh_from_db()
        self.assertEqual((self.cleo.theme, self.cleo.accent), ("light", "lake"))

    def test_appearance_refuses_other_values(self):
        self.client.force_login(self.ada)
        for data in [{"accent": "amber"}, {"accent": "moss"}, {"theme": "sepia"}]:
            with self.subTest(data=data):
                response = self.client.post("/accounts/settings/appearance/", data)
                self.assertEqual(response.status_code, 400)
        self.ada.refresh_from_db()
        self.assertEqual(self.ada.accent, Accent.HEATHER)

    def test_the_page_uses_the_stored_theme_and_accent(self):
        self.ada.theme = "dark"
        self.ada.accent = "ember"
        self.ada.save()
        self.client.force_login(self.ada)
        response = self.client.get("/accounts/settings/")
        self.assertContains(response, 'data-theme-mode="dark"')
        self.assertContains(response, 'data-accent="ember"')


class MeAPITest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        _token, secret = APIToken.create_for(user=self.ada, title="T", access="write")
        self.headers = {"authorization": f"Bearer {secret}"}
        _token, secret = APIToken.create_for(user=self.ada, title="R", access="read")
        self.read_only = {"authorization": f"Bearer {secret}"}

    def put(self, data, headers=None):
        return self.client.put(
            "/api/v1/me/",
            data,
            content_type="application/json",
            headers=headers or self.headers,
        )

    def test_read_and_change(self):
        me = self.client.get("/api/v1/me/", headers=self.headers).json()
        self.assertEqual(
            (me["keyboard_shortcuts"], me["theme"], me["accent"]),
            (True, "auto", "heather"),
        )
        response = self.put({"theme": "dark", "accent": "forest"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["accent"], "forest")
        self.assertTrue(response.json()["keyboard_shortcuts"])
        self.put({"keyboard_shortcuts": False})
        self.ada.refresh_from_db()
        self.assertEqual(
            (self.ada.keyboard_shortcuts, self.ada.theme, self.ada.accent),
            (False, "dark", "forest"),
        )

    def test_invalid_values_and_read_only_tokens(self):
        self.assertEqual(self.put({"accent": "amber"}).status_code, 422)
        self.assertEqual(self.put({"theme": "sepia"}).status_code, 422)
        self.assertEqual(self.put({"theme": "dark"}, self.read_only).status_code, 403)
        self.assertEqual(
            self.client.put(
                "/api/v1/me/", {"theme": "dark"}, content_type="application/json"
            ).status_code,
            401,
        )
