"""Choosing a language (specs/languages.md, "Choosing"): the settings, the
browser's before choosing, the API, and the language of mails"""

from unittest.mock import patch

from django.core import mail
from django.test import TestCase
from django.utils import translation

from biwak.accounts.languages import language_for
from biwak.accounts.models import APIToken
from biwak.organizations import activation
from biwak.projects import operations as project_ops
from biwak.test_utils import person, project, tags


class ChoosingTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.cleo = person("Cleo", client=True)

    def test_the_settings_offer_each_language_in_itself(self):
        for user in [self.ada, self.cleo]:
            with self.subTest(user=user):
                self.client.force_login(user)
                response = self.client.get("/accounts/settings/")
                html = response.content.decode()
                self.assertContains(response, 'action="/accounts/settings/language/"')
                [auto] = tags(html, cls="form-check-input", id="language-auto")
                self.assertIn("checked", auto)
                self.assertRegex(html, r'for="language-de"\s+lang="de"\s*>Deutsch<')
                self.assertContains(response, ">English</label>")
                self.assertContains(response, "Automatic (the browser&#x27;s language)")

    def test_choosing_and_back_to_automatic(self):
        self.client.force_login(self.cleo)
        response = self.client.post("/accounts/settings/language/", {"language": "de"})
        self.assertRedirects(
            response, "/accounts/settings/", fetch_redirect_response=False
        )
        self.cleo.refresh_from_db()
        self.assertEqual(self.cleo.language, "de")
        response = self.client.get("/accounts/settings/")
        self.assertEqual(response["Content-Language"], "de")
        self.assertEqual(response.context["LANGUAGE_CODE"], "de")
        self.client.post("/accounts/settings/language/", {"language": ""})
        self.cleo.refresh_from_db()
        self.assertEqual(self.cleo.language, "")
        self.assertEqual(
            self.client.get("/accounts/settings/")["Content-Language"], "en"
        )

    def test_an_unknown_language_is_refused(self):
        self.client.force_login(self.ada)
        response = self.client.post("/accounts/settings/language/", {"language": "fr"})
        self.assertEqual(response.status_code, 400)
        self.ada.refresh_from_db()
        self.assertEqual(self.ada.language, "")

    def test_the_browser_before_choosing_then_the_choice(self):
        german = {"Accept-Language": "de-CH,de;q=0.9,en;q=0.5"}
        # Signed out: the sign-in page follows the browser, else English
        response = self.client.get("/accounts/login/", headers=german)
        self.assertEqual(response["Content-Language"], "de")
        response = self.client.get("/accounts/login/")
        self.assertEqual(response["Content-Language"], "en")
        # Signed in without a choice: the browser
        self.client.force_login(self.ada)
        self.assertEqual(self.client.get("/", headers=german)["Content-Language"], "de")
        # The choice wins
        self.ada.language = "en"
        self.ada.save()
        self.assertEqual(self.client.get("/", headers=german)["Content-Language"], "en")


class APITest(TestCase):
    def setUp(self):
        self.cleo = person("Cleo", client=True)
        _token, secret = APIToken.create_for(user=self.cleo, title="T", access="write")
        self.headers = {"Authorization": f"Bearer {secret}"}

    def test_me_reads_and_changes_the_language(self):
        response = self.client.get("/api/v1/me/", headers=self.headers)
        self.assertEqual(response.json()["language"], "")
        for language in ["de", "en", ""]:
            with self.subTest(language=language):
                response = self.client.put(
                    "/api/v1/me/",
                    {"language": language},
                    content_type="application/json",
                    headers=self.headers,
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["language"], language)
                self.cleo.refresh_from_db()
                self.assertEqual(self.cleo.language, language)

    def test_unknown_languages_and_other_preferences_leave_it(self):
        self.cleo.language = "de"
        self.cleo.save()
        response = self.client.put(
            "/api/v1/me/",
            {"language": "fr"},
            content_type="application/json",
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 422)
        self.client.put(
            "/api/v1/me/",
            {"theme": "dark"},
            content_type="application/json",
            headers=self.headers,
        )
        self.cleo.refresh_from_db()
        self.assertEqual(self.cleo.language, "de")


class MailLanguageTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.website = project("Website", members=[self.ada])

    def test_language_for(self):
        dora = person("Dora", client=True)
        self.assertEqual(language_for(dora), "en")
        dora.invitation_language = "de"
        self.assertEqual(language_for(dora), "de")
        dora.language = "en"
        self.assertEqual(language_for(dora), "en")

    def invite(self, email, *, language):
        with (
            translation.override(language),
            self.captureOnCommitCallbacks(execute=True),
        ):
            [invited] = project_ops.invite_people(
                [self.website], [{"email": email}], actor=self.ada
            )
        return invited.user

    def test_an_invitation_remembers_the_inviters_language(self):
        dora = self.invite("dora@example.net", language="de")
        dora.refresh_from_db()
        self.assertEqual(dora.invitation_language, "de")
        self.assertEqual(language_for(dora), "de")
        # Resending: the language of the last invitation mail
        with (
            translation.override("en"),
            self.captureOnCommitCallbacks(execute=True),
        ):
            project_ops.resend_invitation(dora, actor=self.ada)
        dora.refresh_from_db()
        self.assertEqual(dora.invitation_language, "en")
        self.assertEqual(len(mail.outbox), 2)

    def test_a_chosen_language_stays_and_nothing_is_remembered(self):
        dora = person("Dora", client=True, language="en", is_active=False)
        self.website.memberships.create(user=dora)
        with (
            translation.override("de"),
            self.captureOnCommitCallbacks(execute=True),
        ):
            activation.activate([dora], actor=self.ada, mail=True)
        dora.refresh_from_db()
        self.assertEqual(dora.invitation_language, "")
        self.assertEqual(language_for(dora), "en")
        self.assertEqual(len(mail.outbox), 1)


class CalendarLanguageTest(TestCase):
    def test_the_feed_is_in_its_owners_language(self):
        from biwak.accounts.models import CalendarToken
        from biwak.items import by_due

        ada = person("Ada", language="de")
        link = CalendarToken.renew(ada)
        seen = []
        original = by_due.calendar_for

        def calendar_for(user):
            seen.append(translation.get_language())
            return original(user)

        with patch.object(by_due, "calendar_for", calendar_for):
            response = self.client.get(
                f"/calendar/{link.token}.ics", headers={"Accept-Language": "en"}
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(seen, ["de"])


class HelpTest(TestCase):
    def test_german_readers_are_told_the_help_is_english(self):
        self.client.force_login(person("Ada", language="de"))
        response = self.client.get("/help/orientation/")
        self.assertContains(response, "Die Hilfe gibt es vorerst nur auf Englisch.")
        self.assertContains(response, '<div lang="en">')
        # How to choose, in English
        self.assertContains(response, "Settings, &quot;Language&quot;")
        self.client.force_login(person("Bea", language="en"))
        response = self.client.get("/help/orientation/")
        self.assertNotContains(response, 'id="help-in-english"')
