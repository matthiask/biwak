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

import asyncio
import datetime as dt
import json
import os
import re
import socket
import time

from django.conf import settings
from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler
from django.db import DEFAULT_DB_ALIAS, connections
from django.db.models import F
from django.test import Client, LiveServerTestCase, tag
from django.test.testcases import LiveServerThread
from django.urls import reverse
from django.views.static import serve as static_serve

from biwak import schedules
from biwak.accounts.models import APIToken, CalendarToken, User
from biwak.activity.models import LevelOverride, Notification
from biwak.bookmarks import operations as link_ops
from biwak.bookmarks.models import Link
from biwak.files.models import Attachment
from biwak.items import operations as ops
from biwak.items.models import Comment, Doc, Item, Kind, Status, Todo
from biwak.projects import operations as project_ops
from biwak.reactions.models import Reaction
from biwak.test_utils import person, project


try:
    from playwright.sync_api import expect, sync_playwright
except ImportError:  # pragma: no cover
    expect = sync_playwright = None
try:
    import uvicorn
except ImportError:  # pragma: no cover
    uvicorn = None


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
        # While a test has taken the network away on purpose, the browser
        # logs the failed requests and reconnects
        self.offline = False
        self.page = self.login(self.ada)

    def tearDown(self):
        for context in self.contexts:
            context.close()
        self.wait_for_server_idle()

    def wait_for_server_idle(self, timeout=10):
        """Wait until the ASGI server has finished with the closed
        browsers: the editor's websocket saves the doc and tells the others
        when it disconnects, in a thread using the database, and the
        flush after the test would deadlock with it (or delete rows under
        its feet)"""
        server = getattr(self.server_thread, "server", None)
        state = getattr(server, "server_state", None)
        if state is None:  # Not uvicorn
            return
        deadline = time.monotonic() + timeout
        while state.connections or state.tasks:
            if time.monotonic() > deadline:  # pragma: no cover
                raise AssertionError("The live server still has open connections")
            time.sleep(0.02)

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
        # serves only the bundle in static/. Live updates need the ASGI
        # server (LiveTest), the others' pages try in vain. A refused tick
        # (409) is part of the pages' dealings, the browser logs it anyway.
        if (
            message.type == "error"
            and not message.location["url"].endswith("/favicon.svg")
            and not (self.offline and "ERR_INTERNET_DISCONNECTED" in message.text)
            and not (
                "/ws/live/" in message.text
                and self.server_thread_class is not ASGIServerThread
            )
            and "status of 409" not in message.text
        ):
            self.errors.append(f"{message.text} {message.location['url']}")

    def goto(self, page, target):
        url = target if isinstance(target, str) else target.get_absolute_url()
        page.goto(f"{self.live_server_url}{url}")
        self.wait_for_sortables(page)

    def wait_for_sortables(self, page):
        # The scripts for dragging are chunks loaded after the page: wait
        # until every sortable container has its Sortable
        page.wait_for_function(
            """() => [...document.querySelectorAll(
                "[data-todos], [data-groups], [data-sortable-order]"
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
        expect(title).to_be_focused()

        title.fill("Write the brief")
        add.locator("[name=notes]").fill("Two pages, *short*")
        picker = add.locator(".wb-picker-input")
        picker.click()
        add.locator(".wb-picker-list li", has_text="Ada").click()
        add.locator("[name=due_on]").fill("2026-12-24")
        title.press("Control+Enter")
        rows = page.locator("[data-todo]")
        rows.filter(has_text="Write the brief").wait_for()
        self.assertEqual(page.evaluate("window.marker"), 1)
        expect(rows.first.locator(".wb-person")).to_contain_text("Ada")
        expect(rows.first.locator(".wb-person .wb-avatar")).to_have_count(1)
        self.assertIn("24. Dec", rows.first.inner_text())
        # Ready for the next one
        self.assertEqual(title.input_value(), "")
        self.assertEqual(add.locator("[name=notes]").input_value(), "")
        expect(add.locator(".wb-pill")).to_have_count(0)
        expect(title).to_be_focused()

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

    def test_a_new_row_has_a_working_peek_button(self):
        """htmx processes the row the script inserted"""
        todolist = self.make_list()
        page = self.page
        self.goto(page, todolist)
        add = page.locator("[data-add-todo]").first
        add.locator("summary").click()
        add.locator("[name=title]").fill("Fresh")
        add.locator("[name=notes]").fill("Some **notes**")
        add.locator("[name=title]").press("Control+Enter")
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
        add.locator("[name=title]").press("Control+Enter")
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
        add.locator("[name=title]").press("Control+Enter")
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


def emoji_rows(picker):
    """The number of emojis in each row of the reaction picker"""
    return picker.evaluate(
        """el => {
          const rows = new Map()
          for (const b of el.querySelectorAll(".wb-emoji")) {
            const top = Math.round(b.getBoundingClientRect().top)
            rows.set(top, (rows.get(top) || 0) + 1)
          }
          return [...rows.values()]
        }"""
    )


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
        textarea.press("ArrowDown")
        second = listbox.locator("li.active span:not(.wb-avatar)").inner_text()
        self.assertNotEqual(first, second)
        textarea.press("ArrowUp")
        self.assertEqual(
            listbox.locator("li.active span:not(.wb-avatar)").inner_text(), first
        )
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
            sorted(listbox.locator("li span:not(.wb-avatar)").all_inner_texts()),
            ["Ada Example", "Cleo Example"],
        )
        self.assertNotIn("@example.org", listbox.inner_text())
        textarea.fill("")
        textarea.press_sequentially("@Bob")
        # (the answer is empty: nothing opens; wait for the request)
        page.wait_for_load_state("networkidle")
        self.assertTrue(listbox.is_hidden())

    def test_mentions_in_the_new_message_form(self):
        """Without an item yet, the list follows the visibility checkbox;
        a client only finds the project's members"""
        page = self.page
        page.goto(self.live_server_url + reverse("message_new", args=[self.project.pk]))
        content = page.locator("textarea[name=content]")
        content.click()
        content.press_sequentially("@Cleo")
        listbox = page.locator(".wb-mentions:not([hidden])")
        listbox.wait_for()
        self.assertEqual(
            listbox.locator("li.is-unavailable small").inner_text(),
            "can't see internal items",
        )
        content.press("Escape")
        page.get_by_label("Visible to clients").check()
        content.fill("")
        content.press_sequentially("@Cleo")
        listbox.wait_for()
        self.assertEqual(listbox.locator("li.is-unavailable").count(), 0)
        content.press("Enter")
        self.assertEqual(
            content.input_value(), f"[@Cleo Example](person:{self.cleo.pk}) "
        )

        page = self.login(self.cleo)
        page.goto(self.live_server_url + reverse("message_new", args=[self.project.pk]))
        content = page.locator("textarea[name=content]")
        content.click()
        content.press_sequentially("@Example")
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

    def test_the_picker_button_is_a_smiling_face(self):
        self.goto(self.page, self.todo)
        summary = self.page.locator(".wb-reaction-add summary").first
        self.assertEqual(summary.get_attribute("aria-label"), "Add a reaction")
        self.assertEqual(summary.locator("i.bi-emoji-smile").count(), 1)
        self.assertNotIn("+", summary.inner_text())

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


class OverdueTest(E2ETestCase):
    def test_the_badge_on_a_list(self):
        """Overdue gets the danger badge, today the quiet one, a completed
        to-do none (specs/ui-round-1.md, part 5)"""
        today = schedules.today()
        todolist = self.make_list(todos=["Late", "Now", "Done", "Soon"])
        for title, due_on in [
            ("Late", today - dt.timedelta(days=2)),
            ("Now", today),
            ("Done", today - dt.timedelta(days=2)),
            ("Soon", today + dt.timedelta(days=2)),
        ]:
            Todo.objects.filter(item__title=title).update(due_on=due_on)
        ops.complete(Item.objects.get(title="Done"), actor=self.ada)
        page = self.page
        self.goto(page, todolist)

        def badge(title):
            return page.locator("[data-todo]", has_text=title).locator("[data-due]")

        expect(badge("Late")).to_have_attribute("data-due", "overdue")
        expect(badge("Late")).to_contain_text("Overdue")
        expect(badge("Now")).to_have_text("Today")
        expect(badge("Soon")).to_have_attribute("data-due", "later")
        expect(page.locator("[data-todo]", has_text="Done")).to_have_count(1)
        expect(badge("Done").filter(has_text="Overdue")).to_have_count(0)
        expect(page.locator("[data-due=overdue]")).to_have_count(1)


class ProjectsPageTest(E2ETestCase):
    def test_archiving_with_undo_and_switching(self):
        self.camp = project("Camp", members=[self.ada])
        page = self.page
        self.goto(page, reverse("projects"))
        # No reload: a marker on the page survives
        page.evaluate("window.marker = 1")
        card = page.locator(".wb-project-card", has_text="Camp")
        card.get_by_role("button", name="Archive the project").click()
        expect(card).to_have_count(0)
        status = page.get_by_role("status")
        expect(status).to_contain_text("Archived.")
        self.camp.refresh_from_db()
        self.assertIsNotNone(self.camp.archived_at)
        status.get_by_role("button", name="Undo").click()
        expect(page.locator(".wb-project-card", has_text="Camp")).to_have_count(1)
        expect(page.get_by_role("status")).to_have_count(0)
        self.camp.refresh_from_db()
        self.assertIsNone(self.camp.archived_at)
        # Switching to the archived projects and bringing one back
        page.get_by_role("link", name="Archive", exact=True).click()
        expect(page.locator("h1")).to_have_text("Archived projects")
        self.assertIn("archived=1", page.url)
        self.assertEqual(page.evaluate("window.marker"), 1)
        project_ops.archive_project(self.camp, actor=self.ada)
        page.reload()
        page.get_by_role("button", name="Bring back from the archive").click()
        expect(page.get_by_role("status")).to_contain_text("Brought back.")
        page.get_by_role("link", name="Active projects").click()
        expect(page.locator(".wb-project-card", has_text="Camp")).to_have_count(1)


class ASGIServerThread(LiveServerThread):
    """The live server through asgi.py with uvicorn, for the websockets of
    docs edited live; static files from STATIC_ROOT like Django's"""

    def run(self):
        sock = socket.socket()
        # The requests and consumers run in threads of their own (asgiref's
        # thread sensitive contexts) which end without closing their
        # connections when they're kept open: the test database couldn't be
        # dropped afterwards. Connections are closed after each use instead.
        settings_dict = connections.settings[DEFAULT_DB_ALIAS]
        max_age = settings_dict["CONN_MAX_AGE"]
        settings_dict["CONN_MAX_AGE"] = 0
        try:
            sock.bind((self.host, self.port))
            self.port = sock.getsockname()[1]
            self.server = self.create_server()
            asyncio.run(self.server.serve(sockets=[sock]))
        except OSError as exc:  # pragma: no cover
            self.error = exc
        finally:
            settings_dict["CONN_MAX_AGE"] = max_age
            self.is_ready.set()
            connections.close_all()

    def create_server(self):
        from asgi import application

        ready = self.is_ready

        class Server(uvicorn.Server):
            async def startup(self, sockets=None):
                await super().startup(sockets=sockets)
                ready.set()

        return Server(
            uvicorn.Config(
                _ASGIStaticFilesHandler(application),
                lifespan="off",
                log_level="warning",
                ws="websockets-sansio",
            )
        )

    def terminate(self):
        if hasattr(self, "server"):
            self.server.should_exit = True
        self.join()


class _ASGIStaticFilesHandler(ASGIStaticFilesHandler):
    def get_base_url(self):
        return settings.STATIC_URL

    def serve(self, request):
        return static_serve(
            request, self.file_path(request.path), document_root=settings.STATIC_ROOT
        )


class CollabTest(E2ETestCase):
    """Docs edited live (specs/collaboration.md): several browsers typing
    at once, offline, watching, losing access, edits through the API"""

    host = "127.0.0.1"
    server_thread_class = ASGIServerThread

    @classmethod
    def setUpClass(cls):
        if uvicorn is None:  # pragma: no cover
            raise cls.skipTest(cls, "uvicorn isn't installed")
        super().setUpClass()

    def setUp(self):
        super().setUp()
        self.doc = ops.create_doc(
            project=self.project,
            title="Minutes",
            content="Agenda\n",
            creator=self.ada,
            visible=True,
        )

    def editor(self, user, doc=None, *, page=None):
        """The doc's editor page in a browser of the person, synced"""
        page = page or self.login(user)
        self.goto(page, reverse("doc_edit", args=[(doc or self.doc).pk]))
        live = page.locator("[data-collab]")
        expect(live).not_to_have_attribute("data-collab-state", "connecting")
        return page

    def content(self, page):
        return page.locator(".cm-content")

    def text(self, page):
        """The editor's text (without the others' cursors)"""
        return page.evaluate(
            "document.querySelector('[data-collab]').collab.view.state.doc.toString()"
        )

    def wait_for_text(self, page, expected):
        page.wait_for_function(
            """(expected) => document.querySelector('[data-collab]')
                .collab.view.state.doc.toString() === expected""",
            arg=expected,
        )

    def type(self, page, text, *, end=True):
        content = self.content(page)
        content.click()
        if end:
            page.keyboard.press("Control+End")
        page.keyboard.type(text)

    def stored(self, doc=None):
        return Doc.objects.get(pk=(doc or self.doc).pk).content

    def wait_for_stored(self, expected, doc=None):
        """Doc.content follows a few seconds after the last keystroke"""
        for _ in range(100):
            if self.stored(doc) == expected:
                return
            time.sleep(0.1)
        self.assertEqual(self.stored(doc), expected)

    def test_a_tick_in_another_browser_arrives_in_the_open_editor(self):
        """Ticks on docs never wait (specs/editor.md): one browser has the
        editor open and typed something not stored yet, another ticks the
        box on the doc's page; the tick appears in the editor, the typing
        stays"""
        doc = ops.create_doc(
            project=self.project,
            title="Packing",
            content="- [ ] tent\n- [ ] rope\n",
            creator=self.ada,
            visible=True,
        )
        editor = self.editor(self.ada, doc, page=self.page)
        ticking = self.login(self.bob)
        self.goto(ticking, doc)
        expect(ticking.locator("p[role=status]")).to_contain_text("Ada is editing this")
        self.type(editor, "- [ ] fuel")
        self.wait_for_text(editor, "- [ ] tent\n- [ ] rope\n- [ ] fuel")
        box = ticking.locator(".wb-checklist input[type=checkbox]").nth(1)
        box.check()
        expect(box).to_be_enabled()
        expect(box).to_be_checked()
        self.wait_for_text(editor, "- [ ] tent\n- [x] rope\n- [ ] fuel")
        self.wait_for_stored("- [ ] tent\n- [x] rope\n- [ ] fuel", doc)
        self.assertFalse(self.errors)

    def test_three_people_typing_at_once(self):
        """Ada, Bob and Cleo (a client, in a doc she created) type at the
        same time and see each other's text and cursors"""
        doc = ops.create_doc(
            project=self.project,
            title="Our notes",
            content="",
            creator=self.cleo,
            visible=True,
        )
        pages = [
            self.editor(user, doc, page=self.page if user == self.ada else None)
            for user in [self.ada, self.bob, self.cleo]
        ]
        for page in pages:
            self.content(page).click()
            page.keyboard.press("Control+End")
            page.keyboard.press("Enter")
        # Interleaved, a word each
        for words in zip(*[
            line.split() for line in ["Ada was here", "Bob too!", "Cleo as well"]
        ]):
            for page, word in zip(pages, words):
                page.keyboard.type(f"{word} ")
        for page in pages:
            for word in ["Ada", "was", "Bob", "too!", "Cleo", "as"]:
                expect(self.content(page)).to_contain_text(word)
        final = self.text(pages[0])
        for page in pages[1:]:
            self.wait_for_text(page, final)
        # The others' cursors with their names, and who is here
        expect(pages[0].locator(".cm-ySelectionInfo", has_text="Bob")).to_have_count(1)
        expect(pages[0].locator(".cm-ySelectionInfo", has_text="Cleo")).to_have_count(1)
        expect(pages[2].locator("[data-collab-people]")).to_contain_text("Ada")
        expect(pages[2].locator("[data-collab-people]")).to_contain_text("Bob")
        expect(pages[2].locator("[data-collab-people] .wb-avatar")).to_have_count(2)
        self.wait_for_stored(final, doc)
        self.assertFalse(self.errors)

    def test_offline_and_reconnect(self):
        ada = self.editor(self.ada, page=self.page)
        bob = self.editor(self.bob)
        live = ada.locator("[data-collab]")
        expect(live).to_have_attribute("data-collab-state", "connected")
        # The network goes, and with it the websocket (which the browser's
        # offline mode leaves open); reconnecting fails until it's back
        self.offline = True
        ada.context.set_offline(True)
        ada.evaluate(
            "document.querySelector('[data-collab]').collab.provider.ws.close()"
        )
        expect(live).to_have_attribute("data-collab-state", "offline")
        expect(ada.locator("[data-collab-status]")).to_contain_text("Offline")
        self.type(ada, "Typed offline")
        self.type(bob, "Typed online. ")
        expect(self.content(bob)).not_to_contain_text("Typed offline")
        ada.context.set_offline(False)
        expect(live).to_have_attribute("data-collab-state", "connected")
        self.offline = False
        for page in [ada, bob]:
            expect(self.content(page)).to_contain_text("Typed offline")
            expect(self.content(page)).to_contain_text("Typed online.")
        final = self.text(ada)
        self.wait_for_text(bob, final)
        self.wait_for_stored(final)
        self.assertFalse(self.errors)

    def test_a_client_watches_read_only(self):
        ada = self.editor(self.ada, page=self.page)
        cleo = self.editor(self.cleo)
        expect(cleo.locator("[data-collab]")).to_have_attribute(
            "data-collab-state", "watching"
        )
        expect(cleo.locator("[data-collab-status]")).to_contain_text("watching")
        expect(self.content(cleo)).to_have_attribute("contenteditable", "false")
        self.type(ada, "Decided: yes")
        expect(self.content(cleo)).to_contain_text("Decided: yes")
        expect(cleo.locator(".cm-ySelectionInfo", has_text="Ada")).to_have_count(1)
        # Typing does nothing
        self.content(cleo).click()
        cleo.keyboard.type("No!")
        self.wait_for_stored("Agenda\nDecided: yes")
        expect(self.content(ada)).not_to_contain_text("No!")
        # No form to rename it, no attaching
        self.assertEqual(cleo.get_by_role("button", name="Rename").count(), 0)
        self.assertFalse(self.errors)

    def test_losing_access_closes_the_session(self):
        cleo = self.editor(self.cleo)
        expect(self.content(cleo)).to_contain_text("Agenda")
        # Ada hides the doc on its page
        page = self.page
        self.goto(page, self.doc)
        page.get_by_role("button", name="Hide from clients").click()
        page.wait_for_load_state()
        live = cleo.locator("[data-collab]")
        expect(live).to_have_attribute("data-collab-state", "gone")
        expect(cleo.locator("[data-collab-status]")).to_have_text(
            "You can’t see this doc anymore."
        )
        expect(cleo.locator(".cm-content")).to_have_count(0)
        self.assertFalse(self.errors)

    def test_becoming_read_only_during_the_session(self):
        bob = self.editor(self.bob)
        expect(self.content(bob)).to_have_attribute("contenteditable", "true")
        page = self.page
        self.goto(page, self.doc)
        page.get_by_role("button", name="Make read-only").click()
        page.wait_for_load_state()
        expect(self.content(bob)).to_have_attribute("contenteditable", "false")
        expect(bob.locator("[data-collab-status]")).to_contain_text("watching")

    def test_an_api_edit_arrives_in_the_open_editor(self):
        ada = self.editor(self.ada, page=self.page)
        self.type(ada, "Typed live", end=True)
        self.wait_for_stored("Agenda\nTyped live")
        _token, secret = APIToken.create_for(user=self.bob, title="CLI", access="write")
        api = self.playwright.request.new_context(base_url=self.live_server_url)
        response = api.patch(
            f"/api/v1/docs/{self.doc.pk}/",
            data={"content": "Agenda for Monday\nTyped live"},
            headers={"Authorization": f"Bearer {secret}"},
        )
        self.assertEqual(response.status, 200, response.text())
        api.dispose()
        expect(self.content(ada)).to_contain_text("Agenda for Monday")
        expect(self.content(ada)).to_contain_text("Typed live")
        self.assertFalse(self.errors)


class LiveTest(E2ETestCase):
    """Live updates and the lantern (specs/lantern.md): two browsers, the
    other's changes appearing without reloading"""

    host = "127.0.0.1"
    server_thread_class = ASGIServerThread

    @classmethod
    def setUpClass(cls):
        if uvicorn is None:  # pragma: no cover
            raise cls.skipTest(cls, "uvicorn isn't installed")
        super().setUpClass()

    def setUp(self):
        super().setUp()
        self.todolist = self.make_list(
            "Shared", visible=True, groups=["Doing"], todos=["Order the tent"]
        )
        self.todo = Item.objects.get(title="Order the tent")
        self.frames = {}

    def open(self, user, target, *, page=None):
        """A page of the person, its websocket connected"""
        page = page or self.login(user)
        frames = self.frames.setdefault(page, [])

        def received(payload):
            # Playwright marks handlers: a function of our own, not a
            # builtin method
            frames.append(payload)

        page.on("websocket", lambda ws: ws.on("framereceived", received))
        self.goto(page, target)
        expect(page.locator("body")).to_have_attribute("data-live-state", "connected")
        return page

    def comment(self, page, text):
        form = page.locator("form:has(input[name=form][value=comment])")
        form.locator("textarea[name=content]").fill(text)
        form.get_by_role("button", name="Add comment").click()
        page.wait_for_load_state()

    def test_a_comment_a_reaction_and_a_completion_appear(self):
        ada = self.open(self.ada, self.todo, page=self.page)
        bob = self.open(self.bob, self.todo)
        self.comment(bob, "Ordered!")
        comment = ada.locator("#live-comments .card", has_text="Ordered!")
        expect(comment).to_have_count(1)
        expect(comment).to_have_class(re.compile("wb-live-new"))
        # A reaction, on the to-do
        reactions = bob.locator(".wb-reactions").first
        reactions.locator(".wb-reaction-add summary").click()
        reactions.locator("button", has_text="🎉").click()
        bob.locator(".wb-reaction.is-mine").first.wait_for()
        expect(ada.locator(".wb-reactions").first).to_contain_text("🎉")
        # Completed
        bob.get_by_role("button", name="Complete").click()
        bob.wait_for_load_state()
        expect(ada.locator("#live-header")).to_contain_text("Reopen")
        expect(ada.locator("#live-status")).to_contain_text("Completed by Bob")
        self.assertFalse(self.errors)

    def test_a_todo_added_and_moved_on_the_board(self):
        board = f"{self.todolist.get_absolute_url()}?view=board"
        ada = self.open(self.ada, board, page=self.page)
        bob = self.open(self.bob, board)
        section = bob.locator("section.wb-group[data-group-item]", has_text="Doing")
        section.locator(".wb-add-todo summary").click()
        title = section.locator("[data-add-todo-form] input[name=title]")
        title.fill("Pack the stove")
        title.press("Control+Enter")
        bob.locator("[data-todo]", has_text="Pack the stove").wait_for()
        doing = ada.locator("section.wb-group[data-group-item]", has_text="Doing")
        expect(doing.locator("[data-todo]", has_text="Pack the stove")).to_have_count(1)
        # Bob moves the tent into "Doing", on the to-do's page
        self.goto(bob, self.todo)
        bob.locator("details.wb-menu", has_text="More").first.locator("summary").click()
        bob.get_by_role("link", name="Move to…").click()
        modal = bob.locator("dialog#modal")
        modal.locator("select[name=target]").select_option(label="Shared / Doing")
        modal.get_by_label("To the top").check()
        with bob.expect_navigation():
            modal.get_by_role("button", name="Move", exact=True).click()
        expect(doing.locator("[data-todo]").first).to_contain_text("Order the tent")
        expect(ada.locator("#todos-none [data-todo]")).to_have_count(0)
        # Still draggable: the new rows are in a Sortable
        self.wait_for_sortables(ada)
        self.assertFalse(self.errors)

    def test_a_form_being_edited_isnt_replaced(self):
        ada = self.open(self.ada, self.todo, page=self.page)
        bob = self.open(self.bob, self.todo)
        # Ada has the form open (the marker only blocks ticks); Bob saves
        # the notes
        ada.get_by_role("link", name="Edit").click()
        title = ada.locator("#live-text input[name=title]")
        title.fill("Order the big tent")
        bob.locator("#live-text .wb-view-text").click()
        bob.locator("#live-text textarea[name=notes]").fill("Two poles")
        bob.get_by_role("button", name="Save").click()
        # The form waits, with a note
        expect(ada.locator("#live-text [data-live-note]")).to_be_visible()
        expect(title).to_have_value("Order the big tent")
        expect(ada.locator("#live-text textarea[name=notes]")).to_have_value("")
        # Cancelled: the view shows what changed
        ada.get_by_role("link", name="Cancel").click()
        expect(ada.locator("#live-text")).to_contain_text("Two poles")
        expect(ada.locator("#live-text form")).to_have_count(0)
        self.assertFalse(self.errors)

    def test_a_clients_page_doesnt_hear_of_an_internal_change(self):
        internal = self.make_list("Internal", todos=["Budget"])
        budget = Item.objects.get(title="Budget")
        cleo = self.open(self.cleo, self.todolist)
        ada = self.open(self.ada, budget, page=self.page)
        self.comment(ada, "Internal remark")
        self.goto(ada, internal)
        section = ada.locator("section.wb-group").first
        section.locator(".wb-add-todo summary").click()
        section.locator("input[name=title]").fill("Secret plan")
        section.locator("input[name=title]").press("Control+Enter")
        ada.locator("[data-todo]", has_text="Secret plan").wait_for()
        # Then something clients see: it arrives, the internal changes
        # didn't (not even as a "changed")
        self.goto(ada, self.todolist)
        section = ada.locator("section.wb-group").first
        section.locator(".wb-add-todo summary").click()
        section.locator("input[name=title]").fill("Buy pegs")
        section.locator("input[name=title]").press("Control+Enter")
        expect(cleo.locator("[data-todo]", has_text="Buy pegs")).to_have_count(1)
        received = [json.loads(frame) for frame in self.frames[cleo]]
        changed = {m["item"] for m in received if m["type"] == "changed"}
        self.assertNotIn(budget.pk, changed)
        self.assertNotIn(internal.pk, changed)
        self.assertFalse(
            set(changed)
            - set(
                Item.objects.filter(is_client_visible=True).values_list("pk", flat=True)
            )
        )
        expect(cleo.locator("body")).not_to_contain_text("Secret plan")
        expect(cleo.locator("body")).not_to_contain_text("Internal remark")
        self.assertFalse(self.errors)

    def test_reconnecting_after_being_offline(self):
        ada = self.open(self.ada, self.todo, page=self.page)
        bob = self.open(self.bob, self.todo)
        ada.context.set_offline(True)
        ada.evaluate("document.body.live.socket.close()")
        expect(ada.locator("body")).to_have_attribute("data-live-state", "offline")
        self.comment(bob, "While you were away")
        ada.context.set_offline(False)
        expect(ada.locator("body")).to_have_attribute(
            "data-live-state", "connected", timeout=15000
        )
        expect(ada.locator("#live-comments")).to_contain_text("While you were away")

    def test_the_lantern_count_and_menu(self):
        ada = self.open(self.ada, reverse("projects"), page=self.page)
        count = ada.locator("[data-lantern-count]")
        expect(count).to_be_hidden()
        bob = self.open(self.bob, self.todo)
        self.comment(bob, "Hi Ada")
        expect(count).to_have_text("1 unread")
        ada.locator("[data-lantern] > summary").click()
        menu = ada.locator("[data-lantern-menu]")
        expect(menu).to_contain_text("Order the tent")
        expect(menu).to_contain_text("Bob Example commented:")
        menu.get_by_role("button", name="Mark as read").click()
        expect(count).to_be_hidden()
        expect(menu.get_by_role("button", name="Mark as unread")).to_have_count(1)
        menu.get_by_role("button", name="Bookmark", exact=True).click()
        expect(menu).to_contain_text("Bookmarked")
        self.assertTrue(self.ada.bookmarks.filter(item=self.todo).exists())
        self.assertFalse(self.errors)

    def test_a_lantern_entry_is_a_link_which_reads(self):
        """Its address shows on hovering; a middle click opens a new tab and
        reads the item's notifications all the same"""
        ada = self.open(self.ada, reverse("projects"), page=self.page)
        bob = self.open(self.bob, self.todo)
        self.comment(bob, "In a new tab")
        expect(ada.locator("[data-lantern-count]")).to_have_text("1 unread")
        ada.locator("[data-lantern] > summary").click()
        entry = ada.locator("[data-lantern-menu] a", has_text="In a new tab")
        self.assertIn(self.todo.get_absolute_url(), entry.get_attribute("href"))
        with ada.context.expect_page():
            entry.click(button="middle")
        expect(ada.locator("[data-lantern-count]")).to_be_hidden()
        self.assertFalse(
            Notification.objects.filter(user=self.ada, read_at=None).exists()
        )

    def test_the_favicon_dot(self):
        icon = "document.querySelector('link[rel=icon]').href"
        User.objects.filter(pk=self.ada.pk).update(lantern_in_favicon=False)
        bob = self.open(self.bob, self.todo)
        ada = self.open(self.ada, reverse("projects"), page=self.page)
        self.comment(bob, "Without the setting")
        expect(ada.locator("[data-lantern-count]")).to_have_text("1 unread")
        self.assertTrue(ada.evaluate(icon).endswith("/favicon.svg"))
        # On by default
        User.objects.filter(pk=self.ada.pk).update(lantern_in_favicon=True)
        ada.reload()
        ada.wait_for_function(f"{icon}.startsWith('data:image/png')")
        # Opening the item reads nothing, following the lantern's entry does
        self.goto(ada, self.todo)
        ada.wait_for_function(f"{icon}.startsWith('data:image/png')")
        ada.locator("[data-lantern] > summary").click()
        ada.locator("[data-lantern-menu]").get_by_text("Without the setting").click()
        ada.wait_for_url(f"**{self.todo.get_absolute_url()}#comment-*")
        ada.wait_for_function(f"{icon}.endsWith('/favicon.svg')")


class LinksTest(E2ETestCase):
    def test_dragging_the_lists_of_a_project(self):
        self.make_list("First")
        self.make_list("Second")
        page = self.page
        self.goto(page, self.project)
        with page.expect_response("**/lists/order/"):
            page.locator("[data-sortable-item]", has_text="Second").locator(
                "[data-sortable-handle]"
            ).drag_to(
                page.locator("[data-sortable-item]", has_text="First"),
                target_position={"x": 40, "y": 3},
            )
        self.assertEqual(
            list(
                Item.objects
                .filter(project=self.project, kind=Kind.LIST)
                .order_by("position", "pk")
                .values_list("title", flat=True)
            ),
            ["Second", "First"],
        )
        self.assertEqual(self.errors, [])

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
            page.locator("[data-sortable-item]", has_text=title).wait_for()
            self.wait_for_sortables(page)
            if title == "One":
                page.locator(".wb-links details summary").click()
        self.assertEqual(
            list(Link.objects.order_by("position").values_list("title", flat=True)),
            ["One", "Two"],
        )

        with page.expect_response("**/links/order/"):
            page.locator("[data-sortable-item]", has_text="Two").locator(
                "[data-sortable-handle]"
            ).drag_to(
                page.locator("[data-sortable-item]", has_text="One"),
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
            page.locator("[data-sortable-item]", has_text="Two").locator(
                "[data-sortable-handle]"
            ).drag_to(
                page.locator("[data-sortable-item]", has_text="One"),
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
        expect(menu.locator("summary")).to_be_focused()

    def test_disclosures_close_like_menus(self):
        """The reaction picker and the form for a link close with a click
        elsewhere and with Escape"""
        todo = self.make_list(todos=["Plan"])
        todo = Item.objects.get(title="Plan")
        page = self.page
        self.goto(page, todo)
        picker = page.locator("details.wb-reaction-add").first
        picker.locator("summary").click()
        self.assertTrue(picker.evaluate("el => el.open"))
        # Empty space: the to-do's heading opens the form (view mode)
        page.mouse.click(2, page.viewport_size["height"] - 2)
        self.assertFalse(picker.evaluate("el => el.open"))
        picker.locator("summary").click()
        picker.locator("input[type=text]").focus()
        picker.locator("input[type=text]").press("Escape")
        self.assertFalse(picker.evaluate("el => el.open"))
        expect(picker.locator("summary")).to_be_focused()

        self.goto(page, self.project)
        link = page.locator(".wb-links details").first
        link.locator("summary").click()
        self.assertTrue(link.evaluate("el => el.open"))
        link.locator("[name=url]").press("Escape")
        self.assertFalse(link.evaluate("el => el.open"))
        link.locator("summary").click()
        page.locator("h1").first.click()
        self.assertFalse(link.evaluate("el => el.open"))

    def test_theme(self):
        page = self.page
        self.goto(page, self.project)
        toggle = page.locator("[data-theme-toggle]")
        html = page.locator("html")
        self.assertEqual(toggle.get_attribute("title"), "Theme: Auto")
        shown = toggle.locator("[data-theme-icon]:not([hidden])")
        self.assertEqual(shown.get_attribute("data-theme-icon"), "auto")
        toggle.click()
        self.assertEqual(html.get_attribute("data-bs-theme"), "light")
        self.assertEqual(toggle.get_attribute("title"), "Theme: Light")
        self.assertEqual(shown.get_attribute("data-theme-icon"), "light")
        toggle.click()
        self.assertEqual(html.get_attribute("data-bs-theme"), "dark")
        # Saved for the person, not the browser (it follows them)
        self.wait_for_theme("dark")
        self.assertIsNone(page.evaluate("localStorage.getItem('theme')"))
        # Remembered on the next page, before it renders
        page.reload()
        self.assertEqual(html.get_attribute("data-bs-theme"), "dark")
        toggle.click()
        self.assertEqual(toggle.get_attribute("title"), "Theme: Auto")
        self.wait_for_theme("auto")

    def wait_for_theme(self, theme):
        self.page.wait_for_function(
            "theme => fetch('/api/v1/me/').then(r => r.json()).then(m => m.theme === theme)",
            arg=theme,
        )

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
        self.assertEqual(
            staff.locator("[data-sortable-field=links] [data-sortable-handle]").count(),
            1,
        )
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
        self.assertEqual(
            page.locator("[data-sortable-field=links] [data-sortable-handle]").count(),
            0,
        )
        self.assertEqual(page.locator("[data-group-handle]").count(), 0)
        self.assertEqual(page.get_by_text("Add a link").count(), 0)
        self.assertEqual(page.get_by_role("link", name="New group").count(), 0)
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
        # The anchor's weekday is on: today
        widget.locator(".wb-chip", has_text="Mon").click()
        widget.locator(".wb-chip", has_text="Wed").click()
        expect(description).to_contain_text("Monday, Wednesday")
        # No weekday at all: the validation message
        while widget.locator(".wb-chip input:checked").count():
            widget.locator(".wb-chip:has(input:checked)").first.click()
        expect(description).to_have_text("Choose at least one weekday.")

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
        add.locator("[name=title]").press("Control+Enter")
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


class NoScriptTest(E2ETestCase):
    def test_drag_handles_are_hidden_without_javascript(self):
        todolist = self.make_list(groups=["Soon"], todos=["A"])
        page = self.login(self.ada, java_script_enabled=False)
        page.goto(f"{self.live_server_url}{todolist.get_absolute_url()}")
        self.assertEqual(page.locator("[data-todo]").count(), 1)
        for handle in page.locator(".wb-handle").all():
            self.assertFalse(handle.is_visible())
        self.assertGreater(page.locator(".wb-handle").count(), 1)


class HtmxTest(E2ETestCase):
    def test_a_request_of_any_element_carries_the_csrf_token(self):
        """Not only forms: htmx 4 inherits headers only when told to"""
        page = self.page
        self.goto(page, self.project)
        page.evaluate("""() => {
            document.body.insertAdjacentHTML(
              "beforeend", '<button id="x" hx-post="/nowhere/">x</button>')
            htmx.process(document.getElementById("x"))
        }""")
        with page.expect_request("**/nowhere/") as request:
            page.locator("#x").click()
        self.assertTrue(request.value.headers.get("x-csrftoken"))


class ModalTest(E2ETestCase):
    """The "More" menu's forms in the dialog (frontend/modal.js)"""

    def setUp(self):
        super().setUp()
        self.todolist = self.make_list("Launch", visible=True, todos=["Plan"])
        self.make_list("Other")

    def open_more(self, page, entry):
        page.locator("details.wb-menu", has_text="More").first.locator(
            "summary"
        ).click()
        page.get_by_role("link", name=entry).click()
        dialog = page.locator("dialog#modal")
        expect(dialog).to_be_visible()
        return dialog

    def test_notifications_open_save_and_focus_returns(self):
        page = self.page
        self.goto(page, self.todolist)
        dialog = self.open_more(page, "Notifications…")
        expect(dialog.locator("h1")).to_have_text("Notifications for this list")
        # No navigation: the page is still the list's
        self.assertEqual(
            page.url, f"{self.live_server_url}{self.todolist.get_absolute_url()}"
        )
        dialog.get_by_label("Nothing").check()
        dialog.get_by_role("button", name="Save").click()
        expect(page.locator("dialog#modal[open]")).to_have_count(0)
        self.assertEqual(
            LevelOverride.objects.get(user=self.ada, item=self.todolist).level,
            "nothing",
        )

    def test_escape_closes_an_unchanged_form_and_returns_the_focus(self):
        page = self.page
        self.goto(page, self.todolist)
        dialog = self.open_more(page, "Notifications…")
        page.keyboard.press("Escape")
        expect(dialog).not_to_be_visible()
        expect(
            page.locator("details.wb-menu", has_text="More").first.locator("summary")
        ).to_be_focused()

    def test_a_changed_form_needs_escape_twice(self):
        page = self.page
        self.goto(page, self.todolist)
        dialog = self.open_more(page, "Notifications…")
        dialog.get_by_label("Nothing").check()
        page.keyboard.press("Escape")
        expect(dialog).to_be_visible()
        page.keyboard.press("Escape")
        expect(dialog).not_to_be_visible()

    def test_cancel_closes(self):
        page = self.page
        self.goto(page, self.todolist)
        dialog = self.open_more(page, "Notifications…")
        dialog.get_by_role("button", name="Cancel").click()
        expect(dialog).not_to_be_visible()

    def test_the_client_banner_shows_on_visible_items(self):
        page = self.page
        self.goto(page, self.todolist)
        dialog = self.open_more(page, "Notifications…")
        expect(dialog.locator(".wb-client-banner")).to_be_visible()

    def test_trashing_asks_first(self):
        page = self.page
        self.goto(page, self.todolist)
        dialog = self.open_more(page, "Trash")
        expect(dialog.locator("h1")).to_have_text("Move to the trash?")
        dialog.get_by_role("button", name="Cancel").click()
        self.todolist.refresh_from_db()
        self.assertEqual(self.todolist.status, Status.ACTIVE)
        dialog = self.open_more(page, "Trash")
        dialog.get_by_role("button", name="Move to the trash").click()
        page.wait_for_url(f"**{self.project.get_absolute_url()}")
        self.todolist.refresh_from_db()
        self.assertEqual(self.todolist.status, Status.TRASHED)

    def test_moving_a_todo(self):
        todo = Item.objects.get(title="Plan")
        other = Item.objects.get(title="Other")
        page = self.page
        self.goto(page, todo)
        dialog = self.open_more(page, "Move to…")
        dialog.locator("select").first.select_option(label="Other")
        # The redirect loads the page again
        with page.expect_navigation():
            dialog.get_by_role("button", name="Move", exact=True).click()
        todo.refresh_from_db()
        self.assertEqual(todo.parent_id, other.pk)

    def test_a_modifier_key_leaves_the_link_alone(self):
        page = self.page
        self.goto(page, self.todolist)
        page.locator("details.wb-menu", has_text="More").first.locator(
            "summary"
        ).click()
        self.assertFalse(self.modifier_click_is_prevented(page, "a[data-modal]"))
        expect(page.locator("dialog#modal[open]")).to_have_count(0)

    def modifier_click_is_prevented(self, page, selector):
        """Whether the page's scripts took a Ctrl+click on ``selector``
        (the browser would follow the link into a new tab otherwise)"""
        return page.evaluate(
            """(selector) => {
                let prevented = null
                window.addEventListener("click", (event) => {
                    prevented = event.defaultPrevented
                    event.preventDefault()
                }, { once: true })
                document.querySelector(selector).dispatchEvent(
                    new MouseEvent("click", {
                        bubbles: true, cancelable: true, ctrlKey: true, button: 0,
                    })
                )
                return prevented
            }""",
            selector,
        )

    def test_new_list_from_the_palette_and_members(self):
        page = self.page
        self.goto(page, self.project)
        page.keyboard.press("Control+k")
        page.get_by_role("combobox").fill("New list")
        page.keyboard.press("Enter")
        dialog = page.locator("dialog#modal")
        expect(dialog.locator("h1")).to_have_text("New list")
        # Errors stay in the dialog (blanks pass the browser's check)
        dialog.get_by_label("title").fill("   ")
        dialog.get_by_role("button", name="Add list").click()
        expect(dialog.locator(".invalid-feedback")).to_be_visible()
        expect(dialog.locator("h1")).to_have_text("New list")
        dialog.get_by_label("title").fill("Fresh")
        dialog.get_by_role("button", name="Add list").click()
        page.wait_for_url("**/lists/**")
        self.assertTrue(Item.objects.filter(title="Fresh").exists())

        self.goto(page, reverse("project_people", args=[self.project.pk]))
        page.get_by_role("link", name="Invite by email").click()
        dialog = page.locator("dialog#modal")
        expect(dialog.locator("h1")).to_have_text("Invite by email")
        dialog.get_by_label("Email").fill("dora@example.org")
        dialog.get_by_role("button", name="Invite").click()
        expect(page.get_by_text("dora@example.org")).to_be_visible()


class NavSearchTest(E2ETestCase):
    def check(self, page, *, hint_visible):
        self.goto(page, self.project)
        button = page.locator("[data-palette-open]")
        expect(button).to_be_visible()
        expect(button).to_have_accessible_name(re.compile(r"^Search or jump to…"))
        self.assertEqual(page.locator(".wb-nav-search-hint").is_visible(), hint_visible)
        button.click()
        expect(page.locator("dialog.wb-dialog[open]")).to_be_visible()
        page.keyboard.press("Escape")
        expect(button).to_be_focused()

    def test_desktop_shows_the_magnifier_with_the_hint(self):
        page = self.page
        self.check(page, hint_visible=True)
        expect(page.locator(".wb-nav-search-hint")).to_have_text("Ctrl+K")

    def test_phone_shows_the_magnifier(self):
        page = self.login(self.ada, viewport={"width": 360, "height": 740})
        self.check(page, hint_visible=False)
        self.assertEqual(
            page.evaluate("document.documentElement.scrollWidth - window.innerWidth"),
            0,
        )

    def test_a_modifier_click_is_the_link_to_the_search_page(self):
        page = self.page
        self.goto(page, self.project)
        self.assertEqual(
            page.locator("[data-palette-open]").get_attribute("href"), "/search/"
        )
        self.assertFalse(
            ModalTest.modifier_click_is_prevented(self, page, "[data-palette-open]")
        )
        expect(page.locator("dialog.wb-dialog[open]")).to_have_count(0)


class PhoneTest(E2ETestCase):
    """What runs off the edge of a phone's screen"""

    def setUp(self):
        super().setUp()
        self.page = self.login(self.ada, viewport={"width": 360, "height": 740})
        self.todolist = self.make_list(todos=["Plan"])
        self.todo = Item.objects.get(title="Plan")

    def assertFits(self, path):
        self.page.goto(f"{self.live_server_url}{path}")
        self.assertEqual(
            self.page.evaluate(
                "document.documentElement.scrollWidth - window.innerWidth"
            ),
            0,
            path,
        )

    def test_pages_fit_the_screen(self):
        from biwak.accounts.models import APIToken

        APIToken.create_for(
            user=self.ada, title="A token for the build", access=APIToken.Access.READ
        )
        self.assertFits(reverse("api_tokens"))

        # A diff with a line without spaces
        doc = ops.create_doc(
            project=self.project,
            title="Notes",
            creator=self.ada,
            content="x" * 200,
        )
        from biwak.files import operations as file_ops

        file_ops.update_doc(
            doc, actor=self.ada, content="y" * 200 + " a", new_version=True
        )
        self.assertFits(reverse("item_history", args=[doc.pk]))
        self.assertFits(
            reverse(
                "doc_version", args=[doc.pk, doc.doc.versions.order_by("pk").last().pk]
            )
        )

        # A project with a long name
        project("A" * 80, members=[self.ada])
        self.assertFits(reverse("projects"))

    def test_the_reaction_picker_stays_on_the_screen(self):
        from biwak.reactions import operations as reaction_ops

        # Enough reactions to push the button to the right
        for word in ["Looks good", "On it", "Thanks a lot", "Agreed"]:
            reaction_ops.add_reaction(self.ada, word, item=self.todo)
        self.goto(self.page, self.todo)
        reactions = self.page.locator(".wb-reactions").first
        reactions.locator(".wb-reaction-add summary").click()
        box = reactions.locator(".wb-reaction-picker").bounding_box()
        self.assertGreaterEqual(box["x"], 0)
        self.assertLessEqual(box["x"] + box["width"], 360)
        self.assertEqual(
            emoji_rows(reactions.locator(".wb-reaction-quick")), [8, 8, 8, 8]
        )


class MenuPlacementTest(E2ETestCase):
    """Menus stay on the screen however far from its edge the button is"""

    def settle(self, page):
        # The toggle event comes after the click
        page.evaluate(
            "new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))"
        )

    def assertMenuFits(self, page, menu):
        menu.locator("summary").click()
        popup = menu.locator(".dropdown-menu")
        expect(popup).to_be_visible()
        self.settle(page)
        box = popup.bounding_box()
        width = page.evaluate("document.documentElement.clientWidth")
        self.assertGreaterEqual(box["x"], 0, box)
        self.assertLessEqual(box["x"] + box["width"], width, box)

    def check(self, width):
        self.page = self.login(self.ada, viewport={"width": width, "height": 740})
        self.make_list(groups=["Phase one"], todos=[("Plan", "Phase one")])
        self.goto(self.page, self.project)
        menus = self.page.locator("details.wb-menu")
        if width == 360:
            # The button wrapped onto a line of its own, at the left
            more = menus.filter(has_text="More").locator("summary")
            self.assertLess(more.bounding_box()["x"], 40)
        self.assertMenuFits(self.page, menus.filter(has_text="More"))
        self.assertMenuFits(self.page, menus.filter(has_text="Ada"))
        self.goto(self.page, Item.objects.get(title="Launch"))
        self.assertMenuFits(
            self.page, self.page.locator("details.wb-menu:has(.wb-group-menu)")
        )

    def test_menus_fit_on_a_phone(self):
        self.check(360)

    def test_menus_fit_on_a_narrow_phone(self):
        self.check(280)

    def test_menus_fit_on_a_desktop(self):
        self.check(1280)

    def test_menu_follows_a_resize(self):
        self.page = self.login(self.ada, viewport={"width": 1280, "height": 740})
        self.goto(self.page, self.project)
        menu = self.page.locator("details.wb-menu").filter(has_text="More")
        self.assertMenuFits(self.page, menu)
        self.page.set_viewport_size({"width": 360, "height": 740})
        self.page.wait_for_function(
            """() => document.querySelector(
                "details.wb-menu[open] > .dropdown-menu"
            ).getBoundingClientRect().left >= 0"""
        )

    def test_menu_by_keyboard(self):
        self.page = self.login(self.ada, viewport={"width": 360, "height": 740})
        self.goto(self.page, self.project)
        menu = self.page.locator("details.wb-menu").filter(has_text="More")
        menu.locator("summary").focus()
        self.page.keyboard.press("Enter")
        popup = menu.locator(".dropdown-menu")
        expect(popup).to_be_visible()
        self.settle(self.page)
        self.assertGreaterEqual(popup.bounding_box()["x"], 0)


class KeyboardTest(E2ETestCase):
    """The command palette and the shortcuts (specs/keyboard.md)"""

    def open_palette(self, page, key="Control+k"):
        page.keyboard.press(key)
        expect(page.locator("#wb-palette")).to_be_visible()
        expect(page.locator("#wb-palette-input")).to_be_focused()

    def options(self, page):
        return page.locator("#wb-palette-list [role=option]")

    def test_ctrl_k_and_slash_open_the_palette(self):
        page = self.page
        self.goto(page, self.project)
        self.open_palette(page)
        # The actions of the page come first, and it has a role for screen
        # readers
        expect(self.options(page).first).to_contain_text("New list")
        self.assertEqual(
            page.locator("#wb-palette-input").get_attribute("role"), "combobox"
        )
        page.keyboard.press("Escape")
        expect(page.locator("#wb-palette")).not_to_be_visible()
        self.open_palette(page, "/")
        # "/" typed into the open palette is just a character
        page.keyboard.type("/")
        self.assertEqual(page.locator("#wb-palette-input").input_value(), "/")
        self.assertEqual(self.errors, [])

    def test_focus_returns_where_it_was(self):
        page = self.page
        self.goto(page, self.project)
        page.locator("a.navbar-brand").focus()
        self.open_palette(page)
        page.keyboard.press("Escape")
        expect(page.locator("a.navbar-brand")).to_be_focused()

    def test_jumping_by_typing(self):
        self.make_list("Launch plan", todos=["Pack"])
        self.make_list("Secret plan")  # visible to nobody but staff
        page = self.page
        self.goto(page, self.project)
        self.open_palette(page)
        page.keyboard.type("laun")
        option = self.options(page).filter(has_text="Launch plan")
        expect(option).to_be_visible()
        # The search is always the last entry
        expect(self.options(page).last).to_contain_text("Search for “laun”")
        # Arrow keys move, Enter runs
        page.keyboard.press("ArrowDown")
        expect(option).to_have_attribute("aria-selected", "true")
        page.keyboard.press("Enter")
        page.wait_for_url("**/lists/*/")
        expect(page.locator("h1")).to_contain_text("Launch plan")

    def test_search_is_an_entry(self):
        page = self.page
        self.goto(page, self.project)
        self.open_palette(page)
        page.keyboard.type("zebra")
        expect(self.options(page).last).to_contain_text("Search for “zebra”")
        page.keyboard.press("Enter")
        page.wait_for_url("**/search/?q=zebra")

    def test_a_client_does_not_find_internal_items(self):
        self.make_list("Launch plan", visible=True)
        self.make_list("Secret plan")
        page = self.login(self.cleo)
        self.goto(page, self.project)
        self.open_palette(page)
        page.keyboard.type("plan")
        expect(self.options(page).filter(has_text="Launch plan")).to_be_visible()
        self.assertEqual(self.options(page).filter(has_text="Secret").count(), 0)
        # And no "New list" for them
        page.locator("#wb-palette-input").fill("new")
        expect(self.options(page).filter(has_text="New message")).to_be_visible()
        self.assertEqual(self.options(page).filter(has_text="New list").count(), 0)

    def test_a_new_to_do_through_the_palette(self):
        todolist = self.make_list()
        page = self.page
        self.goto(page, todolist)
        self.open_palette(page)
        page.keyboard.type("new to-do")
        page.keyboard.press("Enter")
        title = page.locator("[data-add-todo] [name=title]").first
        expect(title).to_be_focused()
        title.fill("From the palette")
        title.press("Control+Enter")
        page.locator("[data-todo]").filter(has_text="From the palette").wait_for()
        self.assertTrue(
            Item.objects.filter(title="From the palette", creator=self.ada).exists()
        )

    def test_completing_a_to_do_through_the_palette(self):
        todo = ops.create_todo(
            todolist=self.make_list(), title="Pack the tent", creator=self.ada
        )
        page = self.page
        self.goto(page, todo)
        self.open_palette(page)
        page.keyboard.type("complete")
        page.keyboard.press("Enter")
        expect(page.locator("main")).to_contain_text("Completed by")
        todo.todo.refresh_from_db()
        self.assertTrue(todo.todo.is_completed)

    def test_rows_with_j_k_o_and_x(self):
        todolist = self.make_list(todos=["One", "Two", "Three"])
        page = self.page
        self.goto(page, todolist)
        current = page.locator(".wb-kb-current")
        page.keyboard.press("j")
        expect(current).to_contain_text("One")
        # Focus follows, to the row's link
        expect(page.locator("[data-todo] a[data-kb-open]").first).to_be_focused()
        page.keyboard.press("j")
        expect(current).to_contain_text("Two")
        page.keyboard.press("j")
        page.keyboard.press("j")  # The last row stays
        expect(current).to_contain_text("Three")
        page.keyboard.press("k")
        expect(current).to_contain_text("Two")
        page.keyboard.press("Escape")
        self.assertEqual(current.count(), 0)
        # x completes the current row
        page.keyboard.press("j")
        page.keyboard.press("j")
        expect(current).to_contain_text("Two")
        page.keyboard.press("x")
        page.wait_for_function("() => !!document.querySelector('.wb-check.is-done')")
        self.assertEqual(Item.objects.get(title="Two").todo.is_completed, True)
        self.assertEqual(Item.objects.get(title="One").todo.is_completed, False)
        # o opens it
        page.keyboard.press("j")
        page.keyboard.press("o")
        page.wait_for_url("**/todos/*/")

    def test_rows_of_my_todos_and_the_feed_and_search(self):
        ops.create_todo(todolist=self.make_list(), title="Alpha", creator=self.ada)
        page = self.page
        for url, row in [
            ("/todos/", "[data-kb-row]"),
            ("/feed/", "[data-kb-row]"),
            ("/search/?q=alpha", "[data-kb-row]"),
        ]:
            self.goto(page, url)
            page.keyboard.press("j")
            expect(page.locator(".wb-kb-current")).to_have_count(1)
            self.assertTrue(
                page.locator(".wb-kb-current").first.evaluate(
                    "el => el.matches('" + row + "')"
                )
            )

    def test_g_then_t_goes_to_my_todos(self):
        page = self.page
        self.goto(page, self.project)
        page.keyboard.press("g")
        page.keyboard.press("t")
        page.wait_for_url("**/todos/?assignee=me")
        page.keyboard.press("g")
        page.keyboard.press("p")
        page.wait_for_url(f"{self.live_server_url}/")

    def test_a_question_mark_lists_the_shortcuts(self):
        page = self.page
        self.goto(page, self.project)
        page.keyboard.press("?")
        dialog = page.locator("#wb-shortcuts")
        expect(dialog).to_be_visible()
        expect(dialog).to_contain_text("command palette")
        page.keyboard.press("Escape")
        expect(dialog).not_to_be_visible()

    def test_shortcuts_of_an_item_page(self):
        todo = ops.create_todo(
            todolist=self.make_list(), title="Pack", creator=self.ada
        )
        page = self.page
        self.goto(page, todo)
        page.keyboard.press("c")
        expect(page.locator("#comments ~ form textarea")).to_be_focused()
        page.locator("h1").click()
        page.keyboard.press("b")
        page.wait_for_function(
            "() => !!document.querySelector('[title=\"Remove the bookmark\"]')"
        )

    def test_nothing_fires_while_typing(self):
        todolist = self.make_list(todos=["One", "Two"])
        page = self.page
        self.goto(page, todolist)
        add = page.locator("[data-add-todo]").first
        add.locator("summary").click()
        title = add.locator("[name=title]")
        expect(title).to_be_focused()
        page.keyboard.type("jkx?/gt c")
        self.assertEqual(title.input_value(), "jkx?/gt c")
        self.assertEqual(page.locator(".wb-kb-current").count(), 0)
        expect(page.locator("#wb-palette")).not_to_be_visible()
        expect(page.locator("#wb-shortcuts")).not_to_be_visible()
        self.assertEqual(
            page.url, f"{self.live_server_url}{todolist.get_absolute_url()}"
        )
        # Ctrl+K works while typing
        self.open_palette(page)

    def test_with_the_setting_off_only_ctrl_k_works(self):
        self.ada.keyboard_shortcuts = False
        self.ada.save()
        todolist = self.make_list(todos=["One"])
        page = self.page
        self.goto(page, todolist)
        for key in ["j", "/", "?", "x"]:
            page.keyboard.press(key)
        self.assertEqual(page.locator(".wb-kb-current").count(), 0)
        expect(page.locator("#wb-palette")).not_to_be_visible()
        expect(page.locator("#wb-shortcuts")).not_to_be_visible()
        page.keyboard.press("g")
        page.keyboard.press("t")
        self.assertEqual(
            page.url, f"{self.live_server_url}{todolist.get_absolute_url()}"
        )
        self.open_palette(page)
        # The actions still run from the palette
        page.keyboard.type("my to-dos")
        page.keyboard.press("Enter")
        page.wait_for_url("**/todos/?assignee=me")

    def test_the_theme_action_and_the_stored_theme(self):
        page = self.page
        self.goto(page, self.project)
        self.open_palette(page)
        page.keyboard.type("switch the theme")
        page.keyboard.press("Enter")
        page.wait_for_function(
            "() => document.documentElement.dataset.themeMode === 'light'"
        )
        # Saved for the person, so that it follows them
        page.wait_for_function(
            "() => fetch('/api/v1/me/').then(r => r.json()).then(m => m.theme === 'light')"
        )
        self.ada.refresh_from_db()
        self.assertEqual(self.ada.theme, "light")
        self.assertEqual(self.errors, [])

    def test_the_settings_page_previews_the_appearance(self):
        page = self.page
        root = "document.documentElement.dataset"
        self.goto(page, "/accounts/settings/")
        stored = page.evaluate(f"[{root}.themeMode, {root}.accent]")
        accent = "lake" if stored[1] != "lake" else "berry"
        page.locator(f'input[name="accent"][value="{accent}"]').check()
        page.wait_for_function(f"() => {root}.accent === '{accent}'")
        # The page's background takes a hint of the accent color at once
        background = "getComputedStyle(document.body).backgroundColor"
        tinted = page.evaluate(background)
        page.locator(f'input[name="accent"][value="{stored[1]}"]').check()
        page.wait_for_function(f"() => {root}.accent === '{stored[1]}'")
        self.assertNotEqual(page.evaluate(background), tinted)
        page.locator(f'input[name="accent"][value="{accent}"]').check()
        page.locator('input[name="theme"][value="dark"]').check()
        page.wait_for_function(f"() => {root}.accent === '{accent}'")
        self.assertEqual(page.evaluate(f"{root}.themeMode"), "dark")
        self.assertEqual(
            page.evaluate("document.documentElement.dataset.bsTheme"), "dark"
        )
        self.ada.refresh_from_db()
        self.assertNotEqual(self.ada.accent, accent)
        # Reset goes back to the stored choice
        reset = page.locator("[data-appearance-reset]")
        expect(reset).to_be_visible()
        reset.click()
        self.assertEqual(page.evaluate(f"[{root}.themeMode, {root}.accent]"), stored)
        expect(reset).to_be_hidden()
        # Reloading without saving shows the stored choice
        page.locator(f'input[name="accent"][value="{accent}"]').check()
        page.locator('input[name="theme"][value="dark"]').check()
        page.reload()
        self.assertEqual(page.evaluate(f"[{root}.themeMode, {root}.accent]"), stored)
        # Saving stores it
        page.locator(f'input[name="accent"][value="{accent}"]').check()
        page.locator('input[name="theme"][value="dark"]').check()
        page.locator("[data-appearance-preview] button[type=submit]").click()
        page.wait_for_load_state()
        self.ada.refresh_from_db()
        self.assertEqual((self.ada.theme, self.ada.accent), ("dark", accent))
        self.assertEqual(
            page.evaluate(f"[{root}.themeMode, {root}.accent]"), ["dark", accent]
        )
        self.assertEqual(self.errors, [])


class ProjectColorTest(E2ETestCase):
    """Project colors (specs/project-colors.md): the card's stripe, the dot
    and the header's line are drawn, with the project's name beside them, and
    nothing runs off the screen, on a phone and on a desktop"""

    SIZES = {
        "phone": {"width": 360, "height": 740},
        "desktop": {"width": 1280, "height": 800},
    }

    def setUp(self):
        super().setUp()
        from biwak.projects import operations as project_ops

        project_ops.update_project(self.project, actor=self.ada, color="lake")
        self.second = project("Wiki", members=[self.ada])
        project_ops.update_project(self.second, actor=self.ada, color="berry")
        self.todolist = self.make_list("Launch plan", todos=["Pack"])

    def assertFits(self, page):
        self.assertEqual(
            page.evaluate("document.documentElement.scrollWidth - window.innerWidth"),
            0,
        )

    def colors(self, page, selector):
        return page.evaluate(
            """(selector) => [...document.querySelectorAll(selector)].map(
                (el) => getComputedStyle(el)
            ).map((style) => [style.backgroundColor, style.borderInlineStartColor])""",
            selector,
        )

    def test_the_projects_page_and_a_feed_page(self):
        for size, viewport in self.SIZES.items():
            with self.subTest(size=size):
                page = self.login(self.ada, viewport=viewport)
                page.goto(f"{self.live_server_url}{reverse('projects')}")
                cards = page.locator(".wb-project-card")
                expect(cards).to_have_count(2)
                lake = page.locator(".wb-project-card", has_text="Website")
                berry = page.locator(".wb-project-card", has_text="Wiki")
                # The dot and the name, in text
                expect(lake.locator(".wb-project-dot")).to_be_visible()
                expect(lake.locator(".wb-project-dot .visually-hidden")).to_have_text(
                    "Color: Lake"
                )
                expect(berry.locator(".wb-project-dot .visually-hidden")).to_have_text(
                    "Color: Berry"
                )
                stripes = page.evaluate(
                    """() => [...document.querySelectorAll(".wb-project-card")].map(
                        (el) => [
                            getComputedStyle(el).borderInlineStartColor,
                            getComputedStyle(el).borderInlineStartWidth,
                            getComputedStyle(el.querySelector(".wb-project-dot"))
                                .backgroundColor,
                        ]
                    )"""
                )
                self.assertEqual(len(stripes), 2)
                for stripe, width, dot in stripes:
                    self.assertEqual(stripe, dot)
                    self.assertNotEqual(stripe, "rgba(0, 0, 0, 0)")
                    self.assertGreaterEqual(float(width.removesuffix("px")), 3)
                self.assertNotEqual(stripes[0][0], stripes[1][0])
                self.assertFits(page)

                # The project's header: the dot and the line
                page.goto(f"{self.live_server_url}{self.project.get_absolute_url()}")
                expect(page.locator("h1 .wb-project-dot")).to_be_visible()
                expect(page.locator("h1")).to_contain_text("Website")
                line = page.locator(".wb-project-line")
                expect(line).to_be_visible()
                self.assertGreaterEqual(line.bounding_box()["height"], 2)
                self.assertFits(page)

                # The feed: every project's dot, beside its name
                page.goto(f"{self.live_server_url}{reverse('feed')}")
                row = page.locator("li", has_text="Website").filter(
                    has=page.locator(".wb-project-dot")
                )
                expect(row.first).to_be_visible()
                self.assertFits(page)

    def test_the_palette_shows_the_dot_beside_the_project(self):
        page = self.login(self.ada, viewport=self.SIZES["desktop"])
        self.goto(page, self.project)
        page.keyboard.press("Control+k")
        page.keyboard.type("launch")
        option = page.locator("#wb-palette-list [role=option]").filter(
            has_text="Launch plan"
        )
        expect(option).to_be_visible()
        expect(option.locator(".wb-project-dot")).to_be_visible()
        expect(option.locator(".wb-palette-hint")).to_contain_text("Website")


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
        # Initials without an image
        expect(options.filter(has_text="Bob").locator("span.wb-avatar")).to_have_text(
            "BE"
        )
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
        textarea.click()
        textarea.press_sequentially("Hi @Example")
        listbox = page.locator(".wb-mentions:not([hidden])")
        listbox.wait_for()
        ada = listbox.locator("li", has_text="Ada")
        expect(ada.locator("img.wb-avatar")).to_have_count(1)
        expect(
            listbox.locator("li", has_text="Bob").locator("span.wb-avatar")
        ).to_have_text("BE")
        page.wait_for_function(
            "() => document.querySelector('.wb-mentions img.wb-avatar').naturalWidth === 256"
        )

    def test_an_image_which_does_not_load_falls_back_to_the_initials(self):
        """The script lists the image URL of everybody; where the view
        answers 404 (someone the viewer may not know, here a file gone) the
        initials take its place"""
        from django.core.files.storage import default_storage

        default_storage.delete(self.ada.image)
        todolist = self.make_list()
        page = self.page
        self.goto(page, todolist)
        add = page.locator("[data-add-todo]").first
        add.locator("summary").click()
        add.locator(".wb-picker-input").click()
        add.locator(".wb-picker-list li", has_text="Ada").click()
        expect(add.locator(".wb-pill span.wb-avatar")).to_have_text("AE")
        expect(add.locator(".wb-pill img")).to_have_count(0)

    def test_the_server_rendered_pages_load_the_image(self):
        page = self.page
        self.goto(page, reverse("people"))
        image = page.locator("img.wb-avatar").first
        expect(image).to_be_visible()
        page.wait_for_function(
            "() => document.querySelector('img.wb-avatar').naturalWidth === 256"
        )
        self.assertEqual(self.errors, [])
