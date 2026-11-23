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

This module is the shared base (``E2ETestCase``, the ASGI server thread,
helpers); the tests are in ``test_e2e_<area>.py`` by area.
"""

import asyncio
import os
import socket
import threading
import time

from django.conf import settings
from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler
from django.db import DEFAULT_DB_ALIAS, connections
from django.db.models import F
from django.test import Client, LiveServerTestCase, tag
from django.test.testcases import LiveServerThread
from django.views.static import serve as static_serve

from biwak.items import operations as ops
from biwak.items.models import Item, Kind
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
    def _callTestMethod(self, method):
        # Playwright's errors can't be pickled: a parallel worker couldn't
        # report the failure and the whole run would end in a
        # MaybeEncodingError. An AssertionError with the message can.
        try:
            method()
        except Exception as exc:
            if type(exc).__module__.startswith("playwright."):
                raise AssertionError(f"{type(exc).__name__}: {exc}") from None
            raise

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
        self.wait_for_server_idle()

    def wait_for_server_idle(self, timeout=10):
        """Wait until the ASGI server has finished with the closed
        browsers: the editor's websocket saves the doc and tells the others
        when it disconnects, in a thread using the database, and the
        flush after the test would deadlock with it (or delete rows under
        its feet). The same for the threads of the WSGI server: a request
        the page made just before closing (the palette's, say) still reads
        while the flush truncates."""
        deadline = time.monotonic() + timeout
        # Django's request threads are daemons, which socketserver doesn't
        # keep track of
        for thread in threading.enumerate():
            if "process_request_thread" not in thread.name:
                continue
            thread.join(max(0, deadline - time.monotonic()))
            if thread.is_alive():  # pragma: no cover
                raise AssertionError("The live server still handles a request")
        server = getattr(self.server_thread, "server", None)
        state = getattr(server, "server_state", None)
        if state is None:  # Not uvicorn
            return
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
        # Only a test taking the network away causes
        # ERR_INTERNET_DISCONNECTED, and a request that failed offline can
        # be logged after the test went online again: ignored throughout.
        if (
            message.type == "error"
            and not message.location["url"].endswith("/favicon.svg")
            and "ERR_INTERNET_DISCONNECTED" not in message.text
            and not (
                "/ws/live/" in message.text
                and self.server_thread_class is not ASGIServerThread
            )
            and "status of 409" not in message.text
        ):
            self.errors.append(f"{message.text} {message.location['url']}")

    def watch_classes(self, page):
        """Remember every class any element had on this page (before it
        loads): animations are over in a moment, the classes toggling them
        are what the scripts do (``seen_class``)"""
        page.add_init_script(
            """(() => {
                window.seenClasses = new Set()
                const note = (el) => {
                    if (el.classList) el.classList.forEach((n) => seenClasses.add(n))
                }
                new MutationObserver((records) => {
                    for (const r of records) {
                        note(r.target)
                        for (const node of r.addedNodes) {
                            note(node)
                            node.querySelectorAll?.("*").forEach(note)
                        }
                    }
                }).observe(document, {
                    subtree: true, childList: true, attributes: true,
                    attributeFilter: ["class"],
                })
            })()"""
        )

    def seen_class(self, page, name):
        return page.wait_for_function(
            "(name) => window.seenClasses.has(name)", arg=name
        )

    def never_class(self, page, name):
        self.assertFalse(page.evaluate("(n) => window.seenClasses.has(n)", name), name)

    def goto(self, page, target):
        url = target if isinstance(target, str) else target.get_absolute_url()
        page.goto(f"{self.live_server_url}{url}")
        self.wait_for_sortables(page)
        self.wait_for_editors(page)

    def wait_for_editors(self, page):
        # The rich editor is a chunk loaded after the page
        # (specs/rich-editor.md): wait until every Markdown field has it
        page.wait_for_function(
            """() => [...document.querySelectorAll("textarea[data-toolbar]")]
                .every((el) => el.richEditor)"""
        )

    @staticmethod
    def editor(field):
        """The rich editor (its contenteditable) of a Markdown field, the
        textarea's locator"""
        return field.locator("xpath=preceding-sibling::div[1]").locator(".ProseMirror")

    @staticmethod
    def set_markdown(field, text):
        """Puts Markdown into the rich editor of the field (instead of
        ``fill()``, the textarea is hidden), as an edit"""
        field.page.wait_for_function("el => el.richEditor", arg=field.element_handle())
        field.evaluate("(el, text) => el.richEditor.setMarkdown(text)", text)

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
