"""People away in what scripts build (specs/quiet-hours.md): the away sign
and "away until …" in the people picker and the @ list, and the note shown
once in the form when assigning or mentioning them"""

import datetime as dt

from django.utils import timezone

from biwak.accounts import operations as account_ops
from biwak.accounts.quiet import away_detail, away_notice
from biwak.items.models import Item
from biwak.projects.models import Membership
from biwak.test_e2e import E2ETestCase, expect


class AwayTest(E2ETestCase):
    def setUp(self):
        super().setUp()
        account_ops.set_away(
            self.bob,
            until=timezone.localdate() + dt.timedelta(days=10),
            note="back soon, ask Ada meanwhile",
            actor=self.bob,
        )
        self.detail = away_detail(self.bob)
        self.notice = away_notice(self.bob, "Bob")

    def open_picker(self, page, todolist):
        self.goto(page, todolist)
        add = page.locator("[data-add-todo]").first
        add.locator("summary").click()
        add.locator(".wb-picker-input").click()
        return add

    def test_the_picker(self):
        page = self.page
        add = self.open_picker(page, self.make_list())
        bob = add.locator(".wb-picker-list li", has_text="Bob")
        expect(bob).to_contain_text(self.detail)
        expect(bob.locator(".wb-away-sign")).to_have_count(1)
        expect(add.locator(".wb-picker-list li", has_text="Ada")).not_to_contain_text(
            "away"
        )
        bob.click()
        notes = add.locator(".wb-away-note")
        expect(notes).to_have_text([self.notice])
        expect(add.locator(".wb-pill .wb-away-sign")).to_have_count(1)
        # Once: taken away and picked again, no second note
        add.locator(".wb-pill-remove").click()
        add.locator(".wb-picker-input").click()
        add.locator(".wb-picker-list li", has_text="Bob").click()
        expect(notes).to_have_count(1)
        self.assertEqual(self.errors, [])

    def test_the_mention_list(self):
        self.make_list(todos=["Plan"])
        page = self.page
        self.goto(page, Item.objects.get(title="Plan"))
        form = page.locator("form:has([name=form][value=comment])")
        editor = self.editor(form.locator("textarea"))
        editor.click()
        editor.press_sequentially("Hi @Bo")
        listbox = page.locator(".wb-mentions:not([hidden])")
        bob = listbox.locator("li", has_text="Bob")
        expect(bob).to_contain_text(self.detail)
        expect(bob.locator(".wb-away-sign")).to_have_count(1)
        editor.press("Enter")
        notes = form.locator(".wb-away-note")
        expect(notes).to_have_text([self.notice])
        editor.press_sequentially("and @Bo")
        expect(listbox.locator("li", has_text="Bob")).to_be_visible()
        editor.press("Enter")
        page.wait_for_function(
            "el => el.value.split('(person:').length === 3",
            arg=form.locator("textarea").element_handle(),
        )
        expect(notes).to_have_count(1)
        self.assertEqual(self.errors, [])

    def test_a_clients_view(self):
        """Clients see the sign and the note of the members they may know"""
        Membership.objects.create(project=self.project, user=self.bob)
        page = self.login(self.cleo)
        add = self.open_picker(page, self.make_list(visible=True))
        bob = add.locator(".wb-picker-list li", has_text="Bob")
        expect(bob).to_contain_text(self.detail)
        bob.click()
        expect(add.locator(".wb-away-note")).to_have_text([self.notice])
        self.assertEqual(self.errors, [])
