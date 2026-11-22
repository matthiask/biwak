"""The settings page's keyboard, appearance and sign-in sections and the
API's ``me/`` preferences (specs/keyboard.md)"""

from unittest.mock import patch

from allauth.mfa.models import Authenticator
from allauth.usersessions.models import UserSession
from django.contrib.sessions.backends.db import SessionStore
from django.test import Client, TestCase, override_settings

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
                    "Add a passkey",
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


RECENT = "allauth.account.internal.flows.reauthentication.did_recently_reauthenticate"
FIREFOX = "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0"
SAFARI = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


# The test client's force_login skips allauth's login flow, which records
# the session; activity tracking records it on the next request instead
@override_settings(USERSESSIONS_TRACK_ACTIVITY=True)
class SignInSectionTest(TestCase):
    """Passkeys and sessions inline on the settings page
    (specs/access.md, "Sign-in"); allauth adds, removes and ends"""

    def setUp(self):
        self.ada = person("Ada")
        self.client.defaults["HTTP_USER_AGENT"] = FIREFOX
        self.client.force_login(self.ada)
        self.client.get("/accounts/settings/")

    def other_session(self, user, user_agent=SAFARI):
        client = Client()
        client.force_login(user)
        key = client.cookies["sessionid"].value
        return UserSession.objects.create(
            user=user, session_key=key, ip="10.0.0.2", user_agent=user_agent
        )

    def passkey(self, name, user=None):
        return Authenticator.objects.create(
            user=user or self.ada,
            type=Authenticator.Type.WEBAUTHN,
            data={"name": name},
        )

    def test_passkeys_are_listed_and_removed(self):
        laptop = self.passkey("Laptop")
        self.passkey("Phone")
        response = self.client.get("/accounts/settings/")
        self.assertContains(response, "Laptop")
        self.assertContains(response, "Phone")
        self.assertContains(response, "Never")
        self.assertContains(response, "Add a passkey")
        self.assertContains(
            response, f"/accounts/2fa/webauthn/keys/{laptop.pk}/remove/"
        )
        url = f"/accounts/2fa/webauthn/keys/{laptop.pk}/remove/"
        # allauth wants a recent confirmation first (and replays the request)
        response = self.client.post(url)
        self.assertIn("/accounts/reauthenticate/", response["Location"])
        self.assertEqual(Authenticator.objects.count(), 2)
        with patch(RECENT, return_value=True):
            response = self.client.post(url)
        self.assertRedirects(
            response, "/accounts/2fa/webauthn/", fetch_redirect_response=False
        )
        self.assertEqual(
            list(Authenticator.objects.values_list("data__name", flat=True)), ["Phone"]
        )

    def test_without_passkeys(self):
        self.assertContains(self.client.get("/accounts/settings/"), "No passkeys yet.")

    def test_only_my_passkeys(self):
        bob = person("Bob")
        key = self.passkey("Bobs key", user=bob)
        self.assertNotContains(self.client.get("/accounts/settings/"), "Bobs key")
        with patch(RECENT, return_value=True):
            response = self.client.post(f"/accounts/2fa/webauthn/keys/{key.pk}/remove/")
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Authenticator.objects.filter(pk=key.pk).exists())

    def test_allauths_lists_lead_to_the_settings_page(self):
        for url in ["/accounts/2fa/", "/accounts/2fa/webauthn/", "/accounts/sessions/"]:
            self.assertRedirects(
                self.client.get(url),
                "/accounts/settings/#sign-in",
                fetch_redirect_response=False,
            )

    def test_sessions_with_this_one_first(self):
        self.other_session(self.ada)
        response = self.client.get("/accounts/settings/")
        self.assertContains(response, "Firefox on Linux")
        self.assertContains(response, "Safari on iPhone")
        self.assertContains(response, "This one", count=1)
        self.assertContains(response, "Sign out everywhere else")
        self.assertContains(response, "10.0.0.2")
        # Relative times with the ago filter (specs/ui.md)
        self.assertContains(response, "just now")
        self.assertEqual(
            [s.browser for s in response.context["sessions"]],
            ["Firefox on Linux", "Safari on iPhone"],
        )
        # Every column has a header, also the actions'
        self.assertContains(response, "<th>", count=4)

    def test_one_session_has_nothing_to_sign_out(self):
        response = self.client.get("/accounts/settings/")
        self.assertNotContains(response, "Sign out everywhere else")
        self.assertNotContains(response, "/end/")

    def test_signing_out_one_session(self):
        phone = self.other_session(self.ada)
        tablet = self.other_session(self.ada)
        response = self.client.post(f"/accounts/sessions/{phone.pk}/end/")
        self.assertRedirects(
            response, "/accounts/settings/#sign-in", fetch_redirect_response=False
        )
        self.assertFalse(UserSession.objects.filter(pk=phone.pk).exists())
        self.assertFalse(SessionStore(phone.session_key).exists(phone.session_key))
        self.assertTrue(UserSession.objects.filter(pk=tablet.pk).exists())
        # This browser is still signed in
        self.assertEqual(self.client.get("/accounts/settings/").status_code, 200)

    def test_not_other_peoples_sessions_nor_this_one_nor_by_get(self):
        bob = person("Bob")
        theirs = self.other_session(bob)
        mine = UserSession.objects.get(user=self.ada)
        self.assertEqual(
            self.client.post(f"/accounts/sessions/{theirs.pk}/end/").status_code, 404
        )
        self.assertEqual(
            self.client.post(f"/accounts/sessions/{mine.pk}/end/").status_code, 404
        )
        self.assertEqual(
            self.client.get(f"/accounts/sessions/{theirs.pk}/end/").status_code, 405
        )
        self.assertEqual(UserSession.objects.count(), 2)

    def test_signing_out_everywhere_else(self):
        self.other_session(self.ada)
        self.other_session(self.ada)
        bobs = self.other_session(person("Bob"))
        response = self.client.post("/accounts/sessions/")
        self.assertRedirects(
            response, "/accounts/sessions/", fetch_redirect_response=False
        )
        self.assertEqual(
            list(
                UserSession.objects.filter(user=self.ada).values_list(
                    "user_agent", flat=True
                )
            ),
            [FIREFOX],
        )
        self.assertTrue(UserSession.objects.filter(pk=bobs.pk).exists())
        self.assertEqual(self.client.get("/accounts/settings/").status_code, 200)

    def test_the_menu_says_sign_out_and_the_card_signs_out_here(self):
        response = self.client.get("/accounts/settings/")
        self.assertNotContains(response, "Sign out of this browser")
        self.assertContains(response, 'class="dropdown-item">Sign out</button>')
        self.assertContains(response, "Sign out here", count=1)
        self.assertNotContains(response, "is signed out with")
        # The button does what the menu's does
        self.client.post("/accounts/logout/")
        self.assertEqual(self.client.get("/accounts/settings/").status_code, 302)


class NameTest(TestCase):
    """One's own name in the settings"""

    def test_changing_ones_name(self):
        ada = person("Ada")
        self.client.force_login(ada)
        self.assertContains(self.client.get("/accounts/settings/"), 'name="full_name"')
        response = self.client.post(
            "/accounts/settings/name/",
            {"full_name": " Ada Lovelace ", "short_name": ""},
        )
        self.assertRedirects(response, "/accounts/settings/")
        ada.refresh_from_db()
        self.assertEqual((ada.full_name, ada.short_name), ("Ada Lovelace", ""))
        self.assertEqual(ada.get_short_name(), "Ada")
        self.client.post(
            "/accounts/settings/name/",
            {"full_name": "Ada Lovelace", "short_name": "Countess"},
        )
        ada.refresh_from_db()
        self.assertEqual(ada.get_short_name(), "Countess")

    def test_the_full_name_is_required(self):
        ada = person("Ada")
        self.client.force_login(ada)
        response = self.client.post(
            "/accounts/settings/name/", {"full_name": "", "short_name": ""}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This field is required")
        ada.refresh_from_db()
        self.assertNotEqual(ada.full_name, "")
