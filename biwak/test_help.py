# Copyright (c) 2026, Feinheit AG and individual contributors (Governance's
# governance/test_help.py, see NOTICE)
"""The help pages from docs/ (specs/help.md)"""

import re
from unittest.mock import patch

from django.test import TestCase

from biwak.help import PAGES
from biwak.items import operations as ops
from biwak.test_utils import person, project


def hrefs(response):
    return re.findall(r'href="([^"]*)"', response.content.decode())


def article(response):
    """What the page's own text links to, without the bar around it"""
    content = response.content.decode()
    return content.split('<article class="card">', 1)[1].split("</article>", 1)[0]


def url(page):
    return f"/help/{page}/" if page else "/help/"


class HelpTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.cleo = person("Cleo", client=True)

    def test_every_chapter_for_staff_and_for_clients(self):
        """Everybody sees every chapter (decided 2026-11-21)"""
        for user in [self.ada, self.cleo]:
            self.client.force_login(user)
            for page in PAGES["en"]:
                with self.subTest(user=user, page=page):
                    response = self.client.get(url(page))
                    self.assertEqual(response.status_code, 200)
                    # One title, the page's own
                    self.assertEqual(response.content.decode().count("<h1"), 1)
                    # The docs link each other, every link leads to a help page
                    self.assertEqual(
                        re.findall(r'href="[^"]*\.md', response.content.decode()), []
                    )

    def test_the_start_page(self):
        self.client.force_login(self.ada)
        response = self.client.get("/help/")
        self.assertContains(response, '<h1 class="wb-title">Help</h1>', html=True)
        self.assertContains(response, "What Biwak doesn")
        self.assertContains(response, "<title>Help – Biwak</title>", html=True)

    def test_relative_links_lead_to_the_help_pages(self):
        self.client.force_login(self.ada)
        text = article(self.client.get("/help/"))
        self.assertIn('href="/help/orientation/"', text)
        self.assertIn('href="/help/todos/"', text)
        self.assertIn('href="/help/cli/"', text)
        # Every link inside the docs to a help page works
        for page in PAGES["en"]:
            for link in re.findall(
                r'href="(/help/[^"#]*)', article(self.client.get(url(page)))
            ):
                with self.subTest(page=page, link=link):
                    self.assertEqual(self.client.get(link).status_code, 200)
        # Links elsewhere stay as they are
        self.assertIn(
            'href="https://github.com/matthiask/biwak/tree/main/cli"',
            article(self.client.get("/help/cli/")),
        )

    def test_the_chapters_above_each_page(self):
        """All chapters in their order, the current one marked"""
        self.client.force_login(self.ada)
        response = self.client.get("/help/todos/")
        nav = response.content.decode().split('class="wb-help-chapters"', 1)[1]
        nav = nav.split("</nav>", 1)[0]
        self.assertEqual(
            re.findall(r'href="([^"]*)"', nav), [url(page) for page in PAGES["en"]]
        )
        self.assertEqual(nav.count("aria-current"), 1)
        self.assertContains(
            response, '<a href="/help/todos/" aria-current="page">To-dos</a>'
        )

    def test_html_in_the_docs_works(self):
        self.client.force_login(self.ada)
        self.assertContains(self.client.get("/help/keyboard/"), "<kbd>Ctrl</kbd>")

    def test_unknown_pages_are_not_found(self):
        self.client.force_login(self.ada)
        for page in ["missing", "README", "constitution", "todos.md"]:
            self.assertEqual(self.client.get(f"/help/{page}/").status_code, 404)


class LanguagesTest(TestCase):
    """German readers get the German pages, English as the fallback per page
    (decided 2026-11-22)"""

    def test_a_german_reader_gets_the_german_page(self):
        self.client.force_login(person("Ada", language="de"))
        response = self.client.get("/help/todos/")
        self.assertContains(response, "Mehrere auf einmal zuweisen")
        self.assertNotContains(response, 'id="help-in-english"')
        self.assertNotContains(response, '<div lang="en">')
        # The chapters in German too
        self.assertContains(
            response,
            '<a href="/help/orientation/">Sich zurechtfinden</a>',
            html=True,
        )

    def test_an_english_reader_gets_the_english_page(self):
        self.client.force_login(person("Bea", language="en"))
        response = self.client.get("/help/todos/")
        self.assertContains(response, "Assigning several at once")
        self.assertNotContains(response, "Mehrere auf einmal zuweisen")
        self.assertNotContains(response, 'id="help-in-english"')

    def test_a_missing_german_page_falls_back_to_english(self):
        self.client.force_login(person("Ada", language="de"))
        with patch.dict(PAGES["de"], {"todos": "missing.de.md"}):
            response = self.client.get("/help/todos/")
            self.assertContains(response, "Assigning several at once")
            self.assertContains(
                response, "Diese Seite der Hilfe gibt es vorerst nur auf Englisch."
            )
            self.assertContains(response, '<div lang="en">')
            # The other pages stay German
            response = self.client.get("/help/")
            self.assertContains(response, "Was Biwak nicht tut")
            self.assertNotContains(response, 'id="help-in-english"')

    def test_every_german_page_and_its_links(self):
        self.client.force_login(person("Ada", language="de"))
        for page in PAGES["de"]:
            response = self.client.get(url(page))
            with self.subTest(page=page):
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, 'id="help-in-english"')
                self.assertEqual(
                    re.findall(r'href="[^"]*\.md', response.content.decode()), []
                )
            for link in re.findall(r'href="(/help/[^"#]*)', article(response)):
                with self.subTest(page=page, link=link):
                    self.assertEqual(self.client.get(link).status_code, 200)


class ShortcutsTest(TestCase):
    """The one list of shortcuts: the keyboard page, the "?" dialog"""

    def setUp(self):
        self.ada = person("Ada")
        self.cleo = person("Cleo", client=True)
        self.client.force_login(self.ada)

    def test_the_keyboard_page_ends_with_the_list(self):
        for user in [self.ada, self.cleo]:
            self.client.force_login(user)
            text = article(self.client.get("/help/keyboard/"))
            self.assertIn('<dl class="wb-shortcuts" id="shortcuts">', text)
            self.assertIn("Go home, to projects", text)
            # After the page's own text
            self.assertGreater(
                text.index('id="shortcuts"'), text.index("Turning them off")
            )

    def test_other_pages_have_no_list_of_their_own(self):
        for page in PAGES["en"]:
            if page == "keyboard":
                continue
            self.assertNotContains(self.client.get(url(page)), 'id="shortcuts"')

    def test_the_dialog_has_the_list_and_a_link_to_the_help(self):
        for user in [self.ada, self.cleo]:
            self.client.force_login(user)
            content = self.client.get("/").content.decode()
            dialog = content.split('id="wb-shortcuts"', 1)[1].split("</dialog>", 1)[0]
            self.assertIn("The command palette", dialog)
            self.assertIn("<kbd>g</kbd> <kbd>h</kbd>", dialog)
            self.assertTrue(dialog.rstrip().endswith("</p>"))
            self.assertIn('<a href="/help/keyboard/">Help</a>', dialog)

    def test_settings_has_the_switch_and_a_link_but_no_list(self):
        for user in [self.ada, self.cleo]:
            self.client.force_login(user)
            response = self.client.get("/accounts/settings/")
            self.assertContains(response, "keyboard_shortcuts")
            self.assertContains(response, 'href="/help/keyboard/#shortcuts"')
            self.assertContains(response, "All shortcuts")
            self.assertNotContains(response, "The shortcuts")
            self.assertNotContains(response, 'class="wb-shortcuts mb-0"')
            # The dialog every page has is the only list on it
            self.assertEqual(response.content.decode().count("The command palette"), 1)


class LinksToTheHelpTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.cleo = person("Cleo", client=True)
        self.camp = project("Camp", members=[self.ada, self.cleo])
        self.list = ops.create_list(project=self.camp, title="Launch", creator=self.ada)

    def test_the_me_menu_has_help_above_sign_out(self):
        for user in [self.ada, self.cleo]:
            self.client.force_login(user)
            content = self.client.get("/").content.decode()
            menu = content.split("wb-me-button", 1)[1]
            self.assertLess(
                menu.index('<a class="dropdown-item" href="/help/">Help</a>'),
                menu.index("Sign out"),
            )

    def test_homes_useful_card_has_help(self):
        for user in [self.ada, self.cleo]:
            self.client.force_login(user)
            card = (
                self.client.get("/").content.decode().split('data-home="links"', 1)[1]
            )
            self.assertIn('<a href="/help/">Help</a>', card)

    def test_quiet_links_to_the_chapters(self):
        self.client.force_login(self.ada)
        self.assertContains(
            self.client.get("/accounts/settings/"), 'href="/help/notifications/"'
        )
        self.assertContains(
            self.client.get("/accounts/api-tokens/"), 'href="/help/cli/"'
        )
        self.assertContains(
            self.client.get("/accounts/calendar/"), 'href="/help/todos/"'
        )

    def test_the_visibility_modal_links_to_clients(self):
        self.client.force_login(self.ada)
        url = f"/items/{self.list.pk}/switch/"
        page = self.client.get(url)
        self.assertContains(page, '<a href="/help/clients/">More in the help</a>')
        # In the modal too
        self.assertContains(
            self.client.get(url, headers={"HX-Modal": "true"}), 'href="/help/clients/"'
        )
        # Other forms have no such link
        self.assertNotContains(
            self.client.get(f"/projects/{self.camp.pk}/lists/new/"), "More in the help"
        )
