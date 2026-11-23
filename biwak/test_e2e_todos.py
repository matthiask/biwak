"""To-dos in the browser: lists, the to-do page, completing and the
repeat rule widget"""

import re

from django.urls import reverse

from biwak.accounts.models import User
from biwak.files.models import Attachment
from biwak.items import operations as ops
from biwak.items.models import Comment, Item
from biwak.organizations.models import Organization
from biwak.reactions.models import Reaction
from biwak.test_e2e import E2ETestCase, emoji_rows, expect


class TodosTest(E2ETestCase):
    def test_adding_todos(self):
        """The form opens in place, saves without leaving the page and stays
        open: Ctrl+Enter saves, notes, assignees and due date arrive"""
        todolist = self.make_list()
        page = self.page
        self.goto(page, todolist)
        page.evaluate("window.marker = 1")
        add = page.locator("[data-add-todo]").first
        add.locator("summary").click()
        title = add.locator("[name=title]")
        expect(title).to_be_focused()

        title.fill("Write the brief")
        self.set_markdown(add.locator("[name=notes]"), "Two pages, *short*")
        picker = add.locator(".wb-picker-input")
        picker.click()
        add.locator(".wb-picker-list li", has_text="Ada").click()
        add.locator("[name=due_on]").fill("2026-12-24")
        title.press("ControlOrMeta+Enter")
        rows = page.locator("[data-todo]")
        rows.filter(has_text="Write the brief").wait_for()
        self.assertEqual(page.evaluate("window.marker"), 1)
        expect(rows.first.locator(".wb-row-people")).to_contain_text("Ada")
        expect(rows.first.locator(".wb-row-people .wb-avatar")).to_have_count(1)
        self.assertIn("24 Dec", rows.first.inner_text())
        # Ready for the next one
        self.assertEqual(title.input_value(), "")
        self.assertEqual(add.locator("[name=notes]").input_value(), "")
        expect(add.locator(".wb-pill")).to_have_count(0)
        expect(title).to_be_focused()

        title.fill("Send it")
        title.press("ControlOrMeta+Enter")
        rows.filter(has_text="Send it").wait_for()
        self.assertEqual(rows.count(), 2)

        # Escape closes, what's typed stays
        title.fill("Unfinished")
        title.press("Escape")
        self.assertFalse(add.evaluate("el => el.open"))
        add.locator("summary").click()
        self.assertEqual(title.input_value(), "Unfinished")
        # A click elsewhere closes it too
        page.locator("h1").click()
        self.assertFalse(add.evaluate("el => el.open"))

        self.assertEqual(
            [t for t, _ in self.order(todolist)], ["Write the brief", "Send it"]
        )
        first = Item.objects.get(title="Write the brief")
        self.assertEqual(first.todo.notes, "Two pages, *short*")
        self.assertEqual(list(first.todo.assignees.all()), [self.ada])
        self.assertEqual(str(first.todo.due_on), "2026-12-24")
        self.assertEqual(first.creator, self.ada)
        self.assertEqual(self.errors, [])

    def test_removing_a_pill_keeps_the_form_open(self):
        """× removes the pill, not the form: the click is inside the form
        although the button is gone from the page by then"""
        todolist = self.make_list()
        page = self.page
        self.goto(page, todolist)
        add = page.locator("[data-add-todo]").first
        add.locator("summary").click()
        add.locator(".wb-picker-input").click()
        add.locator(".wb-picker-list li", has_text="Ada").click()
        add.locator(".wb-pill-remove").click()
        expect(add.locator(".wb-pill")).to_have_count(0)
        self.assertTrue(add.evaluate("el => el.open"))
        self.assertEqual(self.errors, [])

    def test_a_new_row_has_a_working_peek_button(self):
        """htmx processes the row the script inserted"""
        todolist = self.make_list()
        page = self.page
        self.goto(page, todolist)
        add = page.locator("[data-add-todo]").first
        add.locator("summary").click()
        add.locator("[name=title]").fill("Fresh")
        self.set_markdown(add.locator("[name=notes]"), "Some **notes**")
        add.locator("[name=title]").press("ControlOrMeta+Enter")
        row = page.locator("[data-todo]", has_text="Fresh")
        row.wait_for()
        row.locator("[data-peek]").first.click()
        row.locator(".wb-peek-body").wait_for()
        self.assertEqual(self.errors, [])

    def test_adding_with_an_expired_session_inserts_no_page(self):
        todolist = self.make_list()
        page = self.page
        self.goto(page, todolist)
        add = page.locator("[data-add-todo]").first
        add.locator("summary").click()
        page.context.clear_cookies()
        add.locator("[name=title]").fill("Lost")
        add.locator("[name=title]").press("ControlOrMeta+Enter")
        error = add.locator("[data-add-todo-error]")
        expect(error).to_be_visible()
        self.assertEqual(page.locator("[data-todo]").count(), 0)
        self.assertNotIn("<", error.inner_html())
        self.assertLess(len(error.inner_text()), 80)
        self.assertEqual(add.locator("[name=title]").input_value(), "Lost")

    def test_adding_with_a_server_error_shows_no_page(self):
        todolist = self.make_list()
        page = self.page
        self.goto(page, todolist)
        page.route(
            "**/lists/**",
            lambda route: (
                route.fulfill(
                    status=500,
                    content_type="text/html",
                    body="<html><body>Server Error (500)</body></html>",
                )
                if route.request.method == "POST"
                else route.continue_()
            ),
        )
        add = page.locator("[data-add-todo]").first
        add.locator("summary").click()
        add.locator("[name=title]").fill("Lost")
        add.locator("[name=title]").press("ControlOrMeta+Enter")
        error = add.locator("[data-add-todo-error]")
        expect(error).to_be_visible()
        self.assertNotIn("Server Error", error.inner_text())

    def test_adding_to_a_group_and_one_form_open(self):
        todolist = self.make_list(groups=["Soon"])
        page = self.page
        self.goto(page, todolist)
        forms = page.locator("[data-add-todo]")
        forms.nth(1).locator("summary").click()
        forms.nth(1).locator("[name=title]").fill("In the group")
        forms.nth(1).locator("[name=title]").press("ControlOrMeta+Enter")
        page.locator(
            "[data-group-item] [data-todo]", has_text="In the group"
        ).wait_for()
        # Opening the other form closes this one
        forms.nth(0).locator("summary").click()
        self.assertFalse(forms.nth(1).evaluate("el => el.open"))
        self.assertEqual(self.order(todolist), [("In the group", "Soon")])

    def test_adding_with_mention_in_notes(self):
        """The title and the notes of the inline form list people too"""
        todolist = self.make_list()
        page = self.page
        self.goto(page, todolist)
        add = page.locator("[data-add-todo]").first
        add.locator("summary").click()
        notes = add.locator("[name=notes]")
        self.editor(notes).click()
        self.editor(notes).press_sequentially("Ask @Bo")
        page.locator(".wb-mentions:not([hidden])").first.wait_for()
        self.editor(notes).press("Enter")  # Picks, doesn't save or close
        self.assertEqual(notes.input_value(), f"Ask [@Bob](person:{self.bob.pk}) ")
        self.assertTrue(add.evaluate("el => el.open"))
        add.locator("[name=title]").fill("Ask")
        add.locator("[name=title]").press("ControlOrMeta+Enter")
        page.locator("[data-todo]", has_text="Ask").wait_for()
        self.assertEqual(
            Item.objects.get(title="Ask").todo.notes,
            f"Ask [@Bob](person:{self.bob.pk})",
        )

    def test_dragging_within_and_between_groups(self):
        todolist = self.make_list(
            groups=["Soon"], todos=["A", "B", "C", ("D", "Soon"), ("E", "Soon")]
        )
        page = self.page
        self.goto(page, todolist)

        def move(source, target):
            with page.expect_response("**/todos/move/"):
                page.locator("[data-todo]", has_text=source).locator(
                    "[data-handle]"
                ).drag_to(
                    page.locator("[data-todo]", has_text=target),
                    target_position={"x": 40, "y": 3},
                )

        # Within a group
        move("C", "A")
        self.assertEqual(
            self.order(todolist),
            [("C", None), ("A", None), ("B", None), ("D", "Soon"), ("E", "Soon")],
        )
        # Between groups, the order stored among the new neighbours
        move("B", "E")
        self.assertEqual(
            self.order(todolist),
            [("C", None), ("A", None), ("D", "Soon"), ("B", "Soon"), ("E", "Soon")],
        )
        # The page shows what's stored
        self.goto(page, todolist)
        self.assertEqual(
            page.locator(
                "[data-group-item] [data-todo] .wb-todo-title"
            ).all_inner_texts(),
            ["D", "B", "E"],
        )
        self.assertEqual(self.errors, [])

    def test_a_drag_the_server_doesnt_get_reloads_the_page(self):
        """Offline, the page shows what the server has again"""
        todolist = self.make_list(todos=["A", "B", "C"])
        page = self.page
        self.goto(page, todolist)
        page.evaluate("window.marker = 1")
        page.route("**/todos/move/", lambda route: route.abort())
        page.locator("[data-todo]", has_text="A").locator("[data-handle]").drag_to(
            page.locator("[data-todo]", has_text="C"),
            target_position={"x": 40, "y": 15},
        )
        page.wait_for_function("window.marker === undefined")
        page.unroute("**/todos/move/")
        titles = page.locator("[data-todo] .wb-todo-title")
        self.assertEqual(titles.all_inner_texts(), ["A", "B", "C"])

    def test_selecting_several_and_moving_them(self):
        todolist = self.make_list(
            groups=["Soon"], todos=["A", "B", "C", "D", ("E", "Soon"), ("F", "Soon")]
        )
        page = self.page
        self.goto(page, todolist)
        for title in ["A", "C"]:
            page.locator("[data-todo]", has_text=title).locator("[data-handle]").click()
        self.assertEqual(page.locator("[data-todo].is-selected").count(), 2)
        with page.expect_response("**/todos/move/"):
            page.locator("[data-todo]", has_text="A").locator("[data-handle]").drag_to(
                page.locator("[data-todo]", has_text="E"),
                target_position={"x": 40, "y": 3},
            )
        stored = self.order(todolist)
        self.assertEqual(stored[:2], [("B", None), ("D", None)])
        soon = [title for title, group in stored[2:] if group == "Soon"]
        # Both moved together, in their order, the others kept theirs
        self.assertEqual(len(soon), 4)
        self.assertEqual(soon.index("C"), soon.index("A") + 1)
        self.assertEqual([t for t in soon if t in "EF"], ["E", "F"])
        # The selection is cleared
        self.assertEqual(page.locator("[data-todo].is-selected").count(), 0)
        self.assertEqual(self.errors, [])

    def test_board(self):
        """In the board's columns dragging works the same"""
        todolist = self.make_list(groups=["Doing"], todos=["A", "B", ("C", "Doing")])
        page = self.page
        self.goto(page, f"{todolist.get_absolute_url()}?view=board")
        self.assertEqual(page.locator(".wb-todolist.is-board").count(), 1)
        with page.expect_response("**/todos/move/"):
            page.locator("[data-todo]", has_text="A").locator("[data-handle]").drag_to(
                page.locator("[data-todo]", has_text="C"),
                target_position={"x": 40, "y": 3},
            )
        self.assertEqual(
            self.order(todolist), [("B", None), ("A", "Doing"), ("C", "Doing")]
        )

    def test_a_group_menu_on_the_board_is_not_cut_off(self):
        """The board's columns scroll sideways inside it, which cuts off
        what sticks out; the menu shows whole all the same"""
        groups = ["Design", "Build", "Ship", "Polish"]
        todolist = self.make_list(groups=groups, todos=[("Task", g) for g in groups])
        page = self.page
        page.set_viewport_size({"width": 390, "height": 700})
        self.goto(page, f"{todolist.get_absolute_url()}?view=board")
        page.get_by_title("Edit, move or remove the group").first.click()
        menu = page.locator("details.wb-menu[open] > .dropdown-menu")
        expect(menu).to_be_visible()
        # Every entry can be clicked: the topmost element at its middle
        for item in menu.locator(".dropdown-item").all():
            box = item.bounding_box()
            hit = page.evaluate(
                "([x, y]) => document.elementFromPoint(x, y)?.textContent.trim()",
                [box["x"] + box["width"] / 2, box["y"] + box["height"] / 2],
            )
            self.assertEqual(hit, item.text_content().strip())
        # Clicking the last one works
        with page.expect_navigation():
            menu.get_by_role("button", name="Move down").click()
        self.assertEqual(
            list(todolist.todolist.groups.values_list("title", flat=True)),
            ["Build", "Design", "Ship", "Polish"],
        )
        self.assertEqual(self.errors, [])

    def test_dragging_groups(self):
        todolist = self.make_list(groups=["One", "Two"], todos=[])
        page = self.page
        self.goto(page, todolist)
        with page.expect_response("**/groups/*/move/"):
            page.locator(
                '[data-group-item]:has(.wb-group-name:text-is("Two"))'
            ).locator("[data-group-handle]").drag_to(
                page.locator('[data-group-item]:has(.wb-group-name:text-is("One"))'),
                target_position={"x": 40, "y": 3},
            )
        self.assertEqual(
            list(todolist.todolist.groups.values_list("title", flat=True)),
            ["Two", "One"],
        )

    def test_peek(self):
        """The first click loads notes and the newest comments, the next
        one closes"""
        todolist = self.make_list(todos=["Plan"])
        todo = Item.objects.get(title="Plan")
        todo.todo.notes = "Some **notes**"
        todo.todo.save()
        for text in ["first", "second", "third", "fourth"]:
            ops.add_comment(todo, author=self.bob, content=text)
        page = self.page
        self.goto(page, todolist)
        notes_button = page.locator("[data-peek]").first
        peek = page.locator(f"#peek-{todo.pk}")
        self.assertEqual(peek.locator("> *").count(), 0)

        notes_button.click()
        peek.locator(".wb-peek-body").wait_for()
        self.assertIn("notes", peek.locator(".wb-markdown strong").inner_text())
        comments = peek.locator(".wb-peek-comment")
        self.assertEqual(
            [
                text.strip()
                for text in comments.locator(".wb-markdown").all_inner_texts()
            ],
            ["fourth", "third", "second"],
        )
        self.assertIn("The latest 3 of 4", peek.inner_text())
        self.assertEqual(notes_button.get_attribute("aria-expanded"), "true")

        # Not loaded again, closed
        notes_button.click()
        peek.locator(".wb-peek-body").wait_for(state="detached")
        self.assertEqual(notes_button.get_attribute("aria-expanded"), "false")
        # The comments' button opens it again
        page.locator("[data-peek]").nth(1).click()
        peek.locator(".wb-peek-body").wait_for()
        self.assertEqual(self.errors, [])


class TodoPageTest(E2ETestCase):
    def setUp(self):
        super().setUp()
        self.todolist = self.make_list(todos=["Plan"])
        self.todo = Item.objects.get(title="Plan")

    def test_mentions(self):
        """Typing "@" lists people, the arrow keys and Enter choose, the
        saved comment has the mention"""
        page = self.page
        self.goto(page, self.todo)
        textarea = page.locator("form:has([name=form][value=comment]) textarea")
        self.editor(textarea).click()
        self.editor(textarea).press_sequentially("Hello @Example")
        listbox = page.locator(".wb-mentions:not([hidden])")
        listbox.wait_for()
        names = listbox.locator("li span:not(.wb-avatar)").all_inner_texts()
        self.assertEqual(sorted(names), ["Ada Example", "Bob Example", "Cleo Example"])
        # With the organization (specs/organizations.md)
        self.assertIn(
            "Cleo Example, Example Client Ltd",
            listbox.locator("li.is-unavailable").inner_text(),
        )
        # The people who can't see the item can't be chosen
        self.assertEqual(
            listbox.locator("li.is-unavailable").inner_text().count("Cleo"), 1
        )
        self.assertEqual(
            listbox.locator("li.is-unavailable small").inner_text(),
            "can't see internal items",
        )
        # The first available one is active, ArrowDown moves on
        first = listbox.locator("li.active span:not(.wb-avatar)").inner_text()
        self.editor(textarea).press("ArrowDown")
        second = listbox.locator("li.active span:not(.wb-avatar)").inner_text()
        self.assertNotEqual(first, second)
        self.editor(textarea).press("ArrowUp")
        self.assertEqual(
            listbox.locator("li.active span:not(.wb-avatar)").inner_text(), first
        )
        # Escape closes without leaving
        self.editor(textarea).press("Escape")
        self.assertTrue(listbox.is_hidden())

        self.editor(textarea).press_sequentially(" and @Bo")
        listbox.wait_for()
        self.editor(textarea).press("Enter")
        self.assertEqual(
            textarea.input_value(),
            f"Hello @Example and [@Bob](person:{self.bob.pk}) ",
        )
        self.editor(textarea).press("Tab")  # blur
        self.set_markdown(textarea, f"Hello [@Bob Example](person:{self.bob.pk}) ")
        page.get_by_role("button", name="Add comment").click()
        page.locator(".wb-markdown", has_text="Hello").first.wait_for()
        self.assertEqual(
            Comment.objects.get(item=self.todo).content,
            f"Hello [@Bob Example](person:{self.bob.pk})",
        )
        self.assertEqual(self.errors, [])

    def test_the_mention_list_inserts_the_first_name(self):
        """Choosing a person inserts ``[@Bob](person:ID)``, the saved
        comment shows "@Bob" with the full name as title"""
        page = self.page
        self.goto(page, self.todo)
        textarea = page.locator("form:has([name=form][value=comment]) textarea")
        self.editor(textarea).click()
        self.editor(textarea).press_sequentially("Hi @Bob")
        listbox = page.locator(".wb-mentions:not([hidden])")
        listbox.wait_for()
        self.editor(textarea).press("Enter")
        self.assertEqual(textarea.input_value(), f"Hi [@Bob](person:{self.bob.pk}) ")
        page.get_by_role("button", name="Add comment").click()
        mention = page.locator(".wb-markdown .wb-mention")
        mention.wait_for()
        self.assertEqual(mention.inner_text(), "@Bob")
        self.assertEqual(mention.get_attribute("title"), "Bob Example")
        self.assertEqual(self.errors, [])

    def test_the_mention_list_tells_two_first_names_apart(self):
        """Two Bobs: the list inserts "Bob E." and "Bob Z.", the saved
        comment shows the one the viewer sees, the full name as title"""
        bob_z = User.objects.create_user(
            "bob.zed@example.org",
            full_name="Bob Zed",
            organization=Organization.objects.own(),
        )
        page = self.page
        self.goto(page, self.todo)
        textarea = page.locator("form:has([name=form][value=comment]) textarea")
        self.editor(textarea).click()
        self.editor(textarea).press_sequentially("Hi @Bob Z")
        listbox = page.locator(".wb-mentions:not([hidden])")
        listbox.wait_for()
        self.editor(textarea).press("Enter")
        self.assertEqual(textarea.input_value(), f"Hi [@Bob Z.](person:{bob_z.pk}) ")
        page.get_by_role("button", name="Add comment").click()
        mention = page.locator(".wb-markdown .wb-mention")
        mention.wait_for()
        self.assertEqual(mention.inner_text(), "@Bob Z.")
        self.assertEqual(mention.get_attribute("title"), "Bob Zed")
        self.assertEqual(self.errors, [])

    def test_mentions_of_a_client_are_members_only(self):
        self.make_list("Shared", visible=True, todos=["Review"])
        todo = Item.objects.get(title="Review")
        page = self.login(self.cleo)
        self.goto(page, todo)
        textarea = page.locator("form:has([name=form][value=comment]) textarea")
        self.editor(textarea).click()
        self.editor(textarea).press_sequentially("@Example")
        listbox = page.locator(".wb-mentions:not([hidden])")
        listbox.wait_for()
        # Ada is a member, Bob isn't: the client doesn't find him
        self.assertEqual(
            sorted(listbox.locator("li span:not(.wb-avatar)").all_inner_texts()),
            ["Ada Example", "Cleo Example"],
        )
        self.assertNotIn("@example.org", listbox.inner_text())
        self.set_markdown(textarea, "")
        self.editor(textarea).press_sequentially("@Bob")
        # (the answer is empty: nothing opens; wait for the request)
        page.wait_for_load_state("networkidle")
        self.assertTrue(listbox.is_hidden())

    def test_mentions_in_the_new_message_form(self):
        """Without an item yet, the list follows the visibility checkbox;
        a client only finds the project's members"""
        page = self.page
        page.goto(self.live_server_url + reverse("message_new", args=[self.project.pk]))
        content = page.locator("textarea[name=content]")
        self.editor(content).click()
        self.editor(content).press_sequentially("@Cleo")
        listbox = page.locator(".wb-mentions:not([hidden])")
        listbox.wait_for()
        self.assertEqual(
            listbox.locator("li.is-unavailable small").inner_text(),
            "can't see internal items",
        )
        self.editor(content).press("Escape")
        page.get_by_label("Visible to clients").check()
        self.set_markdown(content, "")
        self.editor(content).press_sequentially("@Cleo")
        listbox.wait_for()
        self.assertEqual(listbox.locator("li.is-unavailable").count(), 0)
        self.editor(content).press("Enter")
        self.assertEqual(content.input_value(), f"[@Cleo](person:{self.cleo.pk}) ")

        page = self.login(self.cleo)
        page.goto(self.live_server_url + reverse("message_new", args=[self.project.pk]))
        content = page.locator("textarea[name=content]")
        self.editor(content).click()
        self.editor(content).press_sequentially("@Example")
        listbox = page.locator(".wb-mentions:not([hidden])")
        listbox.wait_for()
        self.assertEqual(
            sorted(listbox.locator("li span:not(.wb-avatar)").all_inner_texts()),
            ["Ada Example", "Cleo Example"],
        )
        self.assertNotIn("@example.org", listbox.inner_text())
        self.assertEqual(self.errors, [])

    def test_the_reaction_picker_fills_its_rows(self):
        self.goto(self.page, self.todo)
        reactions = self.page.locator(".wb-reactions").first
        reactions.locator(".wb-reaction-add summary").click()
        self.assertEqual(
            emoji_rows(reactions.locator(".wb-reaction-quick")), [8, 8, 8, 8]
        )

    def test_reactions(self):
        """The picker adds a quick reaction or a few words, clicking one's
        own reaction removes it"""
        page = self.page
        self.goto(page, self.todo)
        reactions = page.locator(".wb-reactions").first
        reactions.locator(".wb-reaction-add summary").click()
        reactions.locator("button", has_text="🎉").click()
        mine = reactions.locator(".wb-reaction.is-mine")
        mine.wait_for()
        self.assertEqual(mine.get_attribute("aria-pressed"), "true")
        self.assertIn("🎉", mine.inner_text())
        self.assertEqual(Reaction.objects.get().content, "🎉")
        # The block replaced itself, it didn't land inside the form
        self.assertEqual(page.locator(".wb-reactions").count(), 1)

        # A few words, the field takes at most 40 characters
        reactions.locator(".wb-reaction-add summary").click()
        words = reactions.locator("input[type=text][name=content]")
        self.assertEqual(words.get_attribute("maxlength"), "40")
        words.fill("Looks good to me")
        reactions.get_by_role("button", name="React", exact=True).click()
        reactions.locator(".wb-reaction", has_text="Looks good").wait_for()
        self.assertEqual(
            sorted(Reaction.objects.values_list("content", flat=True)),
            ["Looks good to me", "🎉"],
        )

        # Clicking one's own asks first, the trash removes it
        own = reactions.locator(".wb-reaction-own", has_text="🎉")
        own.locator("a.wb-reaction").click()
        own.get_by_role("button", name="Remove your 🎉").click()
        reactions.locator("button.wb-reaction, a.wb-reaction", has_text="🎉").wait_for(
            state="detached"
        )
        self.assertEqual(
            list(Reaction.objects.values_list("content", flat=True)),
            ["Looks good to me"],
        )
        self.assertEqual(self.errors, [])

    def test_removing_ones_own_reaction_asks_first(self):
        Reaction.objects.create(user=self.ada, item=self.todo, content="👍")
        page = self.page
        self.goto(page, self.todo)
        own = page.locator(".wb-reaction-own").first
        trash = own.get_by_role("button", name="Remove your 👍")
        expect(trash).to_be_hidden()

        # Clicking shows the trash and keeps the reaction
        own.locator("a.wb-reaction").click()
        expect(trash).to_be_visible()
        self.assertEqual(Reaction.objects.count(), 1)

        # Escape cancels
        page.keyboard.press("Escape")
        expect(trash).to_be_hidden()
        # An outside click too
        own.locator("a.wb-reaction").click()
        expect(trash).to_be_visible()
        page.locator("h1").first.click()
        expect(trash).to_be_hidden()
        self.assertEqual(Reaction.objects.count(), 1)

        # The keyboard: Enter or Space show it, Tab reaches it
        own.locator("a.wb-reaction").focus()
        page.keyboard.press("Enter")
        expect(trash).to_be_visible()
        page.keyboard.press("Escape")
        page.keyboard.press("Space")
        expect(trash).to_be_visible()
        page.keyboard.press("Tab")
        expect(trash).to_be_focused()
        page.keyboard.press("Enter")
        expect(page.locator(".wb-reaction-own")).to_have_count(0)
        self.assertFalse(Reaction.objects.exists())

    def test_someone_elses_reaction_is_added_at_once(self):
        Reaction.objects.create(user=self.bob, item=self.todo, content="🎉")
        page = self.page
        self.goto(page, self.todo)
        page.locator("button.wb-reaction", has_text="🎉").click()
        page.locator(".wb-reaction-own", has_text="🎉").wait_for()
        self.assertEqual(Reaction.objects.filter(content="🎉").count(), 2)

    def test_a_new_reaction_pops_in_and_a_count_bumps(self):
        """Nothing animates on load; the classes of the animations come with
        the reactions htmx swaps in (specs/celebrations.md)"""
        Reaction.objects.create(user=self.bob, item=self.todo, content="🎉")
        page = self.login(self.ada)
        self.watch_classes(page)
        self.goto(page, self.todo)
        self.never_class(page, "is-new")
        self.never_class(page, "is-bumped")
        page.locator("button.wb-reaction", has_text="🎉").click()
        page.locator(".wb-reaction-own", has_text="🎉").wait_for()
        self.seen_class(page, "is-bumped")
        self.never_class(page, "is-new")
        reactions = page.locator(".wb-reactions").first
        reactions.locator(".wb-reaction-add summary").click()
        reactions.locator("button", has_text="👍").click()
        page.locator(".wb-reaction-own", has_text="👍").wait_for()
        self.seen_class(page, "is-new")
        # The classes are gone again when the animations ended
        expect(
            page.locator(".wb-reactions .is-new, .wb-reaction-count.is-bumped")
        ).to_have_count(0)
        self.assertEqual(self.errors, [])

    def test_reaction_on_a_comment(self):
        ops.add_comment(self.todo, author=self.bob, content="Hello")
        page = self.page
        self.goto(page, self.todo)
        reactions = page.locator("#live-comments .card .wb-reactions")
        reactions.locator(".wb-reaction-add summary").click()
        reactions.locator("button", has_text="👍").click()
        reactions.locator(".wb-reaction.is-mine").wait_for()
        self.assertEqual(Reaction.objects.get().comment.content, "Hello")

    def test_attaching_files(self):
        """Choosing, dropping and pasting a file uploads it and inserts its
        Markdown at the cursor; saving the text links it"""
        page = self.page
        self.goto(page, self.todo)
        form = page.locator("form:has([name=form][value=comment])")
        textarea = form.locator("textarea")
        self.set_markdown(textarea, "See")
        form.get_by_role("button", name="Attach files").click()
        # The hidden file input is the button's
        form.locator("input[type=file]").set_input_files({
            "name": "notes.txt",
            "mimeType": "text/plain",
            "buffer": b"hello",
        })
        textarea.evaluate("el => el.focus()")
        page.wait_for_function(
            "el => /\\]\\(/.test(el.value)", arg=textarea.element_handle()
        )
        self.assertRegex(textarea.input_value(), r"^See \[?!?\[?notes\.txt")
        self.assertNotIn("Uploading", textarea.input_value())
        self.assertEqual(Attachment.objects.count(), 1)

        # Dropping
        self.editor(textarea).evaluate(
            """el => {
                const data = new DataTransfer()
                data.items.add(new File(["dropped"], "dropped.txt", {type: "text/plain"}))
                el.dispatchEvent(new DragEvent("drop", {dataTransfer: data, bubbles: true, cancelable: true}))
            }"""
        )
        page.wait_for_function(
            "el => el.value.includes('dropped.txt') && !el.value.includes('Uploading')",
            arg=textarea.element_handle(),
        )
        # Pasting
        self.editor(textarea).evaluate(
            """el => {
                const data = new DataTransfer()
                data.items.add(new File(["pasted"], "pasted.txt", {type: "text/plain"}))
                el.dispatchEvent(new ClipboardEvent("paste", {clipboardData: data, bubbles: true, cancelable: true}))
            }"""
        )
        page.wait_for_function(
            "el => el.value.includes('pasted.txt') && !el.value.includes('Uploading')",
            arg=textarea.element_handle(),
        )
        self.assertEqual(Attachment.objects.count(), 3)

        form.get_by_role("button", name="Add comment").click()
        page.locator(".wb-markdown a", has_text="pasted.txt").wait_for()

        self.assertEqual(Attachment.objects.filter(item=self.todo).count(), 3)
        self.assertEqual(self.errors, [])

    def test_caret_after_the_uploaded_markdown(self):
        """Typing after an upload doesn't replace the inserted Markdown"""
        page = self.page
        self.goto(page, self.todo)
        form = page.locator("form:has([name=form][value=comment])")
        textarea = form.locator("textarea")
        self.set_markdown(textarea, "See")
        form.locator("input[type=file]").set_input_files({
            "name": "notes.txt",
            "mimeType": "text/plain",
            "buffer": b"hello",
        })
        page.wait_for_function(
            "el => /\\]\\(/.test(el.value)", arg=textarea.element_handle()
        )
        self.editor(textarea).press_sequentially(" done")
        self.assertRegex(textarea.input_value(), r"^See \[notes\.txt\]\(\S+\) done$")

    def test_too_large_file_is_refused_in_the_browser(self):
        page = self.page
        self.goto(page, self.todo)
        form = page.locator("form:has([name=form][value=comment])")
        form.evaluate("el => el.dataset.attachmentsMax = '3'")
        form.locator("input[type=file]").set_input_files({
            "name": "big.txt",
            "mimeType": "text/plain",
            "buffer": b"too large",
        })
        form.locator("[role=alert]").filter(has_text="at most").wait_for()
        self.assertEqual(Attachment.objects.count(), 0)


class CompletionTest(E2ETestCase):
    """Completing a to-do (specs/celebrations.md): classes the script sets
    for the animation, the row gone after it, nothing waiting on it with
    reduced motion"""

    def test_the_row_animates_and_is_gone_after_it(self):
        page = self.page
        self.make_list("Launch", todos=["Plan", "Pack"])
        self.goto(page, Item.objects.get(title="Launch"))
        row = page.locator(".wb-todo", has_text="Plan")
        row.get_by_role("button", name="Complete").click()
        expect(row).to_have_class(re.compile(r"\bis-completing\b"))
        expect(row.locator(".wb-check")).to_have_class(
            re.compile(r"\bis-done\b.*\bis-popping\b")
        )
        expect(row.locator(".wb-todo-title")).to_have_class(
            re.compile(r"\bis-striking\b")
        )
        # Not the last one: no burst
        expect(row.locator(".wb-check")).not_to_have_class(
            re.compile(r"\bis-bursting\b")
        )
        # Done on the server, gone from the list once the animation ended
        expect(page.locator("[data-todos] .wb-todo", has_text="Plan")).to_have_count(0)
        expect(page.locator("[data-todos] .wb-todo", has_text="Pack")).to_have_count(1)
        self.assertEqual(Item.objects.get(title="Plan").todo.is_completed, True)
        self.assertEqual(page.locator(".wb-all-done").count(), 0)
        self.assertEqual(self.errors, [])

    def test_the_last_open_to_do_bursts_and_the_list_says_so(self):
        page = self.page
        self.make_list("Launch", todos=["Plan"])
        self.goto(page, Item.objects.get(title="Launch"))
        row = page.locator(".wb-todo", has_text="Plan")
        row.get_by_role("button", name="Complete").click()
        expect(row.locator(".wb-check")).to_have_class(re.compile(r"\bis-bursting\b"))
        expect(page.locator(".wb-all-done")).to_have_text("All done.")
        # The page after the reload says it as well
        expect(page.locator("[data-todos] .wb-todo")).to_have_count(0)
        expect(page.locator(".wb-all-done")).to_have_text("All done.")
        self.assertEqual(page.locator(".wb-all-done.is-new").count(), 0)
        self.assertEqual(self.errors, [])

    def test_the_keyboard_completes_with_the_animation(self):
        page = self.page
        self.make_list("Launch", todos=["Plan", "Pack"])
        self.goto(page, Item.objects.get(title="Launch"))
        page.keyboard.press("j")
        page.keyboard.press("Shift+x")
        expect(page.locator(".wb-todo.is-completing")).to_have_count(1)
        expect(page.locator("[data-todos] .wb-todo")).to_have_count(1)
        self.assertEqual(Item.objects.get(title="Plan").todo.is_completed, True)

    def test_reopening_only_fades(self):
        page = self.page
        todolist = self.make_list("Launch", todos=["Plan"])
        ops.complete(Item.objects.get(title="Plan"), actor=self.ada)
        self.goto(page, todolist)
        page.get_by_text("Completed (1)").click()
        row = page.locator(".wb-completed .wb-todo", has_text="Plan")
        row.get_by_role("button", name="Reopen").click()
        expect(row).to_have_class(re.compile(r"\bis-reopening\b"))
        expect(row.locator(".wb-check")).not_to_have_class(
            re.compile(r"is-popping|is-bursting")
        )
        expect(page.locator("[data-todos] .wb-todo", has_text="Plan")).to_have_count(1)
        self.assertEqual(Item.objects.get(title="Plan").todo.is_completed, False)

    def test_the_to_do_page_fills_the_check(self):
        page = self.page
        self.make_list("Launch", todos=["Plan"])
        self.goto(page, Item.objects.get(title="Plan"))
        page.get_by_role("button", name="Complete").click()
        # The button's check fills and pops, the heading's new check pops,
        # the title is struck through
        expect(page.locator("form .wb-check.is-done.is-popping")).to_be_visible()
        expect(page.locator("h1 .bi.is-popping")).to_be_visible()
        expect(page.locator("h1 .wb-todo-title.is-striking")).to_be_visible()
        expect(page.get_by_text("Completed by")).to_be_visible()
        self.assertEqual(Item.objects.get(title="Plan").todo.is_completed, True)
        # The green button is the toggle: it reopens
        page.get_by_role("button", name=re.compile("^Reopen")).click()
        expect(page.get_by_role("button", name="Complete", exact=True)).to_be_visible()
        self.assertEqual(Item.objects.get(title="Plan").todo.is_completed, False)

    def test_with_reduced_motion_nothing_waits(self):
        page = self.login(self.ada, reduced_motion="reduce")
        self.make_list("Launch", todos=["Plan"])
        self.goto(page, Item.objects.get(title="Launch"))
        page.locator(".wb-todo", has_text="Plan").get_by_role(
            "button", name="Complete"
        ).click()
        # The animations alone take over a second, with the burst
        expect(page.locator(".wb-all-done")).to_have_text("All done.", timeout=700)
        self.assertEqual(Item.objects.get(title="Plan").todo.is_completed, True)


class RuleWidgetTest(E2ETestCase):
    def widget(self, page, index=0):
        add = page.locator("[data-add-todo]").nth(index)
        add.locator("summary").click()
        return add, add.locator("[data-rule-widget]")

    def visible_parts(self, widget):
        return {
            part
            for part in ["weekly", "monthly", "yearly"]
            if widget.locator(f"[data-rule-part={part}]").first.is_visible()
        }

    def test_the_parts_and_the_description_follow_the_frequency(self):
        todolist = self.make_list()
        page = self.page
        self.goto(page, todolist)
        _add, widget = self.widget(page)
        frequency = widget.locator("[data-rule-frequency]")
        description = widget.locator("[data-rule-description]")
        interval = widget.locator("[name=recurrence_interval]")
        # Doesn't repeat: nothing but the choice
        self.assertFalse(interval.is_visible())
        self.assertEqual(self.visible_parts(widget), set())

        frequency.select_option("daily")
        expect(description).to_have_text("every day")
        self.assertTrue(interval.is_visible())
        self.assertEqual(self.visible_parts(widget), set())
        interval.fill("3")
        expect(description).to_have_text("every 3 days")

        frequency.select_option("weekly")
        self.assertEqual(self.visible_parts(widget), {"weekly"})
        interval.fill("1")
        # The anchor's weekday is on: today's, so clicking a chip may turn it
        # off (on a Monday, "Mon" is on already); no weekday at all first
        expect(widget.locator(".wb-chip input:checked")).to_have_count(1)
        while widget.locator(".wb-chip input:checked").count():
            widget.locator(".wb-chip:has(input:checked)").first.click()
        # No weekday at all: the validation message
        expect(description).to_have_text("Choose at least one weekday.")
        widget.locator(".wb-chip", has_text="Mon").click()
        widget.locator(".wb-chip", has_text="Wed").click()
        expect(description).to_contain_text("Monday, Wednesday")
        while widget.locator(".wb-chip input:checked").count():
            widget.locator(".wb-chip:has(input:checked)").first.click()

        frequency.select_option("monthly")
        self.assertEqual(self.visible_parts(widget), {"monthly"})
        widget.locator("[value=nth]").check()
        widget.locator("[name=recurrence_ordinal]").select_option("2")
        widget.locator("[name=recurrence_weekday]").select_option("TU")
        expect(description).to_have_text("the second Tuesday of every month")
        widget.locator("[name=recurrence_weekday]").select_option("WD")
        widget.locator("[name=recurrence_ordinal]").select_option("-1")
        expect(description).to_have_text("the last working day of every month")
        widget.locator("[value=day]").check()
        widget.locator("[name=recurrence_month_day]").fill("31")
        expect(description).to_have_text("the 31st (or the last day) of every month")

        frequency.select_option("yearly")
        self.assertEqual(self.visible_parts(widget), {"yearly"})
        widget.locator("[name=recurrence_year_month]").select_option("3")
        widget.locator("[name=recurrence_year_day]").fill("5")
        expect(description).to_have_text("every year on March 5")
        widget.locator("[name=recurrence_year_month]").select_option("2")
        widget.locator("[name=recurrence_year_day]").fill("30")
        expect(description).to_have_text("This date doesn't exist.")

        frequency.select_option("")
        expect(description).to_have_text("")
        self.assertEqual(self.visible_parts(widget), set())
        self.assertEqual(self.errors, [])

    def test_the_forms_of_groups_are_separate(self):
        todolist = self.make_list(groups=["Soon"])
        page = self.page
        self.goto(page, todolist)
        _add, first = self.widget(page, 0)
        first.locator("[data-rule-frequency]").select_option("weekly")
        _add, second = self.widget(page, 1)
        expect(second.locator("[data-rule-frequency]")).to_have_value("")
        second.locator("[data-rule-frequency]").select_option("daily")
        expect(second.locator("[data-rule-description]")).to_have_text("every day")
        expect(first.locator("[data-rule-frequency]")).to_have_value("weekly")

    def test_a_second_tuesday_every_month(self):
        todolist = self.make_list()
        page = self.page
        self.goto(page, todolist)
        add, widget = self.widget(page)
        add.locator("[name=title]").fill("Team lunch")
        add.locator("[name=due_on]").fill("2026-12-08")
        widget.locator("[data-rule-frequency]").select_option("monthly")
        widget.locator("[value=nth]").check()
        widget.locator("[name=recurrence_ordinal]").select_option("2")
        widget.locator("[name=recurrence_weekday]").select_option("TU")
        expect(widget.locator("[data-rule-description]")).to_have_text(
            "the second Tuesday of every month"
        )
        add.locator("[name=title]").press("ControlOrMeta+Enter")
        page.locator("[data-todo]", has_text="Team lunch").wait_for()
        # The form is ready for the next one
        expect(widget.locator("[data-rule-frequency]")).to_have_value("")
        item = Item.objects.get(title="Team lunch")
        self.assertEqual(item.todo.recurrence, "FREQ=MONTHLY;BYDAY=TU;BYSETPOS=2")

        # Completing it creates the next one
        self.goto(page, item)
        page.locator("button", has_text="Complete").click()
        page.locator("text=Completed by").wait_for()
        following = Item.objects.get(title="Team lunch", todo__completed_at=None)
        self.assertEqual(str(following.todo.due_on), "2027-01-12")
        self.assertEqual(following.todo.recurrence, item.todo.recurrence)

    def test_the_todo_page_and_a_rule_set_elsewhere(self):
        elsewhere = ops.create_todo(
            todolist=self.make_list(todos=[]),
            title="Elsewhere",
            creator=self.ada,
            recurrence="FREQ=MONTHLY;BYMONTHDAY=1,15",
        )
        page = self.page
        self.goto(page, elsewhere)
        page.get_by_role("link", name="Edit").click()
        widget = page.locator("[data-rule-widget]")
        expect(widget).to_contain_text("can't be edited here")
        self.assertFalse(widget.locator("[data-rule-frequency]").is_visible())
        page.locator("form [name=title][maxlength='500']").fill("Renamed")
        page.locator("form button[type=submit]", has_text="Save").first.click()
        expect(page.locator("[data-rule-widget]")).to_have_count(0)
        elsewhere.todo.refresh_from_db()
        self.assertEqual(elsewhere.todo.recurrence, "FREQ=MONTHLY;BYMONTHDAY=1,15")
        # Replace opens the widget
        page.get_by_role("link", name="Edit").click()
        page.locator("[data-rule-replace]").check()
        frequency = widget.locator("[data-rule-frequency]")
        expect(frequency).to_be_visible()
        frequency.select_option("daily")
        expect(widget.locator("[data-rule-description]")).to_have_text("every day")
        page.locator("form button[type=submit]", has_text="Save").first.click()
        expect(page.locator("[data-rule-widget]")).to_have_count(0)
        elsewhere.todo.refresh_from_db()
        self.assertEqual(elsewhere.todo.recurrence, "FREQ=DAILY")

    def test_the_question_form(self):
        page = self.page
        page.goto(f"{self.live_server_url}/projects/{self.project.pk}/checkins/new/")
        widget = page.locator("[data-rule-widget]")
        frequency = widget.locator("[data-rule-frequency]")
        # Check-ins always repeat
        self.assertEqual(
            frequency.locator("option").all_inner_texts(),
            ["Daily", "Weekly", "Monthly", "Yearly"],
        )
        expect(frequency).to_have_value("weekly")
        expect(widget.locator("[data-rule-description]")).not_to_have_text("")
        frequency.select_option("monthly")
        expect(widget.locator("[data-rule-description]")).to_contain_text(
            "of every month"
        )
        self.assertEqual(self.errors, [])
