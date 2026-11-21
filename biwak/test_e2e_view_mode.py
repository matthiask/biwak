"""View mode with click to edit, and the assignee picker in the browser
(frontend/view-edit.js, frontend/assignees.js, specs/ui-round-1.md)"""

from django.core.files.base import ContentFile

from biwak.items import operations as ops
from biwak.items.models import Editing, Item, Todo
from biwak.projects import operations as project_ops
from biwak.test_e2e import ASGIServerThread, E2ETestCase, expect, uvicorn


NOTES = "Two *poles*\n\n- [ ] Pegs\n- [ ] Rope"


class ViewModeTest(E2ETestCase):
    def setUp(self):
        super().setUp()
        self.todolist = ops.create_list(
            project=self.project, title="Camp", creator=self.ada, visible=True
        )
        self.todo = ops.create_todo(
            todolist=self.todolist,
            title="Order the tent",
            creator=self.ada,
            notes=NOTES,
            due_on="2027-03-01",
        )

    def saved(self):
        return Todo.objects.get(pk=self.todo.pk)

    def form(self, page):
        return page.locator("#live-text form[data-view-edit-form]")

    def test_editing_happens_inside_the_card(self):
        page = self.page
        self.goto(page, self.todo)
        card = page.locator("main .card").first
        expect(card.locator(".wb-facts")).to_be_visible()
        expect(card.locator(".wb-markdown em")).to_be_visible()
        page.locator("#live-text .wb-markdown em").click()
        # The form replaces the card's content: one card, the form inside
        expect(page.locator("#live-text .card")).to_have_count(1)
        expect(
            page.locator("#live-text .card form[data-view-edit-form]")
        ).to_be_visible()
        expect(page.locator("#live-text .wb-facts")).to_have_count(0)
        page.get_by_role("link", name="Cancel").click()
        expect(page.locator("#live-text .card .wb-facts")).to_be_visible()
        expect(page.locator("#live-text .card")).to_have_count(1)

    def test_the_page_shows_the_to_do_and_a_click_edits(self):
        page = self.page
        self.goto(page, self.todo)
        page.evaluate("window.marker = 1")
        expect(page.locator("h1")).to_contain_text("Order the tent")
        self.assertEqual(self.form(page).count(), 0)
        self.assertFalse(Editing.objects.exists())

        # The notes: the form, focused on them, without a reload
        page.locator("#live-text .wb-markdown em").click()
        expect(self.form(page)).to_be_visible()
        expect(page.locator("#live-text textarea[name=notes]")).to_be_focused()
        self.assertEqual(page.evaluate("window.marker"), 1)
        self.assertTrue(Editing.objects.filter(item=self.todo, user=self.ada).exists())
        # The heading and the Edit button give way to the form
        expect(page.locator(".wb-page-header h1")).to_be_hidden()
        # Cancel: the view, the marker gone
        page.get_by_role("link", name="Cancel").click()
        expect(self.form(page)).to_have_count(0)
        expect(page.locator("h1")).to_be_visible()
        expect(page.locator("#live-text")).to_contain_text("Pegs")
        self.assertFalse(Editing.objects.exists())

        # The title; Escape cancels an unchanged form
        page.locator("h1").click()
        expect(page.locator("#live-text input[name=title]")).to_be_focused()
        page.keyboard.press("Escape")
        expect(self.form(page)).to_have_count(0)
        # The due date
        page.get_by_text("Monday, 1. March 2027").click()
        expect(page.locator("#live-text input[name=due_on]")).to_be_focused()
        page.get_by_role("link", name="Cancel").click()
        self.assertEqual(self.errors, [])

    def test_escape_needs_two_presses_for_a_changed_form(self):
        page = self.page
        self.goto(page, self.todo)
        page.get_by_role("link", name="Edit").click()
        title = page.locator("#live-text input[name=title]")
        expect(title).to_be_focused()
        title.fill("Changed")
        page.keyboard.press("Escape")
        expect(self.form(page)).to_be_visible()
        page.keyboard.press("Escape")
        expect(self.form(page)).to_have_count(0)
        self.assertEqual(self.saved().item.title, "Order the tent")
        self.assertFalse(Editing.objects.exists())

    def test_saving_swaps_the_view_and_the_heading_back(self):
        page = self.page
        self.goto(page, self.todo)
        page.evaluate("window.marker = 1")
        page.locator("h1").click()
        page.locator("#live-text input[name=title]").fill("Order two tents")
        page.locator("#live-text textarea[name=notes]").fill("Both **big**")
        page.get_by_role("button", name="Save").click()
        expect(self.form(page)).to_have_count(0)
        expect(page.locator("h1")).to_contain_text("Order two tents")
        expect(page.locator("#live-text strong")).to_have_text("big")
        self.assertEqual(page.evaluate("window.marker"), 1)
        self.assertEqual(Item.objects.get(pk=self.todo.pk).title, "Order two tents")
        self.assertFalse(Editing.objects.exists())
        # Errors stay in the form
        page.locator("h1").click()
        page.locator("#live-text input[name=title]").fill("")
        page.locator("#live-text input[name=title]").evaluate(
            "el => el.required = false"
        )
        page.get_by_role("button", name="Save").click()
        expect(page.locator("#live-text")).to_contain_text("This field is required")
        expect(self.form(page)).to_be_visible()
        self.assertEqual(self.errors, [])

    def test_ticking_in_view_mode_and_not_while_editing(self):
        page = self.page
        self.goto(page, self.todo)
        boxes = page.locator("#live-text input[type=checkbox]")
        boxes.first.check()
        expect(boxes.first).to_be_enabled()
        expect(boxes.first).to_be_checked()
        # Ticking didn't open the form
        self.assertEqual(self.form(page).count(), 0)
        self.assertIn("[x] Pegs", self.saved().notes)
        # Somebody else has the form open: ticking is refused with the reason
        bob = self.login(self.bob)
        project_ops.add_member(self.project, self.bob, actor=self.ada)
        self.goto(bob, self.todo)
        bob.get_by_role("link", name="Edit").click()
        expect(bob.locator("#live-text textarea[name=notes]")).to_be_visible()
        boxes.last.check()
        expect(page.locator(".wb-tick-note[role=status]")).to_contain_text(
            "Bob is editing this"
        )
        bob.get_by_role("link", name="Cancel").click()
        expect(self.form(bob)).to_have_count(0)
        self.assertFalse(Editing.objects.exists())
        self.assertEqual(self.errors, [])

    def test_a_link_in_the_text_doesnt_open_the_form(self):
        ops.update_todo(
            self.todo, actor=self.ada, notes="See [the plan](https://example.org/p)"
        )
        page = self.page
        self.goto(page, self.todo)
        link = page.locator("#live-text a", has_text="the plan")
        link.evaluate("el => el.addEventListener('click', e => e.preventDefault())")
        link.click()
        self.assertEqual(self.form(page).count(), 0)

    def test_without_javascript_edit_is_a_page(self):
        context = self.browser.new_context(java_script_enabled=False)
        self.contexts.append(context)
        page = context.new_page()
        from django.test import Client

        client = Client()
        client.force_login(self.ada)
        context.add_cookies([
            {
                "name": "sessionid",
                "value": client.cookies["sessionid"].value,
                "url": self.live_server_url,
            }
        ])
        self.goto_plain = page.goto(
            f"{self.live_server_url}{self.todo.get_absolute_url()}"
        )
        page.get_by_role("link", name="Edit").click()
        page.wait_for_url("**/edit/")
        page.locator("#live-text input[name=title]").fill("Plain")
        page.get_by_role("button", name="Save").click()
        page.wait_for_url(f"**{self.todo.get_absolute_url()}")
        self.assertEqual(Item.objects.get(pk=self.todo.pk).title, "Plain")

    def test_the_end_fields_show_with_a_repeat_only(self):
        page = self.page
        self.goto(page, self.todo)
        page.get_by_role("link", name="Edit").click()
        ends = page.locator("[data-rule-ends]")
        expect(ends).to_have_count(1)
        expect(ends).to_be_hidden()
        page.locator("[data-rule-frequency]").select_option("weekly")
        expect(ends).to_be_visible()
        # Inside the rule's fieldset
        self.assertEqual(
            page.locator("fieldset.wb-rule [name=recurrence_count]").count(), 1
        )
        ends.locator("[name=recurrence_count]").fill("3")
        page.get_by_role("button", name="Save").click()
        expect(page.locator("#live-text")).to_contain_text("3 more to come")
        self.assertEqual(self.saved().recurrence_count, 3)

    def test_a_message_is_clicked_to_edit(self):
        message = ops.create_message(
            project=self.project, title="News", content="Hello *camp*", creator=self.ada
        )
        page = self.page
        self.goto(page, message)
        page.locator("#live-text em").click()
        expect(page.locator("#live-text textarea[name=content]")).to_be_focused()
        page.locator("#live-text textarea[name=content]").fill("Hello everybody")
        page.get_by_role("button", name="Save").click()
        expect(page.locator("#live-text")).to_have_text("Hello everybody")
        page.locator("h1").click()
        expect(page.locator("#live-text input[name=title]")).to_be_focused()
        page.keyboard.press("Escape")
        expect(self.form(page)).to_have_count(0)
        self.assertFalse(Editing.objects.exists())
        self.assertEqual(self.errors, [])

    def test_a_file_is_clicked_to_edit(self):
        upload = ops.create_upload(
            project=self.project,
            file=ContentFile(b"x", name="plan.txt"),
            creator=self.ada,
        )
        page = self.page
        self.goto(page, upload)
        page.get_by_text("Add a description…").click()
        expect(page.locator("#live-text textarea[name=description]")).to_be_focused()
        page.locator("#live-text textarea[name=description]").fill("The plan")
        page.get_by_role("button", name="Save").click()
        expect(page.locator("#live-text")).to_contain_text("The plan")
        self.assertEqual(self.errors, [])

    def test_a_clients_view(self):
        cleo = self.login(self.cleo)
        self.goto(cleo, self.todo)
        expect(cleo.locator("h1")).to_contain_text("Order the tent")
        # To-dos are shared work: a client edits too
        cleo.locator("h1").click()
        expect(cleo.locator("#live-text input[name=title]")).to_be_focused()
        cleo.get_by_role("link", name="Cancel").click()
        expect(self.form(cleo)).to_have_count(0)
        self.assertEqual(self.errors, [])


class PickerTest(E2ETestCase):
    def setUp(self):
        super().setUp()
        self.dora = self.bob  # Staff, not a member
        self.todolist = ops.create_list(
            project=self.project, title="Camp", creator=self.ada, visible=True
        )
        self.todo = ops.create_todo(
            todolist=self.todolist, title="Order the tent", creator=self.ada
        )

    def open_form(self, page):
        self.goto(page, self.todo)
        page.get_by_role("link", name="Edit").click()
        return page.locator(".wb-picker-input")

    def test_choosing_filtering_and_removing(self):
        page = self.page
        field = self.open_form(page)
        listbox = page.locator(".wb-picker-list")
        expect(listbox).to_be_hidden()
        field.click()
        expect(listbox).to_be_visible()
        # Members first, the non-member says so
        names = listbox.locator("li").all_inner_texts()
        # Each with their mark (the initials) before the name
        self.assertIn("Ada", names[0])
        self.assertIn("Cleo", names[1])
        self.assertIn("not in the project yet", names[2])
        # Typing filters; the arrow keys and Enter pick
        field.press_sequentially("bo")
        expect(listbox.locator("li")).to_have_count(1)
        field.press("Enter")
        expect(page.locator(".wb-pill")).to_have_text("BEBob×")  # with the mark
        # Escape closes the list but not the form
        field.press("Escape")
        expect(listbox).to_be_hidden()
        expect(page.locator("form[data-view-edit-form]")).to_be_visible()
        field.press("ArrowDown")
        field.press("ArrowDown")
        field.press("Enter")
        expect(page.locator(".wb-pill")).to_have_count(2)
        # × removes, Backspace takes the last one
        page.get_by_role("button", name="Remove Bob").click()
        expect(page.locator(".wb-pill")).to_have_count(1)
        field.press("Backspace")
        expect(page.locator(".wb-pill")).to_have_count(0)
        # Save: pills match what's posted
        field.click()
        listbox.locator("li", has_text="Bob").click()
        page.get_by_role("button", name="Save").click()
        expect(page.locator("form[data-view-edit-form]")).to_have_count(0)
        expect(page.locator("#live-text")).to_contain_text("Bob")
        self.assertEqual(list(self.todo.todo.assignees.all()), [self.bob])
        # Assigning made Bob a member
        self.assertTrue(self.project.memberships.filter(user=self.bob).exists())
        self.assertEqual(self.errors, [])

    def test_clicking_the_assignees_focuses_the_field(self):
        page = self.page
        self.goto(page, self.todo)
        page.get_by_text("Nobody").click()
        expect(page.locator(".wb-picker-input")).to_be_focused()

    def test_clients_only_get_members(self):
        cleo = self.login(self.cleo)
        field = self.open_form(cleo)
        field.click()
        texts = cleo.locator(".wb-picker-list li").all_inner_texts()
        self.assertEqual(len(texts), 2)
        self.assertFalse(any("Bob" in text for text in texts))
        self.assertFalse(any("not in the project" in text for text in texts))

    def test_the_inline_form(self):
        page = self.page
        self.goto(page, self.todolist)
        add = page.locator("[data-add-todo]").first
        add.locator("summary").click()
        add.locator(".wb-picker-input").click()
        add.locator(".wb-picker-list li", has_text="Cleo").click()
        add.locator("[name=title]").fill("With Cleo")
        add.locator("[name=title]").press("Control+Enter")
        page.locator("[data-todo]", has_text="With Cleo").wait_for()
        todo = Item.objects.get(title="With Cleo")
        self.assertEqual(list(todo.todo.assignees.all()), [self.cleo])
        # The form is ready for the next one
        expect(add.locator(".wb-pill")).to_have_count(0)
        self.assertEqual(self.errors, [])


class LiveViewTest(E2ETestCase):
    """Live updates (specs/lantern.md) in view mode and around the form"""

    host = "127.0.0.1"
    server_thread_class = ASGIServerThread

    @classmethod
    def setUpClass(cls):
        if uvicorn is None:  # pragma: no cover
            raise cls.skipTest(cls, "uvicorn isn't installed")
        super().setUpClass()

    def setUp(self):
        super().setUp()
        todolist = ops.create_list(
            project=self.project, title="Camp", creator=self.ada, visible=True
        )
        self.todo = ops.create_todo(
            todolist=todolist, title="Order the tent", creator=self.ada
        )

    def test_live_updates_keep_working_in_view_mode(self):
        page = self.page
        self.goto(page, self.todo)
        expect(page.locator("body")).to_have_attribute("data-live-state", "connected")
        project_ops.add_member(self.project, self.bob, actor=self.ada)
        bob = self.login(self.bob)
        self.goto(bob, self.todo)
        bob.locator("#live-text .wb-view-text").click()
        bob.locator("#live-text textarea[name=notes]").fill("Fresh notes")
        bob.get_by_role("button", name="Save").click()
        expect(page.locator("#live-text")).to_contain_text("Fresh notes")
        bob.locator("h1").click()
        bob.locator("#live-text input[name=title]").fill("Order the big tent")
        bob.get_by_role("button", name="Save").click()
        expect(page.locator("h1")).to_contain_text("Order the big tent")
        self.assertEqual(self.errors, [])
