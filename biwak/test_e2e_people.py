"""People in the browser: avatars, teams and the client's view"""

import re

from django.urls import reverse

from biwak.items.models import Comment, Item
from biwak.test_e2e import E2ETestCase, expect
from biwak.test_utils import person


class AvatarTest(E2ETestCase):
    """The mark in what scripts build (specs/people.md): the assignee
    picker, the @ list; the image loads through the permission-checked
    view, with the session"""

    def setUp(self):
        super().setUp()
        from biwak.accounts import operations as account_ops
        from biwak.accounts.test_images import picture

        account_ops.set_image(self.ada, picture(), actor=self.ada)

    def test_the_assignee_picker_shows_marks(self):
        todolist = self.make_list()
        page = self.page
        self.goto(page, todolist)
        add = page.locator("[data-add-todo]").first
        add.locator("summary").click()
        add.locator(".wb-picker-input").click()
        options = add.locator(".wb-picker-list li")
        ada = options.filter(has_text="Ada")
        expect(ada.locator("img.wb-avatar")).to_have_count(1)
        # The drawn mark without an image: white through the drawing's mask
        bob = options.filter(has_text="Bob").locator("span.wb-avatar")
        expect(bob).to_have_class(re.compile(rf"wb-mark-{self.bob.mark}\b"))
        expect(bob).to_have_text("")
        mask = bob.evaluate(
            "el => getComputedStyle(el, '::before').maskImage"
            " || getComputedStyle(el, '::before').webkitMaskImage"
        )
        self.assertIn("url(", mask)
        ada.click()
        pill = add.locator(".wb-pill")
        expect(pill.locator("img.wb-avatar")).to_have_count(1)
        page.wait_for_function(
            "() => document.querySelector('.wb-pill img.wb-avatar').naturalWidth === 256"
        )
        self.assertEqual(self.errors, [])

    def test_the_mention_list_shows_marks(self):
        self.make_list(todos=["Plan"])
        page = self.page
        self.goto(page, Item.objects.get(title="Plan"))
        textarea = page.locator("form:has([name=form][value=comment]) textarea")
        self.editor(textarea).click()
        self.editor(textarea).press_sequentially("Hi @Example")
        listbox = page.locator(".wb-mentions:not([hidden])")
        listbox.wait_for()
        ada = listbox.locator("li", has_text="Ada")
        expect(ada.locator("img.wb-avatar")).to_have_count(1)
        expect(
            listbox.locator("li", has_text="Bob").locator("span.wb-avatar")
        ).to_have_class(re.compile(rf"wb-mark-{self.bob.mark}\b"))
        page.wait_for_function(
            "() => document.querySelector('.wb-mentions img.wb-avatar').naturalWidth === 256"
        )

    def test_an_image_which_does_not_load_falls_back_to_the_drawn_mark(self):
        """The script lists the image URL of everybody; where the view
        answers 404 (someone the viewer may not know, here a file gone) the
        drawn mark takes its place"""
        from django.core.files.storage import default_storage

        default_storage.delete(self.ada.image)
        todolist = self.make_list()
        page = self.page
        self.goto(page, todolist)
        add = page.locator("[data-add-todo]").first
        add.locator("summary").click()
        add.locator(".wb-picker-input").click()
        add.locator(".wb-picker-list li", has_text="Ada").click()
        expect(add.locator(".wb-pill span.wb-avatar")).to_have_class(
            re.compile(rf"wb-mark-{self.ada.mark}\b")
        )
        expect(add.locator(".wb-pill img")).to_have_count(0)


class TeamsTest(E2ETestCase):
    """Picking a team (specs/teams.md) in the people picker and the @ list:
    its members who can be there, the entry saying how many are left out
    and why"""

    def setUp(self):
        super().setUp()
        from biwak.projects.models import Membership
        from biwak.teams import operations as team_ops

        self.dan = person("Dan", notification_level="concerns_me")
        Membership.objects.create(project=self.project, user=self.dan)
        self.cleo.notification_level = "concerns_me"
        self.cleo.save()
        # Bob isn't a member, Cleo is a client
        team_ops.create_team(
            name="Design team",
            members=[self.ada, self.bob, self.cleo, self.dan],
            actor=self.ada,
        )

    def test_the_picker_adds_the_members_who_can_be_assigned(self):
        todolist = self.make_list()
        page = self.page
        self.goto(page, todolist)
        add = page.locator("[data-add-todo]").first
        add.locator("summary").click()
        # Opening focuses the title: only then to the picker
        expect(add.locator("[name=title]")).to_be_focused()
        picker = add.locator(".wb-picker-input")
        picker.click()
        # Teams come after the people (decided 2026-11-22)
        options = add.locator(".wb-picker-list li")
        expect(options.last).to_have_attribute("data-team", re.compile(r"\d"))
        expect(options.first).not_to_have_attribute("data-team", re.compile(".*"))
        picker.press_sequentially("desi")
        team = add.locator(".wb-picker-list li[data-team]")
        expect(team).to_contain_text("Design team")
        # Assigning Bob would make him a member; Cleo can't see the list
        expect(team).to_contain_text(
            "team · 2 of 4: 1 not a member of this project, 1 can't see internal items"
        )
        expect(team.locator(".wb-team-mark")).to_have_count(1)
        # The only match, so Enter picks it
        picker.press("Enter")
        pills = add.locator(".wb-pill")
        expect(pills).to_have_text([re.compile("Ada"), re.compile("Dan")])
        # Nobody left to add: not offered any more
        picker.press_sequentially("desi")
        expect(add.locator(".wb-picker-list")).to_contain_text("Nobody found")
        picker.press("Escape")
        # Removing a pill is removing a person; the team adds only Dan then
        picker.press("Backspace")
        expect(pills).to_have_text([re.compile("Ada")])
        picker.press_sequentially("desi")
        picker.press("Enter")
        expect(pills).to_have_text([re.compile("Ada"), re.compile("Dan")])
        add.locator("[name=title]").fill("Sketch")
        add.locator("[name=title]").press("ControlOrMeta+Enter")
        page.locator("[data-todo]", has_text="Sketch").wait_for()
        todo = Item.objects.get(title="Sketch")
        self.assertEqual(
            set(todo.todo.assignees.all()), {self.ada, self.dan}, "people only"
        )
        self.assertEqual(self.errors, [])

    def test_the_picker_follows_visible_to_clients(self):
        """ "Also tell…" when posting at the top: the client is added only
        while the message is visible to clients"""
        page = self.page
        page.goto(self.live_server_url + reverse("message_new", args=[self.project.pk]))
        picker = page.locator(".wb-picker-input")
        picker.press_sequentially("design")
        team = page.locator(".wb-picker-list li[data-team]")
        # Ada posts (in already), Bob isn't a member
        expect(team).to_contain_text(
            "2 of 4: 1 not a member of this project, 1 can't see internal items"
        )
        picker.press("Escape")
        page.get_by_label("Visible to clients").check()
        picker.press_sequentially("design")
        expect(team).to_contain_text("3 of 4: 1 not a member of this project")
        picker.press("Enter")
        expect(page.locator(".wb-pill")).to_have_text([
            re.compile("Cleo"),
            re.compile("Dan"),
        ])
        self.assertEqual(self.errors, [])

    def test_check_ins_people_asked_follow_visible_to_clients(self):
        """A check-in's "People asked" is the picker with teams (decided
        2026-11-22); clients only while it's visible to clients"""
        page = self.page
        page.goto(
            self.live_server_url + reverse("question_new", args=[self.project.pk])
        )
        pills = page.locator(".wb-pill")
        # The one creating it is asked by default
        expect(pills).to_have_text([re.compile("Ada")])
        picker = page.locator(".wb-picker-input")
        picker.press_sequentially("design")
        team = page.locator(".wb-picker-list li[data-team]")
        expect(team).to_contain_text("1 can't see internal items")
        picker.press("Escape")
        page.get_by_label("Visible to clients").check()
        picker.press_sequentially("design")
        expect(team).not_to_contain_text("can't see internal items")
        picker.press("Enter")
        expect(pills).to_have_count(4)
        expect(page.locator(".wb-picker")).to_contain_text("Cleo")
        # Unticking takes the client away again
        page.get_by_label("Visible to clients").uncheck()
        expect(pills).to_have_count(3)
        expect(page.locator(".wb-picker")).not_to_contain_text("Cleo")
        self.assertEqual(self.errors, [])

    def test_the_mention_list_inserts_a_mention_per_member(self):
        self.make_list(todos=["Plan"])
        todo = Item.objects.get(title="Plan")
        page = self.page
        self.goto(page, todo)
        textarea = page.locator("form:has([name=form][value=comment]) textarea")
        # Dan is mentioned already: not twice
        self.set_markdown(textarea, f"[@Dan](person:{self.dan.pk}) and")
        self.editor(textarea).press("ControlOrMeta+End")
        self.editor(textarea).press_sequentially(" @desi")
        listbox = page.locator(".wb-mentions:not([hidden])")
        listbox.wait_for()
        team = listbox.locator("li[data-team]")
        expect(team).to_contain_text("Design team")
        # Bob sees the all-access project's internal items
        expect(team).to_contain_text("3 of 4: 1 can't see internal items")
        expect(team).to_have_class(re.compile("active"))
        self.editor(textarea).press("Enter")
        self.assertEqual(
            textarea.input_value(),
            f"[@Dan](person:{self.dan.pk}) and [@Ada](person:{self.ada.pk})"
            f" [@Bob](person:{self.bob.pk}) ",
        )
        page.get_by_role("button", name="Add comment").click()
        page.locator(".wb-markdown .wb-mention").first.wait_for()
        content = Comment.objects.get(item=todo).content
        self.assertNotIn("Design", content)
        self.assertEqual(self.errors, [])

    def test_clients_find_no_teams(self):
        self.make_list("Shared", visible=True, todos=["Review"])
        todo = Item.objects.get(title="Review")
        page = self.login(self.cleo)
        self.goto(page, todo)
        textarea = page.locator("form:has([name=form][value=comment]) textarea")
        self.editor(textarea).click()
        self.editor(textarea).press_sequentially("@Example")
        listbox = page.locator(".wb-mentions:not([hidden])")
        listbox.wait_for()
        expect(listbox.locator("li[data-team]")).to_have_count(0)
        self.assertNotIn("Design", listbox.inner_text())


class ClientTest(E2ETestCase):
    """What clients see and may do is server-rendered (test_views.py),
    their inline add is JavaScript"""

    def test_a_client_adds_to_dos_inline(self):
        todolist = self.make_list("Shared", visible=True, todos=["A"])
        page = self.login(self.cleo)
        self.goto(page, todolist)
        add = page.locator("[data-add-todo]").first
        add.locator("summary").click()
        add.locator("[name=title]").fill("From the client")
        add.locator("[name=title]").press("ControlOrMeta+Enter")
        page.locator("[data-todo]", has_text="From the client").wait_for()
        created = Item.objects.get(title="From the client")
        self.assertEqual(created.creator, self.cleo)
        self.assertTrue(created.is_client_visible)
        self.assertEqual(self.errors, [])
