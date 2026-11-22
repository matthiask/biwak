"""The connection banner and what pages do offline (specs/connection.md),
in the browser: the network taken away the way ``test_offline_and_reconnect``
does it"""

import time
from unittest import mock

from django.urls import reverse

from biwak.collab import live
from biwak.collab.models import LiveState
from biwak.items.models import Comment, Doc, Item
from biwak.test_e2e import ASGIServerThread, E2ETestCase, expect, uvicorn
from biwak.test_utils import bare_doc


class ConnectionTest(E2ETestCase):
    host = "127.0.0.1"
    server_thread_class = ASGIServerThread

    @classmethod
    def setUpClass(cls):
        if uvicorn is None:  # pragma: no cover
            raise cls.skipTest(cls, "uvicorn isn't installed")
        super().setUpClass()

    def setUp(self):
        super().setUp()
        self.todolist = self.make_list("Shared", visible=True, todos=["A", "B", "C"])
        self.todo = Item.objects.get(title="A")
        self.banner = lambda page: page.locator("[data-connection]")

    def open(self, user, target, *, page=None):
        page = page or self.login(user)
        self.goto(page, target)
        expect(page.locator("body")).to_have_attribute("data-live-state", "connected")
        return page

    def go_offline(self, page):
        page.context.set_offline(True)

    def go_online(self, page):
        page.context.set_offline(False)

    def test_the_banner_is_a_status_region_and_empty_online(self):
        page = self.open(self.ada, self.todolist, page=self.page)
        banner = self.banner(page)
        expect(banner).to_have_attribute("role", "status")
        expect(banner).to_have_attribute("aria-live", "polite")
        expect(banner).to_be_empty()
        expect(banner).to_be_hidden()

    def test_a_short_blip_shows_nothing(self):
        page = self.open(self.ada, self.todolist, page=self.page)
        page.evaluate(
            """() => {
                window.seen = []
                new MutationObserver(() =>
                    window.seen.push(document.querySelector("[data-connection]").textContent)
                ).observe(document.querySelector("[data-connection]"),
                    {childList: true, characterData: true, subtree: true})
                document.body.live.socket.close()
            }"""
        )
        expect(page.locator("body")).to_have_attribute("data-live-state", "offline")
        expect(page.locator("body")).to_have_attribute(
            "data-live-state", "connected", timeout=10000
        )
        time.sleep(0.5)
        self.assertEqual(page.evaluate("window.seen"), [])
        expect(self.banner(page)).to_be_empty()

    def test_a_socket_down_for_three_seconds_shows_the_banner(self):
        page = self.open(self.ada, self.todolist, page=self.page)
        # The server doesn't take the websocket anymore
        down = [True]
        page.route_web_socket(
            "**/ws/live/**",
            lambda ws: ws.close() if down[0] else ws.connect_to_server(),
        )
        page.evaluate("document.body.live.socket.close()")
        expect(page.locator("body")).to_have_attribute("data-live-state", "offline")
        time.sleep(1.5)
        expect(self.banner(page)).to_be_empty()
        expect(self.banner(page)).to_contain_text("You’re offline", timeout=5000)
        expect(self.banner(page)).to_contain_text("This page isn’t updating")
        # Reconnecting works again
        down[0] = False
        page.evaluate("window.dispatchEvent(new Event('online'))")
        expect(self.banner(page)).to_have_text("Back online.", timeout=15000)
        expect(self.banner(page)).to_be_empty(timeout=6000)

    def test_other_pages_and_back_online_with_the_page_catching_up(self):
        ada = self.open(self.ada, self.todo, page=self.page)
        bob = self.open(self.bob, self.todo)
        self.go_offline(ada)
        expect(self.banner(ada)).to_have_text(
            "You’re offline. This page isn’t updating, and changes can’t be saved "
            "until you’re back."
        )
        expect(self.banner(ada)).to_have_attribute("data-connection-state", "offline")
        form = bob.locator("form:has(input[name=form][value=comment])")
        self.set_markdown(form.locator("textarea[name=content]"), "While you were away")
        form.get_by_role("button", name="Add comment").click()
        bob.wait_for_load_state()
        expect(ada.locator("#live-comments")).not_to_contain_text("While you were away")
        self.go_online(ada)
        expect(self.banner(ada)).to_have_text("Back online.", timeout=15000)
        expect(ada.locator("#live-comments")).to_contain_text(
            "While you were away", timeout=15000
        )
        expect(self.banner(ada)).to_be_empty(timeout=6000)
        self.assertFalse(self.errors)

    def test_the_editor_says_its_text_is_kept(self):
        doc = bare_doc(
            project=self.project,
            title="Minutes",
            content="Agenda\n",
            creator=self.ada,
            visible=True,
        )
        page = self.page
        self.goto(page, reverse("doc_edit", args=[doc.pk]))
        live = page.locator("[data-collab]")
        expect(live).to_have_attribute("data-collab-state", "connected")
        self.go_offline(page)
        page.evaluate(
            "document.querySelector('[data-collab]').collab.provider.ws.close()"
        )
        expect(self.banner(page)).to_have_text(
            "You’re offline. What you type is kept and merged when you’re back."
        )
        self.assertNotIn("Don", self.banner(page).inner_text())
        self.go_online(page)
        expect(live).to_have_attribute("data-collab-state", "connected")
        expect(self.banner(page)).to_have_text("Back online.", timeout=15000)
        expect(self.banner(page)).to_be_empty(timeout=6000)
        self.assertFalse(self.errors)

    def test_a_tick_is_undone(self):
        doc = bare_doc(
            project=self.project,
            title="Packing",
            content="- [ ] tent\n- [ ] rope\n",
            creator=self.ada,
            visible=True,
        )
        page = self.open(self.ada, doc, page=self.page)
        page.evaluate("window.marker = 1")
        self.go_offline(page)
        box = page.locator(".wb-checklist input[type=checkbox]").nth(1)
        box.click()
        expect(box).not_to_be_checked()
        expect(box).to_be_enabled()
        expect(self.banner(page)).to_contain_text("You’re offline")
        # No reload to an error page
        self.assertEqual(page.evaluate("window.marker"), 1)
        self.go_online(page)
        expect(self.banner(page)).to_have_text("Back online.", timeout=15000)
        box.check()
        expect(box).to_be_checked()
        expect(box).to_be_enabled()
        self.assertFalse(self.errors)

    def test_a_drag_is_undone(self):
        page = self.open(self.ada, self.todolist, page=self.page)
        page.evaluate("window.marker = 1")
        self.go_offline(page)
        page.locator("[data-todo]", has_text="A").locator("[data-handle]").drag_to(
            page.locator("[data-todo]", has_text="C"),
            target_position={"x": 40, "y": 15},
        )
        titles = page.locator("[data-todo] .wb-todo-title")
        expect(titles).to_have_text(["A", "B", "C"])
        expect(self.banner(page)).to_contain_text("You’re offline")
        self.assertEqual(page.evaluate("window.marker"), 1)
        self.go_online(page)
        expect(self.banner(page)).to_have_text("Back online.", timeout=15000)
        self.assertEqual(
            list(
                Item.objects
                .filter(parent=self.todolist)
                .order_by("position")
                .values_list("title", flat=True)
            ),
            ["A", "B", "C"],
        )
        self.assertFalse(self.errors)

    def test_a_form_is_held_back_with_its_text(self):
        page = self.open(self.ada, self.todo, page=self.page)
        page.evaluate("window.marker = 1")
        form = page.locator("form:has(input[name=form][value=comment])")
        self.set_markdown(form.locator("textarea[name=content]"), "Typed offline")
        self.go_offline(page)
        form.get_by_role("button", name="Add comment").click()
        expect(form.locator("[data-not-sent]")).to_have_text(
            "Not sent: you’re offline."
        )
        expect(form.locator("textarea[name=content]")).to_have_value("Typed offline")
        self.assertEqual(page.evaluate("window.marker"), 1)
        self.assertEqual(Comment.objects.count(), 0)
        self.go_online(page)
        expect(form.locator("[data-not-sent]")).to_have_count(0)
        expect(self.banner(page)).to_have_text("Back online.", timeout=15000)
        # By hand, now
        form.get_by_role("button", name="Add comment").click()
        page.wait_for_load_state()
        self.assertEqual(Comment.objects.get().content, "Typed offline")
        self.assertFalse(self.errors)

    def test_a_reaction_is_held_back(self):
        page = self.open(self.ada, self.todo, page=self.page)
        reactions = page.locator(".wb-reactions").first
        reactions.locator(".wb-reaction-add summary").click()
        self.go_offline(page)
        reactions.locator("button", has_text="🎉").click()
        expect(reactions.locator("[data-not-sent]")).to_be_visible()
        expect(self.banner(page)).to_contain_text("You’re offline")
        self.go_online(page)
        self.assertFalse(self.errors)

    def test_leaving_with_unsaved_input_asks_while_offline(self):
        page = self.open(self.ada, self.todo, page=self.page)
        form = page.locator("form:has(input[name=form][value=comment])")
        self.set_markdown(form.locator("textarea[name=content]"), "Not saved")
        ask = (
            "(() => { const e = new Event('beforeunload', {cancelable: true});"
            " dispatchEvent(e); return e.defaultPrevented })()"
        )
        self.assertFalse(page.evaluate(ask))  # Online: nothing to ask
        self.go_offline(page)
        self.assertTrue(page.evaluate(ask))
        self.set_markdown(form.locator("textarea[name=content]"), "")
        self.assertFalse(page.evaluate(ask))  # Nothing typed
        self.go_online(page)

    # The live editor keeps its typing in the browser ---------------------

    def stored_docs(self, page):
        return page.evaluate(
            """async () => (await indexedDB.databases())
                .map((db) => db.name).filter((n) => n.startsWith("biwak-doc-"))"""
        )

    def edit(self, page, doc):
        self.goto(page, reverse("doc_edit", args=[doc.pk]))
        expect(page.locator("[data-collab]")).to_have_attribute(
            "data-collab-state", "connected"
        )

    def test_typing_offline_survives_closing_the_page(self):
        doc = bare_doc(
            project=self.project,
            title="Minutes",
            content="Agenda\n",
            creator=self.ada,
            visible=True,
        )
        page = self.page
        self.edit(page, doc)
        # Online nothing stays in the browser once the server has the text
        page.wait_for_function(
            """async () => !(await indexedDB.databases())
                .some((db) => db.name.startsWith("biwak-doc-"))"""
        )
        self.go_offline(page)
        page.evaluate(
            "document.querySelector('[data-collab]').collab.provider.ws.close()"
        )
        expect(self.banner(page)).to_contain_text("What you type is kept")
        page.locator("[data-collab-editor] .ProseMirror").click()
        page.keyboard.press("ControlOrMeta+End")
        page.keyboard.press("Enter")
        page.keyboard.type("Typed offline")
        page.wait_for_function(
            """async () => (await indexedDB.databases())
                .some((db) => db.name.startsWith("biwak-doc-"))"""
        )
        # The text is in the browser's storage before the tab goes
        time.sleep(0.5)
        context = page.context
        page.close()
        self.assertNotIn("Typed offline", Doc.objects.get(pk=doc.pk).content)
        context.set_offline(False)
        page = context.new_page()
        self.edit(page, doc)
        expect(page.locator("[data-collab-editor] .ProseMirror")).to_contain_text(
            "Typed offline"
        )
        for _ in range(100):
            if "Typed offline" in Doc.objects.get(pk=doc.pk).content:
                break
            time.sleep(0.1)
        self.assertEqual(
            Doc.objects.get(pk=doc.pk).content, "Agenda\n\nTyped offline\n"
        )
        # The stored copy goes once the server has it
        page.wait_for_function(
            """async () => !(await indexedDB.databases())
                .some((db) => db.name.startsWith("biwak-doc-"))""",
            timeout=10000,
        )
        self.assertFalse(self.errors)

    def test_logging_out_removes_the_stored_docs(self):
        doc = bare_doc(
            project=self.project,
            title="Minutes",
            content="Agenda\n",
            creator=self.ada,
            visible=True,
        )
        page = self.page
        self.edit(page, doc)
        page.wait_for_function(
            """async () => !(await indexedDB.databases())
                .some((db) => db.name.startsWith("biwak-doc-"))"""
        )
        # Something stored, as if the browser had been closed offline
        page.evaluate(
            """() => new Promise((resolve) => {
                const request = indexedDB.open("biwak-doc-1-1")
                request.onsuccess = () => { request.result.close(); resolve() }
            })"""
        )
        self.assertIn("biwak-doc-1-1", self.stored_docs(page))
        page.locator("summary", has_text="Ada").click()
        page.get_by_role("button", name="Sign out").click()
        page.wait_for_url("**/accounts/login/**")
        self.assertEqual(self.stored_docs(page), [])

    def test_the_stored_copy_stays_until_the_server_has_the_text(self):
        doc = bare_doc(
            project=self.project,
            title="Minutes",
            content="Agenda\n",
            creator=self.ada,
            visible=True,
        )
        page = self.page
        self.edit(page, doc)
        self.go_offline(page)
        page.evaluate(
            "document.querySelector('[data-collab]').collab.provider.ws.close()"
        )
        expect(self.banner(page)).to_contain_text("What you type is kept")
        page.locator("[data-collab-editor] .ProseMirror").click()
        page.keyboard.press("ControlOrMeta+End")
        page.keyboard.press("Enter")
        page.keyboard.type("Typed offline")
        # The server drops what the editor sends until we say otherwise
        dropping = [True]
        original = live.append

        def append(pk, update, user):
            if not dropping[0]:
                return original(pk, update, user)
            return None

        with mock.patch.object(live, "append", append):
            self.go_online(page)
            expect(page.locator("[data-collab]")).to_have_attribute(
                "data-collab-state", "connected"
            )
            expect(self.banner(page)).to_have_text("Back online.", timeout=15000)
            time.sleep(3)
            self.assertEqual(len(self.stored_docs(page)), 1)
            self.assertNotIn("Typed offline", Doc.objects.get(pk=doc.pk).content)
            dropping[0] = False
            # Saving waits 3 seconds after the last update; under a parallel
            # run's load the resend and the save take longer than alone
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if "Typed offline" in Doc.objects.get(pk=doc.pk).content:
                    break
                time.sleep(0.1)
        self.assertEqual(
            Doc.objects.get(pk=doc.pk).content, "Agenda\n\nTyped offline\n"
        )
        page.wait_for_function(
            """async () => !(await indexedDB.databases())
                .some((db) => db.name.startsWith("biwak-doc-"))""",
            timeout=10000,
        )
        self.assertFalse(self.errors)

    def test_a_copy_of_another_history_is_not_merged(self):
        doc = bare_doc(
            project=self.project,
            title="Minutes",
            content="Agenda\n",
            creator=self.ada,
            visible=True,
        )
        page = self.page
        self.edit(page, doc)
        self.go_offline(page)
        page.evaluate(
            "document.querySelector('[data-collab]').collab.provider.ws.close()"
        )
        page.locator("[data-collab-editor] .ProseMirror").click()
        page.keyboard.press("ControlOrMeta+End")
        page.keyboard.press("Enter")
        page.keyboard.type("Typed offline")
        page.wait_for_function(
            """async () => (await indexedDB.databases())
                .some((db) => db.name.startsWith("biwak-doc-"))"""
        )
        time.sleep(0.5)
        context = page.context
        page.close()
        # The server's history is made again (a restored backup, say)
        LiveState.objects.filter(doc_id=doc.pk).delete()
        time.sleep(0.01)
        context.set_offline(False)
        page = context.new_page()
        self.edit(page, doc)
        expect(page.locator("[data-collab-editor] .ProseMirror")).to_contain_text(
            "Agenda"
        )
        time.sleep(1)
        self.assertEqual(
            page.evaluate(
                "document.querySelector('[data-collab]').collab.editor.markdown()"
            ),
            "Agenda",
        )
        self.assertNotIn("Typed offline", Doc.objects.get(pk=doc.pk).content)
        # The old copy is gone, a new one made and cleared
        page.wait_for_function(
            """async () => !(await indexedDB.databases())
                .some((db) => db.name.startsWith("biwak-doc-"))""",
            timeout=10000,
        )
        self.assertFalse(self.errors)
