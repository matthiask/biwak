"""Docs edited live and live updates in the browser, through the ASGI
server (specs/collaboration.md)"""

import json
import re
import time

from django.urls import reverse

from biwak.accounts.models import APIToken, User
from biwak.activity.models import Notification
from biwak.items import operations as ops
from biwak.items.models import Doc, Item
from biwak.test_e2e import ASGIServerThread, E2ETestCase, expect, uvicorn
from biwak.test_utils import bare_doc


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
        # Exactly this text, without the heading create_doc() puts in front
        self.doc = bare_doc(
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
        return page.locator("[data-collab-editor] .ProseMirror")

    def text(self, page):
        """The editor's document as Markdown (without the others' cursors)"""
        return page.evaluate(
            "document.querySelector('[data-collab]').collab.editor.markdown()"
        )

    def wait_for_text(self, page, expected):
        page.wait_for_function(
            """(expected) => document.querySelector('[data-collab]')
                .collab.editor.markdown() === expected""",
            arg=expected,
        )

    def converged(self, *pages, timeout=10):
        """The text once every editor has the same one"""
        deadline = time.monotonic() + timeout
        while True:
            texts = {self.text(page) for page in pages}
            if len(texts) == 1 or time.monotonic() > deadline:
                break
            pages[0].wait_for_timeout(100)
        self.assertEqual(len(texts), 1, texts)
        return texts.pop()

    def type(self, page, text, *, end=True):
        """Types a paragraph at the end (``end``), or where the caret is"""
        content = self.content(page)
        content.click()
        if end:
            page.keyboard.press("ControlOrMeta+End")
            page.keyboard.press("Enter")
        page.keyboard.type(text)

    def stored(self, doc=None):
        return Doc.objects.get(pk=(doc or self.doc).pk).content

    def wait_for_stored(self, expected, doc=None):
        """Doc.content follows a few seconds after the last keystroke (a
        line break at the end stays when the last block does)"""
        for _ in range(100):
            if self.stored(doc).rstrip("\n") == expected.rstrip("\n"):
                return
            time.sleep(0.1)
        self.assertEqual(self.stored(doc).rstrip("\n"), expected.rstrip("\n"))

    def test_a_doc_without_a_title_says_title(self):
        """Any doc whose first line is empty (an empty one: Markdown drops
        leading blank lines) shows "Title" there, a hint, not text (decided
        2026-11-23)"""
        doc = bare_doc(
            project=self.project, title="Empty", content="", creator=self.ada
        )
        page = self.editor(self.ada, doc)
        # Its first line becomes the title heading (decided 2026-11-23)
        first = self.content(page).locator("> *").first
        expect(first).to_have_attribute("data-placeholder", "Title")
        expect(first).to_have_js_property("tagName", "H1")
        # This doc has a title: no hint
        page = self.editor(self.ada)
        expect(self.content(page).locator("[data-placeholder]")).to_have_count(0)
        self.assertEqual(self.errors, [])

    def test_the_heading_button_makes_the_title_a_level_1_heading(self):
        """In a doc's first line the toolbar's heading is an H1, below an H2
        as in every field (decided 2026-11-23)"""
        page = self.editor(self.ada)
        button = page.locator("[data-toolbar-action=heading]")
        self.content(page).locator("p", has_text="Agenda").click()
        button.click()
        expect(self.content(page).locator("h1")).to_have_text("Agenda")
        self.content(page).press("End")
        self.content(page).press("Enter")
        page.keyboard.type("Points")
        button.click()
        expect(self.content(page).locator("h2")).to_have_text("Points")
        self.wait_for_text(page, "# Agenda\n\n## Points")
        self.assertEqual(self.errors, [])

    def test_the_toolbar_and_its_keys(self):
        """The same toolbar as above Markdown fields, working on the live
        editor's document, undone by its undo (Yjs')"""
        page = self.editor(self.ada)
        bar = page.locator("[data-collab] .wb-toolbar")
        expect(bar).to_be_visible()
        self.content(page).click()

        def select_agenda():
            page.keyboard.press("ControlOrMeta+Home")
            page.keyboard.press("Shift+End")

        select_agenda()
        bar.locator('[data-toolbar-action="bold"]').click()
        self.wait_for_text(page, "**Agenda**")
        page.keyboard.press("ControlOrMeta+z")
        self.wait_for_text(page, "Agenda")
        page.keyboard.press("ControlOrMeta+Shift+z")
        self.wait_for_text(page, "**Agenda**")
        page.keyboard.press("ControlOrMeta+z")
        # The keys
        select_agenda()
        page.keyboard.press("ControlOrMeta+i")
        self.wait_for_text(page, "*Agenda*")
        bar.locator('[data-toolbar-action="quote"]').click()
        self.wait_for_text(page, "> *Agenda*")
        self.wait_for_stored("> *Agenda*\n")
        # No "Markdown" switch: the shared document is the editor's
        expect(bar.locator('[data-toolbar-action="source"]')).to_be_hidden()
        self.assertEqual(self.errors, [])

    def test_tables_in_a_live_doc(self):
        page = self.editor(self.ada)
        self.content(page).click()
        page.keyboard.press("ControlOrMeta+End")
        page.keyboard.press("Enter")
        page.locator('[data-collab] [data-toolbar-action="table"]').click()
        page.keyboard.type("Day")
        bar = page.locator(".wb-table-bar")
        bar.locator('[data-table-action="align-center"]').click()
        bar.locator('[data-table-action="row-below"]').click()
        self.wait_for_text(
            page, "Agenda\n\n| Day |  |\n| :---: | --- |\n|  |  |\n|  |  |"
        )
        self.wait_for_stored("Agenda\n\n| Day |  |\n| :---: | --- |\n|  |  |\n|  |  |")
        self.assertFalse(self.errors)

    def test_a_tick_in_another_browser_arrives_in_the_open_editor(self):
        """Ticks on docs never wait (specs/editor.md): one browser has the
        editor open and typed something not stored yet, another ticks the
        box on the doc's page; the tick appears in the editor, the typing
        stays"""
        doc = bare_doc(
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
        # A new task item
        self.type(editor, "fuel")
        self.wait_for_text(editor, "- [ ] tent\n- [ ] rope\n- [ ] fuel")
        box = ticking.locator(".wb-checklist input[type=checkbox]").nth(1)
        box.check()
        expect(box).to_be_enabled()
        expect(box).to_be_checked()
        self.wait_for_text(editor, "- [ ] tent\n- [x] rope\n- [ ] fuel")
        self.wait_for_stored("- [ ] tent\n- [x] rope\n- [ ] fuel\n", doc)
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
            page.keyboard.press("ControlOrMeta+End")
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
        final = self.converged(*pages)
        # The others' cursors with their names, and who is here
        expect(
            pages[0].locator(".ProseMirror-yjs-cursor", has_text="Bob")
        ).to_have_count(1)
        expect(
            pages[0].locator(".ProseMirror-yjs-cursor", has_text="Cleo")
        ).to_have_count(1)
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
        for page in [ada, bob]:
            expect(self.content(page)).to_contain_text("Typed offline")
            expect(self.content(page)).to_contain_text("Typed online.")
        # Both the same, whatever arrives last (the trailing space of "Typed
        # online. " could still be on its way when "Typed online." shows):
        # reading one side too early made the other wait forever in CI
        final = self.converged(ada, bob)
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
        expect(cleo.locator(".ProseMirror-yjs-cursor", has_text="Ada")).to_have_count(1)
        # Typing does nothing
        self.content(cleo).click()
        cleo.keyboard.type("No!")
        self.wait_for_stored("Agenda\n\nDecided: yes\n")
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
        page.locator(".wb-page-actions summary", has_text="More").click()
        page.get_by_role("button", name="Hide from clients").click()
        page.wait_for_load_state()
        live = cleo.locator("[data-collab]")
        expect(live).to_have_attribute("data-collab-state", "gone")
        expect(cleo.locator("[data-collab-status]")).to_have_text(
            "You can’t see this doc anymore."
        )
        expect(self.content(cleo)).to_have_count(0)
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

    def test_undo_is_ones_own_and_composition_beside_typing(self):
        """Undo takes back one's own typing, not the other's; composing
        (an input method) while somebody else types in the same paragraph"""
        from biwak.test_e2e_editor import compose

        ada = self.editor(self.ada, page=self.page)
        bob = self.editor(self.bob)
        self.type(bob, "Bob's line")
        self.wait_for_text(ada, "Agenda\n\nBob's line")
        self.content(ada).click()
        ada.keyboard.press("ControlOrMeta+Home")
        ada.keyboard.press("End")
        ada.keyboard.type(" by Ada")
        self.wait_for_text(bob, "Agenda by Ada\n\nBob's line")
        ada.keyboard.press("ControlOrMeta+z")
        self.wait_for_text(bob, "Agenda\n\nBob's line")
        ada.keyboard.press("ControlOrMeta+Shift+z")
        self.wait_for_text(bob, "Agenda by Ada\n\nBob's line")
        # Composing on Ada's side while Bob types
        self.content(ada).click()
        ada.keyboard.press("ControlOrMeta+Home")
        compose(ada, ["に", "にほ"], "日本")
        bob.keyboard.type("!")
        final = self.converged(ada, bob)
        self.assertEqual(final, "日本Agenda by Ada\n\nBob's line!")
        # The others' cursors carry their names
        expect(ada.locator(".ProseMirror-yjs-cursor", has_text="Bob")).to_have_count(1)
        self.assertFalse(self.errors)

    def test_an_api_edit_arrives_in_the_open_editor(self):
        ada = self.editor(self.ada, page=self.page)
        self.type(ada, "Typed live", end=True)
        self.wait_for_stored("Agenda\n\nTyped live\n")
        _token, secret = APIToken.create_for(user=self.bob, title="CLI", access="write")
        api = self.playwright.request.new_context(base_url=self.live_server_url)
        response = api.patch(
            f"/api/v1/docs/{self.doc.pk}/",
            data={"content": "Agenda for Monday\n\nTyped live"},
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

    def test_a_socket_without_pongs_is_replaced(self):
        """Pings every 30 seconds; no pong within 10 is a dead connection
        (one without a close), replaced at once. The server's pongs are
        dropped on the way, the browser's clock is fast-forwarded."""
        page = self.login(self.ada)
        page.clock.install()
        sockets = []

        def opened(ws):
            # A function of our own: Playwright marks handlers, which a
            # builtin method (sockets.append) can't be
            sockets.append(ws)

        page.on("websocket", opened)

        def handler(ws):
            server = ws.connect_to_server()
            server.on_message(
                lambda message: None if '"pong"' in str(message) else ws.send(message)
            )

        page.route_web_socket("**/ws/live/**", handler)
        self.goto(page, self.todo)
        expect(page.locator("body")).to_have_attribute("data-live-state", "connected")
        self.assertEqual(len(sockets), 1)
        # The ping, then the wait for its pong
        page.clock.fast_forward(31000)
        page.wait_for_timeout(300)
        page.clock.fast_forward(11000)
        for _ in range(50):
            if len(sockets) == 2:
                break
            page.wait_for_timeout(100)
        self.assertEqual(len(sockets), 2)
        expect(page.locator("body")).to_have_attribute("data-live-state", "connected")

    def test_pongs_keep_the_socket(self):
        page = self.login(self.ada)
        page.clock.install()
        sockets = []

        def opened(ws):
            # A function of our own: Playwright marks handlers, which a
            # builtin method (sockets.append) can't be
            sockets.append(ws)

        page.on("websocket", opened)
        self.goto(page, self.todo)
        expect(page.locator("body")).to_have_attribute("data-live-state", "connected")
        frames = []

        def framed(payload):
            frames.append(payload)

        sockets[0].on("framereceived", framed)
        page.clock.fast_forward(31000)
        page.wait_for_timeout(300)
        page.clock.fast_forward(15000)
        page.wait_for_timeout(300)
        self.assertEqual(len(sockets), 1)
        self.assertIn('{"type": "pong"}', frames)

    def comment(self, page, text):
        form = page.locator("form:has(input[name=form][value=comment])")
        self.set_markdown(form.locator("textarea[name=content]"), text)
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
        expect(ada.locator("#live-header")).to_contain_text("Completed by")
        expect(ada.locator("#live-header")).to_contain_text("Bob")
        self.assertFalse(self.errors)

    def test_the_timelines_lines_appear_and_go(self):
        ada = self.open(self.ada, self.todo, page=self.page)
        bob = self.open(self.bob, self.todo)
        lines = ada.locator("#live-comments .wb-timeline-line")
        expect(lines).to_have_count(0)
        bob.get_by_role("button", name="Complete").click()
        bob.wait_for_load_state()
        expect(lines).to_have_count(1)
        expect(lines).to_contain_text("Bob completed this")
        expect(lines).to_have_class(re.compile("wb-live-new"))
        # Reopened soon after: the completing is gone (feed.md)
        bob.get_by_role("button", name="Reopen").click()
        bob.wait_for_load_state()
        expect(lines).to_have_count(0)
        self.assertFalse(self.errors)

    def test_a_row_slides_in_and_the_lantern_dot_pulses(self):
        ada = self.login(self.ada)
        self.watch_classes(ada)
        self.open(self.ada, self.todo, page=ada)
        bob = self.open(self.bob, self.todo)
        self.never_class(ada, "wb-live-enter")
        self.never_class(ada, "is-pulsing")
        self.comment(bob, "Ordered!")
        # The comment is new (a row of a list), and Ada has something unread
        self.seen_class(ada, "wb-live-enter")
        self.seen_class(ada, "is-pulsing")
        expect(ada.locator("[data-lantern-count]")).to_have_text("1 unread")
        expect(ada.locator("#live-comments .wb-live-enter")).to_have_count(0)
        self.assertFalse(self.errors)

    def test_a_todo_added_and_moved_on_the_board(self):
        board = f"{self.todolist.get_absolute_url()}?view=board"
        ada = self.open(self.ada, board, page=self.page)
        bob = self.open(self.bob, board)
        section = bob.locator("section.wb-group[data-group-item]", has_text="Doing")
        section.locator(".wb-add-todo summary").click()
        title = section.locator("[data-add-todo-form] input[name=title]")
        title.fill("Pack the stove")
        title.press("ControlOrMeta+Enter")
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

    def test_a_groups_color_appears(self):
        """Its section's attribute, a list synced child by child"""
        page = self.open(self.ada, self.todolist, page=self.page)
        section = page.locator("section.wb-group[data-group-item]", has_text="Doing")
        expect(section).not_to_have_attribute("data-group-color", re.compile("."))
        group = self.todolist.todolist.groups.get()
        bob = self.login(self.bob)
        self.goto(bob, f"/groups/{group.pk}/edit/")
        bob.get_by_label("Lake").check()
        with bob.expect_navigation():
            bob.get_by_role("button", name="Save").click()
        expect(section).to_have_attribute("data-group-color", "lake")
        self.goto(bob, f"/groups/{group.pk}/edit/")
        bob.get_by_label("None").check()
        with bob.expect_navigation():
            bob.get_by_role("button", name="Save").click()
        expect(section).not_to_have_attribute("data-group-color", re.compile("."))
        self.assertFalse(self.errors)

    def test_a_completion_keeps_the_completed_loaded_with_show_more(self):
        for i in range(6):
            todo = ops.create_todo(
                todolist=self.todolist, title=f"Done {i}", creator=self.ada
            )
            ops.complete(todo, actor=self.ada)
        ada = self.open(self.ada, self.todolist, page=self.page)
        rows = ada.locator("#completed .wb-todo")
        expect(rows).to_have_count(5)
        ada.get_by_role("link", name="Show more").click()
        expect(rows).to_have_count(6)
        bob = self.open(self.bob, self.todolist)
        bob.locator("[data-todos] .wb-todo", has_text="Order the tent").get_by_role(
            "button", name="Complete"
        ).click()
        expect(ada.locator("#completed")).to_contain_text("Completed (7)")
        expect(rows).to_have_count(7)
        expect(rows.first).to_contain_text("Order the tent")
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
        self.set_markdown(bob.locator("#live-text textarea[name=notes]"), "Two poles")
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
        section.locator("input[name=title]").press("ControlOrMeta+Enter")
        ada.locator("[data-todo]", has_text="Secret plan").wait_for()
        # Then something clients see: it arrives, the internal changes
        # didn't (not even as a "changed")
        self.goto(ada, self.todolist)
        section = ada.locator("section.wb-group").first
        section.locator(".wb-add-todo summary").click()
        section.locator("input[name=title]").fill("Buy pegs")
        section.locator("input[name=title]").press("ControlOrMeta+Enter")
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

    def test_nothing_changed_nothing_marked(self):
        """What the page's scripts add to its forms (the toolbar, mentions,
        the rich editor) isn't a change: fetched again, nothing is marked"""
        for target in (self.todolist, self.todo):
            page = self.login(self.ada)
            self.watch_classes(page)
            self.open(self.ada, target, page=page)
            self.wait_for_editors(page)
            # Reconnecting fetches the page once
            page.evaluate("document.body.live.socket.close()")
            expect(page.locator("body")).to_have_attribute(
                "data-live-updated", re.compile(r"\d")
            )
            self.never_class(page, "wb-live-new")

    def test_back_in_the_history_isnt_marked(self):
        """A page restored from the back/forward cache takes over what
        changed meanwhile without marking it, as a reload would show it
        (GitHub issue #2). Playwright turns the cache off, and Chromium's
        headless shell has none: the full Chromium with it on."""
        browser = self.playwright.chromium.launch(
            channel="chromium",
            ignore_default_args=["--disable-back-forward-cache"],
        )
        self.addCleanup(browser.close)
        default, self.browser = self.browser, browser
        try:
            page = self.login(self.ada)
        finally:
            self.browser = default
        self.watch_classes(page)
        page.add_init_script(
            """addEventListener("pageshow", (event) => {
                if (event.persisted) document.body.dataset.restored = ""
            })"""
        )
        self.open(self.ada, self.todolist, page=page)
        page.get_by_role("link", name="Order the tent").click()
        page.wait_for_load_state()
        Item.objects.filter(pk=self.todo.pk).update(title="Order the big tent")
        ops.create_todo(todolist=self.todolist, title="Pack", creator=self.bob)
        # A restored page has no load event
        page.go_back(wait_until="commit")
        expect(page.locator("body")).to_have_attribute("data-restored", "")
        expect(page.locator("main")).to_contain_text("Order the big tent")
        expect(page.locator("main")).to_contain_text("Pack")
        self.never_class(page, "wb-live-new")
        self.never_class(page, "wb-live-enter")

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

    def test_unread_and_read_items_and_one_divider(self):
        """Unread items have a red dot and bold text, read ones are quiet,
        and one line (not two) separates the groups (specs/lantern.md, "The lantern")"""
        from biwak.activity import lantern

        stove = ops.create_todo(
            todolist=self.todolist, title="Pack the stove", creator=self.ada
        )
        for todo in [self.todo, stove]:
            ops.add_comment(todo, author=self.bob, content="First")
        lantern.read(self.ada, item=self.todo)
        ada = self.open(self.ada, reverse("projects"), page=self.page)
        ada.locator("[data-lantern] > summary").click()
        menu = ada.locator("[data-lantern-menu]")
        unread = menu.locator("section.wb-lantern-item.is-unread")
        read = menu.locator("section.wb-lantern-item:not(.is-unread)")
        expect(unread).to_have_count(1)
        expect(read).to_have_count(1)
        expect(unread).to_contain_text("Pack the stove")
        expect(unread.locator(".wb-lantern-unread")).to_be_visible()
        expect(read.locator(".wb-lantern-unread")).to_have_count(0)

        def style(locator, prop):
            return locator.evaluate(f"el => getComputedStyle(el).{prop}")

        # Quiet: not bold, and not the unread items' color
        title = read.locator(".wb-lantern-title")
        self.assertLess(int(style(title, "fontWeight")), 600)
        self.assertGreaterEqual(
            int(style(unread.locator(".wb-lantern-title"), "fontWeight")), 600
        )
        self.assertNotEqual(
            style(title, "color"), style(unread.locator(".wb-lantern-title"), "color")
        )
        self.assertNotEqual(
            style(read.locator(".wb-lantern-entry"), "color"),
            style(unread.locator(".wb-lantern-entry"), "color"),
        )
        # One divider: the unread group's border, no rule on top of it
        expect(menu.locator("hr")).to_have_count(0)
        self.assertEqual(style(unread, "borderBottomWidth"), "1px")
        self.assertEqual(style(read, "borderTopWidth"), "0px")
        # Wide: 34rem, kept on the screen
        box = menu.bounding_box()
        self.assertGreater(box["width"], 26 * 16)
        self.assertLessEqual(box["x"] + box["width"], ada.viewport_size["width"])
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
