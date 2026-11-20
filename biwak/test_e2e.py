# Copyright (c) 2026, Feinheit AG and individual contributors (Governance's
# end-to-end setup, see NOTICE)
"""End-to-end tests of the JavaScript in ``frontend/`` (AGENTS.md, decided
2026-11-20: only what nothing but a browser can test)

They run the real server (``LiveServerTestCase``, serving ``static/`` with
the production bundle ``./runtests.sh`` builds) and Chromium through
Playwright, installed with ``uv run playwright install chromium``. Without
the browser or the bundle they're skipped; ``./runtests.sh --exclude-tag
e2e`` leaves them out.

Each test logs in through a session cookie and waits for what it expects
(Playwright's waiting, no sleeps).
"""

import os

from django.conf import settings
from django.db.models import F
from django.test import Client, LiveServerTestCase, tag
from django.urls import reverse

from biwak.accounts.models import CalendarToken
from biwak.bookmarks import operations as link_ops
from biwak.bookmarks.models import Link
from biwak.files.models import Attachment
from biwak.items import operations as ops
from biwak.items.models import Comment, Doc, Item, Kind
from biwak.reactions.models import Reaction
from biwak.test_utils import person, project


try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None


@tag("e2e")
class E2ETestCase(LiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        if sync_playwright is None:  # pragma: no cover
            raise cls.skipTest(cls, "Playwright isn't installed")
        if not (settings.STATIC_ROOT / "main.html").exists():  # pragma: no cover
            raise cls.skipTest(cls, "No bundle: yarn rspack build --mode production")
        # Playwright's sync API runs an event loop, the test's database
        # access happens outside of it
        os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
        super().setUpClass()
        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch()
        except Exception as exc:  # pragma: no cover
            cls.playwright.stop()
            super().tearDownClass()
            raise cls.skipTest(cls, f"No browser: {exc}") from exc

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        super().tearDownClass()
        os.environ.pop("DJANGO_ALLOW_ASYNC_UNSAFE", None)

    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")  # Staff, not a member
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.cleo])
        self.contexts = []
        self.errors = []
        self.page = self.login(self.ada)

    def tearDown(self):
        for context in self.contexts:
            context.close()

    def login(self, user, **kwargs):
        """A page of a new browser context, logged in as ``user``"""
        client = Client()
        client.force_login(user)
        context = self.browser.new_context(**kwargs)
        self.contexts.append(context)
        context.add_cookies([
            {
                "name": "sessionid",
                "value": client.cookies["sessionid"].value,
                "url": self.live_server_url,
            }
        ])
        page = context.new_page()
        page.on("pageerror", lambda error: self.errors.append(str(error)))
        page.on(
            "console",
            self.console,
        )
        return page

    def console(self, message):
        # The favicon lives in an app's static files, the test server
        # serves only the bundle in static/
        if message.type == "error" and not message.location["url"].endswith(
            "/favicon.svg"
        ):
            self.errors.append(f"{message.text} {message.location['url']}")

    def goto(self, page, target):
        url = target if isinstance(target, str) else target.get_absolute_url()
        page.goto(f"{self.live_server_url}{url}")
        # The scripts for dragging are chunks loaded after the page: wait
        # until every sortable container has its Sortable
        page.wait_for_function(
            """() => [...document.querySelectorAll(
                "[data-todos], [data-groups], [data-sortable-links], [data-sortable-lists]"
            )].every((el) => Object.keys(el).some((key) => key.startsWith("Sortable")))"""
        )

    def make_list(self, title="Launch", *, visible=False, groups=(), todos=()):
        """A list with its groups and to-dos (titles; a ``(title, group)``
        pair puts it into the group)"""
        todolist = ops.create_list(
            project=self.project, title=title, creator=self.ada, visible=visible
        )
        made = {
            name: ops.create_group(todolist=todolist.todolist, title=name)
            for name in groups
        }
        for entry in todos:
            name, group = (entry, None) if isinstance(entry, str) else entry
            ops.create_todo(
                todolist=todolist,
                title=name,
                creator=self.ada,
                group=made.get(group),
            )
        return todolist

    def order(self, todolist):
        """``[(title, group title or None)]`` as stored"""
        return [
            (todo.title, todo.todo.group.title if todo.todo.group else None)
            for todo in Item.objects
            .filter(parent=todolist, kind=Kind.TODO)
            .select_related("todo__group")
            .order_by(
                F("todo__group__position").asc(nulls_first=True), "position", "pk"
            )
        ]


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
        self.assertTrue(title.evaluate("el => el === document.activeElement"))

        title.fill("Write the brief")
        add.locator("[name=notes]").fill("Two pages, *short*")
        add.locator(".wb-chip", has_text="Ada").click()
        add.locator("[name=due_on]").fill("2026-12-24")
        title.press("Control+Enter")
        rows = page.locator("[data-todo]")
        rows.filter(has_text="Write the brief").wait_for()
        self.assertEqual(page.evaluate("window.marker"), 1)
        self.assertEqual(rows.first.locator(".wb-person").inner_text(), "Ada")
        self.assertIn("24. Dec", rows.first.inner_text())
        # Ready for the next one
        self.assertEqual(title.input_value(), "")
        self.assertEqual(add.locator("[name=notes]").input_value(), "")
        self.assertFalse(add.locator(".wb-chip input").first.is_checked())
        self.assertTrue(title.evaluate("el => el === document.activeElement"))

        title.fill("Send it")
        title.press("Control+Enter")
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

    def test_adding_to_a_group_and_one_form_open(self):
        todolist = self.make_list(groups=["Soon"])
        page = self.page
        self.goto(page, todolist)
        forms = page.locator("[data-add-todo]")
        forms.nth(1).locator("summary").click()
        forms.nth(1).locator("[name=title]").fill("In the group")
        forms.nth(1).locator("[name=title]").press("Control+Enter")
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
        notes.click()
        notes.press_sequentially("Ask @Bo")
        page.locator(".wb-mentions:not([hidden])").first.wait_for()
        notes.press("Enter")  # Picks, doesn't save or close
        self.assertEqual(
            notes.input_value(), f"Ask [@Bob Example](person:{self.bob.pk}) "
        )
        self.assertTrue(add.evaluate("el => el.open"))
        add.locator("[name=title]").fill("Ask")
        add.locator("[name=title]").press("Control+Enter")
        page.locator("[data-todo]", has_text="Ask").wait_for()
        self.assertEqual(
            Item.objects.get(title="Ask").todo.notes,
            f"Ask [@Bob Example](person:{self.bob.pk})",
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
        textarea.click()
        textarea.press_sequentially("Hello @Example")
        listbox = page.locator(".wb-mentions:not([hidden])")
        listbox.wait_for()
        names = listbox.locator("li span").all_inner_texts()
        self.assertEqual(sorted(names), ["Ada Example", "Bob Example", "Cleo Example"])
        # The people who can't see the item can't be chosen
        self.assertEqual(
            listbox.locator("li.is-unavailable").inner_text().count("Cleo"), 1
        )
        self.assertEqual(
            listbox.locator("li.is-unavailable small").inner_text(),
            "can't see internal items",
        )
        # The first available one is active, ArrowDown moves on
        first = listbox.locator("li.active span").inner_text()
        textarea.press("ArrowDown")
        second = listbox.locator("li.active span").inner_text()
        self.assertNotEqual(first, second)
        textarea.press("ArrowUp")
        self.assertEqual(listbox.locator("li.active span").inner_text(), first)
        # Escape closes without leaving
        textarea.press("Escape")
        self.assertTrue(listbox.is_hidden())

        textarea.press_sequentially(" and @Bo")
        listbox.wait_for()
        textarea.press("Enter")
        self.assertEqual(
            textarea.input_value(),
            f"Hello @Example and [@Bob Example](person:{self.bob.pk}) ",
        )
        textarea.press("Tab")  # blur
        textarea.fill(f"Hello [@Bob Example](person:{self.bob.pk}) ")
        page.get_by_role("button", name="Add comment").click()
        page.locator(".wb-markdown", has_text="Hello").first.wait_for()
        self.assertEqual(
            Comment.objects.get(item=self.todo).content,
            f"Hello [@Bob Example](person:{self.bob.pk})",
        )
        self.assertEqual(self.errors, [])

    def test_mentions_of_a_client_are_members_only(self):
        self.make_list("Shared", visible=True, todos=["Review"])
        todo = Item.objects.get(title="Review")
        page = self.login(self.cleo)
        self.goto(page, todo)
        textarea = page.locator("form:has([name=form][value=comment]) textarea")
        textarea.click()
        textarea.press_sequentially("@Example")
        listbox = page.locator(".wb-mentions:not([hidden])")
        listbox.wait_for()
        # Ada is a member, Bob isn't: the client doesn't find him
        self.assertEqual(
            sorted(listbox.locator("li span").all_inner_texts()),
            ["Ada Example", "Cleo Example"],
        )
        self.assertNotIn("@example.org", listbox.inner_text())
        textarea.fill("")
        textarea.press_sequentially("@Bob")
        # (the answer is empty: nothing opens; wait for the request)
        page.wait_for_load_state("networkidle")
        self.assertTrue(listbox.is_hidden())

    def test_reactions(self):
        """The picker adds a quick reaction or a few words, clicking one's
        own reaction removes it"""
        page = self.page
        self.goto(page, self.todo)
        reactions = page.locator(".wb-reactions").first
        reactions.locator(".wb-reaction-add summary").click()
        reactions.locator("button", has_text="🎉").click()
        mine = reactions.locator("button.wb-reaction.is-mine")
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
        reactions.locator("button.wb-reaction", has_text="Looks good").wait_for()
        self.assertEqual(
            sorted(Reaction.objects.values_list("content", flat=True)),
            ["Looks good to me", "🎉"],
        )

        # Clicking one's own removes it
        reactions.locator("button.wb-reaction", has_text="🎉").click()
        reactions.locator("button.wb-reaction", has_text="🎉").wait_for(
            state="detached"
        )
        self.assertEqual(
            list(Reaction.objects.values_list("content", flat=True)),
            ["Looks good to me"],
        )
        self.assertEqual(self.errors, [])

    def test_reaction_on_a_comment(self):
        ops.add_comment(self.todo, author=self.bob, content="Hello")
        page = self.page
        self.goto(page, self.todo)
        reactions = page.locator("#comments ~ .card .wb-reactions")
        reactions.locator(".wb-reaction-add summary").click()
        reactions.locator("button", has_text="👍").click()
        reactions.locator("button.wb-reaction.is-mine").wait_for()
        self.assertEqual(Reaction.objects.get().comment.content, "Hello")

    def test_attaching_files(self):
        """Choosing, dropping and pasting a file uploads it and inserts its
        Markdown at the cursor; saving the text links it"""
        page = self.page
        self.goto(page, self.todo)
        form = page.locator("form:has([name=form][value=comment])")
        textarea = form.locator("textarea")
        textarea.fill("See")
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
        textarea.evaluate(
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
        textarea.evaluate(
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
        textarea.fill("See")
        form.locator("input[type=file]").set_input_files({
            "name": "notes.txt",
            "mimeType": "text/plain",
            "buffer": b"hello",
        })
        page.wait_for_function(
            "el => /\\]\\(/.test(el.value)", arg=textarea.element_handle()
        )
        textarea.press_sequentially(" done")
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


class DocLockTest(E2ETestCase):
    def test_lock(self):
        doc = ops.create_doc(project=self.project, title="Notes", creator=self.ada)
        edit = reverse("doc_edit", args=[doc.pk])
        page = self.page
        self.goto(page, edit)
        page.locator("[data-doc-lock]").wait_for()
        self.assertEqual(Doc.objects.get(item=doc).locked_by, self.ada)

        # A second person is sent back to the doc, which is locked
        other = self.login(self.bob)
        self.goto(other, edit)
        other.wait_for_url(f"**{doc.get_absolute_url()}")
        self.assertIn(
            "Ada is editing this doc",
            other.locator(".alert", has_text="editing").first.inner_text(),
        )
        self.assertEqual(Doc.objects.get(item=doc).locked_by, self.ada)

        # Releasing frees it
        page.get_by_role("button", name="Cancel").click()
        page.wait_for_url(f"**{doc.get_absolute_url()}")
        self.assertIsNone(Doc.objects.get(item=doc).locked_by)
        self.goto(other, edit)
        other.locator("[data-doc-lock]").wait_for()
        self.assertEqual(Doc.objects.get(item=doc).locked_by, self.bob)

    def test_lock_is_renewed_every_minute(self):
        doc = ops.create_doc(project=self.project, title="Notes", creator=self.ada)
        page = self.page
        page.clock.install()
        self.goto(page, reverse("doc_edit", args=[doc.pk]))
        page.locator("[data-doc-lock]").wait_for()
        before = Doc.objects.get(item=doc).locked_at
        with page.expect_request("**/lock/"):
            page.clock.run_for(61_000)
        # The server answered
        page.wait_for_load_state("networkidle")
        self.assertGreater(Doc.objects.get(item=doc).locked_at, before)


class LinksTest(E2ETestCase):
    def test_adding_and_dragging_links(self):
        page = self.page
        self.goto(page, self.project)
        page.locator(".wb-links details summary").click()
        for url, title in [
            ("https://example.com/one", "One"),
            ("https://example.com/two", "Two"),
        ]:
            form = page.locator(".wb-links details form")
            form.locator("[name=url]").fill(url)
            form.locator("[name=title]").fill(title)
            form.get_by_role("button", name="Add").click()
            page.locator("[data-link-item]", has_text=title).wait_for()
            if title == "One":
                page.locator(".wb-links details summary").click()
        self.assertEqual(
            list(Link.objects.order_by("position").values_list("title", flat=True)),
            ["One", "Two"],
        )

        with page.expect_response("**/links/order/"):
            page.locator("[data-link-item]", has_text="Two").locator(
                "[data-link-handle]"
            ).drag_to(
                page.locator("[data-link-item]", has_text="One"),
                target_position={"x": 5, "y": 5},
            )
        self.assertEqual(
            list(Link.objects.order_by("position").values_list("title", flat=True)),
            ["Two", "One"],
        )
        self.assertEqual(self.errors, [])

    def test_links_on_an_item(self):
        todolist = self.make_list()
        for title in ["One", "Two"]:
            link_ops.add_link(
                project=self.project,
                item=todolist,
                url=f"https://example.com/{title}",
                title=title,
                created_by=self.ada,
            )
        page = self.page
        self.goto(page, todolist)
        with page.expect_response("**/links/order/"):
            page.locator("[data-link-item]", has_text="Two").locator(
                "[data-link-handle]"
            ).drag_to(
                page.locator("[data-link-item]", has_text="One"),
                target_position={"x": 5, "y": 5},
            )
        self.assertEqual(
            list(
                Link.objects
                .filter(item=todolist)
                .order_by("position")
                .values_list("title", flat=True)
            ),
            ["Two", "One"],
        )


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
        self.assertTrue(
            menu.locator("summary").evaluate("el => el === document.activeElement")
        )

    def test_theme(self):
        page = self.page
        self.goto(page, self.project)
        toggle = page.locator("[data-theme-toggle]")
        html = page.locator("html")
        self.assertEqual(toggle.get_attribute("title"), "Theme: Auto")
        toggle.click()
        self.assertEqual(html.get_attribute("data-bs-theme"), "light")
        self.assertEqual(toggle.get_attribute("title"), "Theme: Light")
        toggle.click()
        self.assertEqual(html.get_attribute("data-bs-theme"), "dark")
        self.assertEqual(page.evaluate("localStorage.getItem('theme')"), "dark")
        # Remembered on the next page, before it renders
        page.reload()
        self.assertEqual(html.get_attribute("data-bs-theme"), "dark")
        toggle.click()
        self.assertEqual(toggle.get_attribute("title"), "Theme: Auto")
        self.assertIsNone(page.evaluate("localStorage.getItem('theme')"))

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


class ClientTest(E2ETestCase):
    def test_client_sees_the_badge_and_banner_but_no_staff_controls(self):
        todolist = self.make_list("Shared", visible=True, groups=["Soon"], todos=["A"])
        link_ops.add_link(
            project=self.project,
            item=todolist,
            url="https://example.com/",
            title="Spec",
            created_by=self.ada,
            visible=True,
        )
        # Staff see the switch and the controls
        staff = self.page
        self.goto(staff, todolist)
        self.assertEqual(
            staff.get_by_role("button", name="Hide from clients").count(), 1
        )
        self.assertEqual(staff.locator("[data-link-handle]").count(), 1)
        self.assertEqual(staff.locator("[data-group-handle]").count(), 1)

        page = self.login(self.cleo)
        self.goto(page, todolist)
        self.assertEqual(page.locator("h1 .wb-client-badge").inner_text(), "Clients")
        self.assertIn(
            "Clients can see this.", page.locator(".wb-client-banner").inner_text()
        )
        self.assertEqual(
            page.get_by_role("button", name="Hide from clients").count(), 0
        )
        self.assertEqual(page.get_by_role("button", name="Show to clients").count(), 0)
        self.assertEqual(page.get_by_role("link", name="Edit").count(), 0)
        self.assertEqual(page.locator("[data-link-handle]").count(), 0)
        self.assertEqual(page.locator("[data-group-handle]").count(), 0)
        self.assertEqual(page.get_by_text("Add a link").count(), 0)
        self.assertEqual(page.get_by_role("button", name="Add group").count(), 0)
        self.assertEqual(page.locator("details.wb-menu .wb-group-menu").count(), 0)

        # Adding to-dos inline works and what the client creates is
        # visible to clients
        add = page.locator("[data-add-todo]").first
        add.locator("summary").click()
        add.locator("[name=title]").fill("From the client")
        add.locator("[name=title]").press("Control+Enter")
        page.locator("[data-todo]", has_text="From the client").wait_for()
        created = Item.objects.get(title="From the client")
        self.assertEqual(created.creator, self.cleo)
        self.assertTrue(created.is_client_visible)

        # Their to-do page too
        self.goto(page, created)
        self.assertEqual(page.locator("h1 .wb-client-badge").count(), 1)
        self.assertGreaterEqual(page.locator(".wb-client-banner").count(), 1)
        self.assertEqual(page.get_by_role("button", name="Show to clients").count(), 0)
        self.assertEqual(self.errors, [])
