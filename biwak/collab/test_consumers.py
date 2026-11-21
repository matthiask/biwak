"""The websocket of docs edited live (specs/collaboration.md): who may
connect, who may type, losing access during a session, storing

A small Yjs client in Python (pycrdt) speaks the protocol of the browsers'
y-websocket provider.
"""

import asyncio
import json
from unittest.mock import ANY, patch

from allauth.usersessions.models import UserSession
from channels.auth import AuthMiddlewareStack
from channels.db import database_sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.sessions.models import Session
from django.test import Client, TransactionTestCase
from django.urls import reverse
from pycrdt import (
    Doc,
    Encoder,
    Text,
    YMessageType,
    YSyncMessageType,
    create_awareness_message,
    create_sync_message,
    create_update_message,
    handle_sync_message,
    read_message,
)

from biwak.activity.models import Event
from biwak.collab import consumers, live, ytext
from biwak.collab.consumers import decode_awareness, encode_awareness
from biwak.collab.models import LiveUpdate
from biwak.collab.routing import websocket_urlpatterns
from biwak.files import operations
from biwak.items import operations as ops
from biwak.items.models import Item
from biwak.projects import operations as project_ops
from biwak.projects.models import Membership
from biwak.test_utils import person, project


application = AuthMiddlewareStack(URLRouter(websocket_urlpatterns))


class YClient:
    """An editor: its own Yjs document, synced through the websocket"""

    def __init__(self, communicator):
        self.communicator = communicator
        self.doc = Doc()
        self.text = self.doc.get(ytext.TEXT, type=Text)
        self.modes = []
        self.awareness = []

    async def receive(self):
        """The next message from the server, handled; returns it"""
        output = await self.communicator.receive_output()
        if output["type"] == "websocket.close":
            return output
        data = output["bytes"]
        if data[0] == 0:
            reply = handle_sync_message(data[1:], self.doc)
            if reply is not None:
                await self.communicator.send_to(bytes_data=reply)
        elif data[0] == 1:
            self.awareness.append(decode_awareness(read_message(data[1:])))
        elif data[0] == consumers.MESSAGE_MODE:
            self.modes.append(data[1])
        return output

    async def drain(self):
        """Handles what the server sends until it's quiet"""
        while not await self.communicator.receive_nothing(timeout=0.2):
            await self.receive()

    async def sync(self):
        await self.communicator.send_to(bytes_data=create_sync_message(self.doc))
        await self.drain()

    async def type(self, at, value):
        before = self.doc.get_state()
        self.text.insert(len(str(self.text)[:at].encode()), value)
        await self.send_update(self.doc.get_update(before))

    async def send_update(self, update):
        await self.communicator.send_to(bytes_data=create_update_message(update))

    def __str__(self):
        return str(self.text)


@patch.multiple(consumers, SAVE_AFTER=0.05, SAVE_AT_LEAST_EVERY=1)
class ConsumerTest(TransactionTestCase):
    """A transaction test: the consumer commits like in production, and
    closes connections still inside a test's transaction"""

    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.cleo])
        self.shared = ops.create_doc(
            project=self.project,
            title="Minutes",
            content="Agenda\n",
            creator=self.ada,
            visible=True,
        )
        self.secret = ops.create_doc(
            project=self.project, title="Secret", content="Internal", creator=self.ada
        )
        self.communicators = []

    async def asyncTearDown(self):
        for communicator in self.communicators:
            await communicator.disconnect()

    def session(self, user):
        client = Client()
        client.force_login(user)
        return client.cookies["sessionid"].value

    async def connect(self, user, item, *, sync=True, key=None):
        """``key``: the login session's, else a new one's"""
        headers = []
        if user is not None:
            if key is None:
                key = await database_sync_to_async(self.session)(user)
            headers = [(b"cookie", f"sessionid={key}".encode())]
        communicator = WebsocketCommunicator(
            application, f"/ws/docs/{item.pk}", headers=headers
        )
        self.communicators.append(communicator)
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        editor = YClient(communicator)
        if sync:
            await editor.sync()
        return editor

    async def assertClosed(self, editor):
        while True:
            output = await editor.receive()
            if output["type"] == "websocket.close":
                self.assertEqual(output["code"], consumers.CLOSE_NOT_FOUND)
                return

    @database_sync_to_async
    def content(self, item):
        return Item.objects.get(pk=item.pk).doc.content

    # Who may connect -------------------------------------------------------

    async def test_the_doc_as_it_is(self):
        editor = await self.connect(self.ada, self.shared)
        self.assertEqual(str(editor), "Agenda\n")
        self.assertEqual(editor.modes, [1])

    async def test_internal_docs_are_refused_to_clients_like_the_pages(self):
        editor = await self.connect(self.cleo, self.secret, sync=False)
        await self.assertClosed(editor)
        self.assertEqual(str(editor), "")

    async def test_nobody_gets_in_without_a_login_or_access(self):
        dan = await database_sync_to_async(person)("Dan", client=True)
        for user in [None, dan]:
            with self.subTest(user=user):
                editor = await self.connect(user, self.shared, sync=False)
                await self.assertClosed(editor)
        other = await database_sync_to_async(project)("Other", all_access=False)
        doc = await database_sync_to_async(ops.create_doc)(
            project=other, title="Elsewhere", creator=self.bob
        )
        await self.assertClosed(await self.connect(self.ada, doc, sync=False))

    async def test_only_pages_of_our_hosts_connect(self):
        """asgi.py: the session cookie authenticates, so a page elsewhere
        mustn't open the websocket with it (ALLOWED_HOSTS)"""
        import asgi

        key = await database_sync_to_async(self.session)(self.ada)
        for origin, connects in [
            ("https://elsewhere.example.org", False),
            ("https://biwak.example.org", True),
        ]:
            with (
                self.subTest(origin=origin),
                self.settings(ALLOWED_HOSTS=["biwak.example.org"]),
            ):
                communicator = WebsocketCommunicator(
                    asgi.application,
                    f"/ws/docs/{self.shared.pk}",
                    headers=[
                        (b"cookie", f"sessionid={key}".encode()),
                        (b"origin", origin.encode()),
                    ],
                )
                connected, _ = await communicator.connect()
                self.assertEqual(connected, connects)
                await communicator.disconnect()

    async def test_trashed_docs_are_refused(self):
        await database_sync_to_async(ops.trash)(self.shared, actor=self.ada)
        await self.assertClosed(await self.connect(self.ada, self.shared, sync=False))

    # Who may type ----------------------------------------------------------

    async def test_staff_type_and_the_others_see_it(self):
        ada = await self.connect(self.ada, self.shared)
        bob = await self.connect(self.bob, self.shared)
        await ada.type(6, " for Monday")
        await bob.drain()
        self.assertEqual(str(bob), "Agenda for Monday\n")
        await bob.type(0, "# ")
        await ada.drain()
        self.assertEqual(str(ada), "# Agenda for Monday\n")
        self.assertEqual(await self.content(self.shared), "# Agenda for Monday\n")

    async def test_clients_watch_docs_they_did_not_create(self):
        ada = await self.connect(self.ada, self.shared)
        cleo = await self.connect(self.cleo, self.shared)
        self.assertEqual(cleo.modes, [0])
        await ada.type(0, "Draft: ")
        await cleo.drain()
        self.assertEqual(str(cleo), "Draft: Agenda\n")
        # What a client types into the doc goes nowhere
        await cleo.type(0, "Approved. ")
        await ada.drain()
        self.assertEqual(str(ada), "Draft: Agenda\n")
        await asyncio.sleep(0.1)
        self.assertEqual(await self.content(self.shared), "Draft: Agenda\n")

    async def test_clients_edit_docs_they_created(self):
        doc = await database_sync_to_async(ops.create_doc)(
            project=self.project,
            title="Our notes",
            content="",
            creator=self.cleo,
            visible=True,
        )
        cleo = await self.connect(self.cleo, doc)
        self.assertEqual(cleo.modes, [1])
        ada = await self.connect(self.ada, doc)
        await cleo.type(0, "Questions")
        await ada.drain()
        self.assertEqual(str(ada), "Questions")

    async def test_read_only_docs_are_watched_by_everybody(self):
        await database_sync_to_async(operations.set_read_only)(
            self.shared, read_only=True, actor=self.ada
        )
        ada = await self.connect(self.ada, self.shared)
        self.assertEqual(ada.modes, [0])
        await ada.type(0, "x")
        await asyncio.sleep(0.1)
        self.assertEqual(await database_sync_to_async(LiveUpdate.objects.count)(), 0)

    async def test_broken_messages_are_ignored(self):
        ada = await self.connect(self.ada, self.shared)
        with self.assertLogs("biwak.collab.consumers", "WARNING"):
            for data in [
                b"\x00\x02\x05xx",
                b"\x00\x02\x02\x01\x02",
                b"\x01\x03ab",
                b"\x07",
            ]:
                await ada.communicator.send_to(bytes_data=data)
            await ada.type(0, "Still ")
            await ada.drain()
        bob = await self.connect(self.bob, self.shared)
        self.assertEqual(str(bob), "Still Agenda\n")

    # Losing access during a session ----------------------------------------

    def on_commit(self, function, *args, **kwargs):
        """Runs the operation; its messages to the editors go out when it
        commits"""
        function(*args, **kwargs)

    async def test_hiding_the_doc_closes_the_clients_session(self):
        ada = await self.connect(self.ada, self.shared)
        cleo = await self.connect(self.cleo, self.shared)
        await database_sync_to_async(self.on_commit)(
            ops.set_visibility, self.shared, visible=False, actor=self.ada
        )
        await self.assertClosed(cleo)
        await ada.type(0, "Internal: ")
        self.assertTrue(await ada.communicator.receive_nothing(0.2))

    async def test_removing_the_client_closes_the_session(self):
        cleo = await self.connect(self.cleo, self.shared)
        await database_sync_to_async(self.on_commit)(
            project_ops.remove_member, self.project, self.cleo, actor=self.ada
        )
        await self.assertClosed(cleo)

    @patch.object(consumers, "RECHECK_AFTER", 0)
    async def test_access_lost_without_a_message_closes_at_the_next_update(self):
        """The access check's message lost (or never sent: changed in the
        database directly): the next update passed on checks first (if the
        last check is older than ``RECHECK_AFTER``)"""
        cleo = await self.connect(self.cleo, self.shared)
        ada = await self.connect(self.ada, self.shared)
        await database_sync_to_async(
            Membership.objects.filter(project=self.project, user=self.cleo).delete
        )()
        await ada.type(6, " for Monday")
        await self.assertClosed(cleo)
        self.assertEqual(str(cleo), "Agenda\n")

    async def test_moving_the_doc_into_an_internal_folder(self):
        folder = await database_sync_to_async(ops.create_folder)(
            project=self.project, title="Internal", creator=self.ada
        )
        cleo = await self.connect(self.cleo, self.shared)
        await database_sync_to_async(self.on_commit)(
            ops.move_item, self.shared, parent=folder, actor=self.ada
        )
        await self.assertClosed(cleo)

    async def test_trashing_the_doc_closes_every_session(self):
        ada = await self.connect(self.ada, self.shared)
        await database_sync_to_async(self.on_commit)(
            ops.trash, self.shared, actor=self.ada
        )
        await self.assertClosed(ada)

    async def test_becoming_read_only_stops_the_typing(self):
        ada = await self.connect(self.ada, self.shared)
        await database_sync_to_async(self.on_commit)(
            operations.set_read_only, self.shared, read_only=True, actor=self.ada
        )
        await ada.drain()
        self.assertEqual(ada.modes, [1, 0])
        await ada.type(0, "x")
        await asyncio.sleep(0.1)
        self.assertEqual(await self.content(self.shared), "Agenda\n")
        await database_sync_to_async(self.on_commit)(
            operations.set_read_only, self.shared, read_only=False, actor=self.bob
        )
        await ada.drain()
        self.assertEqual(ada.modes, [1, 0, 1])

    async def test_a_person_made_client_or_deactivated(self):
        bob = await self.connect(self.bob, self.shared)

        def deactivate():
            self.bob.is_active = False
            self.bob.save()

        await database_sync_to_async(self.on_commit)(deactivate)
        await self.assertClosed(bob)

    async def test_a_project_made_limited_in_the_admin(self):
        """Bob is staff, not a member: limiting the project shuts him out
        even without an operation (the Django admin)"""
        bob = await self.connect(self.bob, self.shared)

        def limit():
            self.project.is_all_access = False
            self.project.save()

        await database_sync_to_async(self.on_commit)(limit)
        await self.assertClosed(bob)

    async def test_access_lost_while_connecting(self):
        """Checked again after joining the groups that tell about changes:
        a change between the first check and joining isn't missed"""
        with patch.object(live, "access", side_effect=[live.READ, None]):
            cleo = await self.connect(self.cleo, self.shared, sync=False)
            await self.assertClosed(cleo)
        self.assertEqual(cleo.modes, [])

    async def test_access_is_checked_before_syncing(self):
        cleo = await self.connect(self.cleo, self.shared, sync=False)
        await cleo.drain()
        # Without telling the editors
        await database_sync_to_async(Item.objects.filter(pk=self.shared.pk).update)(
            is_client_visible=False
        )
        await cleo.communicator.send_to(bytes_data=create_sync_message(cleo.doc))
        await self.assertClosed(cleo)
        self.assertEqual(str(cleo), "")

    async def test_logging_out_closes_the_session_at_the_next_check(self):
        cleo = await self.connect(self.cleo, self.shared)
        await database_sync_to_async(Session.objects.all().delete)()
        await database_sync_to_async(self.on_commit)(
            live.check_access, doc=self.shared.pk
        )
        await self.assertClosed(cleo)

    async def logged_in(self, user):
        """A client logged in, and its session listed as logging in by code
        would (``force_login()`` doesn't)"""
        client = Client()
        await database_sync_to_async(client.force_login)(user)
        key = client.cookies["sessionid"].value
        await database_sync_to_async(UserSession.objects.create)(
            user=user, session_key=key, ip="127.0.0.1", user_agent="Test"
        )
        return client, key

    async def test_logging_out_closes_the_session(self):
        client, key = await self.logged_in(self.cleo)
        cleo = await self.connect(self.cleo, self.shared, key=key)
        await database_sync_to_async(client.post)(reverse("account_logout"))
        await self.assertClosed(cleo)

    async def test_logging_out_everywhere_closes_the_session(self):
        _client, key = await self.logged_in(self.cleo)
        cleo = await self.connect(self.cleo, self.shared, key=key)
        here, _key = await self.logged_in(self.cleo)
        await database_sync_to_async(here.post)(reverse("usersessions_list"))
        await self.assertClosed(cleo)

    async def test_checking_periodically(self):
        with patch.object(consumers, "CHECK_EVERY", 0.1):
            cleo = await self.connect(self.cleo, self.shared)
            await database_sync_to_async(Item.objects.filter(pk=self.shared.pk).update)(
                is_client_visible=False
            )
            await self.assertClosed(cleo)

    # Storing --------------------------------------------------------------

    async def test_storing_after_a_pause_with_one_event_per_session(self):
        ada = await self.connect(self.ada, self.shared)
        await ada.type(6, " and minutes")
        self.assertEqual(await self.content(self.shared), "Agenda\n")
        await asyncio.sleep(0.2)
        self.assertEqual(await self.content(self.shared), "Agenda and minutes\n")
        await ada.type(0, "Our ")
        await asyncio.sleep(0.2)

        @database_sync_to_async
        def check():
            item = Item.objects.get(pk=self.shared.pk)
            self.assertEqual(item.doc.content, "Our Agenda and minutes\n")
            edits = Event.objects.filter(item=item, action="edited")
            self.assertEqual([e.actor for e in edits], [self.ada])
            versions = list(item.doc.versions.all())
            self.assertEqual(len(versions), 1)
            self.assertEqual(versions[0].content, "Our Agenda and minutes\n")
            self.assertFalse(LiveUpdate.objects.exists())

        await check()

    async def test_storing_while_somebody_keeps_typing(self):
        ada = await self.connect(self.ada, self.shared)
        with patch.multiple(consumers, SAVE_AFTER=0.3, SAVE_AT_LEAST_EVERY=0.5):
            for i in range(8):
                await ada.type(0, f"{i}")
                await asyncio.sleep(0.1)
            self.assertIn("Agenda", await self.content(self.shared))
            self.assertNotEqual(await self.content(self.shared), "Agenda\n")

    async def test_two_people_typing_make_an_event_each(self):
        ada = await self.connect(self.ada, self.shared)
        bob = await self.connect(self.bob, self.shared)
        with patch.object(consumers, "SAVE_AFTER", 10):
            await ada.type(0, "A")
            await bob.drain()
            await bob.type(1, "B")
            await ada.drain()
        # Leaving saves at once
        await bob.communicator.disconnect()
        self.communicators.remove(bob.communicator)

        @database_sync_to_async
        def check():
            item = Item.objects.get(pk=self.shared.pk)
            self.assertEqual(item.doc.content, "ABAgenda\n")
            actors = set(
                Event.objects.filter(item=item, action="edited").values_list(
                    "actor__full_name", flat=True
                )
            )
            self.assertEqual(actors, {"Ada Example", "Bob Example"})
            # The creation's version by Ada, updated: one of the authors
            self.assertEqual(item.doc.versions.count(), 1)

        await check()

    async def test_offline_edits_merge_on_reconnect(self):
        ada = await self.connect(self.ada, self.shared)
        bob = await self.connect(self.bob, self.shared)
        await ada.communicator.disconnect()
        self.communicators.remove(ada.communicator)
        # Both type, Ada offline
        ada.text.insert(len(b"Agenda"), " (Ada)")
        await bob.type(0, "Bob: ")
        # Back online: a new connection with the same document
        communicator = WebsocketCommunicator(
            application,
            f"/ws/docs/{self.shared.pk}",
            headers=[
                (
                    b"cookie",
                    f"sessionid={await database_sync_to_async(self.session)(self.ada)}".encode(),
                )
            ],
        )
        self.communicators.append(communicator)
        await communicator.connect()
        ada.communicator = communicator
        await ada.sync()
        await bob.drain()
        self.assertEqual(str(ada), "Bob: Agenda (Ada)\n")
        self.assertEqual(str(bob), "Bob: Agenda (Ada)\n")

    async def test_an_api_edit_arrives_in_the_editors(self):
        ada = await self.connect(self.ada, self.shared)
        await ada.type(0, "Live ")
        await database_sync_to_async(self.on_commit)(
            operations.update_doc,
            self.shared,
            actor=self.bob,
            content="Agenda\n- one\n",
        )
        await ada.drain()
        # The API changed the text as it saw it, what Ada typed stays
        self.assertEqual(str(ada), "Live Agenda\n- one\n")
        self.assertEqual(await self.content(self.shared), "Live Agenda\n- one\n")

    # Awareness: cursors and names -------------------------------------------

    async def test_names_come_from_the_server_and_leaving_is_told(self):
        ada = await self.connect(self.ada, self.shared)
        cleo = await self.connect(self.cleo, self.shared)
        state = json.dumps({"user": {"name": "The boss"}, "cursor": None})
        update = encode_awareness([(cleo.doc.client_id, 1, state)])
        await cleo.communicator.send_to(bytes_data=create_awareness_message(update))
        # Not somebody else's state
        update = encode_awareness([(ada.doc.client_id, 5, state)])
        await cleo.communicator.send_to(bytes_data=create_awareness_message(update))
        await ada.drain()
        (entries,) = ada.awareness
        ((client, clock, received),) = entries
        # Under an ID the server gave Cleo's editor
        self.assertNotIn(client, {cleo.doc.client_id, ada.doc.client_id})
        self.assertEqual(clock, 1)
        self.assertEqual(json.loads(received)["user"]["name"], "Cleo")
        # Cleo hears herself too (y-websocket reconnects after 30 silent
        # seconds), under her own ID (her editor doesn't list itself)
        await cleo.drain()
        self.assertEqual(cleo.awareness, [[(cleo.doc.client_id, 1, received)]])
        await cleo.communicator.disconnect()
        self.communicators.remove(cleo.communicator)
        await ada.drain()
        self.assertEqual(ada.awareness[-1], [(client, 2, "null")])

    def names(self, editor):
        return [
            json.loads(state)["user"]["name"]
            for entries in editor.awareness
            for _client, _clock, state in entries
            if state != "null"
        ]

    async def announce(self, editor, client=None, state=None):
        state = json.dumps(state or {"cursor": None})
        update = encode_awareness([(client or editor.doc.client_id, 1, state)])
        await editor.communicator.send_to(bytes_data=create_awareness_message(update))

    async def test_clients_see_who_is_here(self):
        """Who is in the doc is shown to clients like the authors of
        comments, members or not: staff of an all-access project who
        aren't members too (decided 2026-11-20)"""
        cleo = await self.connect(self.cleo, self.shared)
        bob = await self.connect(self.bob, self.shared)
        ada = await self.connect(self.ada, self.shared)
        await self.announce(bob)
        await self.announce(ada)
        await cleo.drain()
        self.assertEqual(self.names(cleo), ["Bob", "Ada"])
        ((bobs, _clock, _state),) = cleo.awareness[0]
        await bob.communicator.disconnect()
        self.communicators.remove(bob.communicator)
        await cleo.drain()
        self.assertEqual(cleo.awareness[-1], [(bobs, 2, "null")])

    async def test_nobody_takes_over_somebody_elses_presence(self):
        """Every editor's state goes out under an ID the server gave it,
        with only the cursor and the server's name: nobody removes or
        overwrites the state of somebody else's editor"""
        ada = await self.connect(self.ada, self.shared)
        bob = await self.connect(self.bob, self.shared)
        await self.announce(ada)
        await bob.drain()
        ((adas, _clock, _state),) = bob.awareness[0]
        cleo = await self.connect(self.cleo, self.shared)
        # Cleo claims Ada's editor and the ID the others know it by, with
        # a newer clock, and removes them
        for client in [ada.doc.client_id, adas]:
            await self.announce(
                cleo,
                client=client,
                state={"cursor": None, "user": {"name": "Ada"}, "name": "Ada"},
            )
            await cleo.communicator.send_to(
                bytes_data=create_awareness_message(
                    encode_awareness([(client, 9, "null")])
                )
            )
        await bob.drain()
        await ada.drain()
        received = [entry for entries in bob.awareness for entry in entries]
        self.assertEqual([e for e in received if e[0] == adas], [bob.awareness[0][0]])
        self.assertEqual(self.names(bob), ["Ada", "Cleo"])
        self.assertEqual(
            json.loads(received[1][2]),
            {"cursor": None, "user": {"name": "Cleo", "color": ANY}},
        )
        self.assertEqual(
            [e[0] for e in received[1:]], [received[1][0]] * (len(received) - 1)
        )
        # Ada heard the same
        self.assertEqual(len(ada.awareness), len(bob.awareness))

    async def test_asking_for_the_others(self):
        ada = await self.connect(self.ada, self.shared)
        bob = await self.connect(self.bob, self.shared)
        await bob.communicator.send_to(bytes_data=bytes([consumers.QUERY_AWARENESS]))
        output = await ada.receive()
        self.assertEqual(output["bytes"], bytes([consumers.QUERY_AWARENESS]))
        self.assertTrue(await bob.communicator.receive_nothing(0.1))

    # Limits ------------------------------------------------------------------

    async def awareness(self, editor, clock, state):
        update = encode_awareness([(editor.doc.client_id, clock, json.dumps(state))])
        await editor.communicator.send_to(bytes_data=create_awareness_message(update))

    @patch.multiple(consumers, AWARENESS_RATE=(5, 0.001))
    async def test_awareness_is_rate_limited(self):
        ada = await self.connect(self.ada, self.shared)
        bob = await self.connect(self.bob, self.shared)
        for clock in range(1, 21):
            await self.awareness(bob, clock, {"cursor": None})
        await ada.drain()
        self.assertEqual(len(ada.awareness), 5)

    async def test_big_awareness_and_cursors_are_ignored(self):
        ada = await self.connect(self.ada, self.shared)
        bob = await self.connect(self.bob, self.shared)
        await self.awareness(bob, 1, {"cursor": {"anchor": "x" * 2000}})
        # Many entries, each small
        update = encode_awareness([
            (bob.doc.client_id, clock, "{}") for clock in range(1, 2000)
        ])
        await bob.communicator.send_to(bytes_data=create_awareness_message(update))
        await ada.drain()
        self.assertEqual(ada.awareness, [])
        # A normal cursor still goes
        await self.awareness(bob, 2, {"cursor": {"anchor": "x" * 100}})
        await ada.drain()
        self.assertEqual(len(ada.awareness), 1)

    @patch.multiple(consumers, QUERY_AWARENESS_RATE=(2, 0.001))
    async def test_asking_for_the_others_is_rate_limited(self):
        ada = await self.connect(self.ada, self.shared)
        bob = await self.connect(self.bob, self.shared)
        for _n in range(5):
            await bob.communicator.send_to(
                bytes_data=bytes([consumers.QUERY_AWARENESS])
            )
        queries = 0
        while not await ada.communicator.receive_nothing(timeout=0.2):
            output = await ada.receive()
            queries += output["bytes"] == bytes([consumers.QUERY_AWARENESS])
        self.assertEqual(queries, 2)

    @patch.multiple(consumers, SYNC_RATE=(3, 0.001))
    async def test_syncing_is_rate_limited(self):
        # Connecting synced once already
        bob = await self.connect(self.bob, self.shared)
        for _n in range(5):
            await bob.communicator.send_to(bytes_data=create_sync_message(bob.doc))
        answers = 0
        while not await bob.communicator.receive_nothing(timeout=0.2):
            output = await bob.receive()
            answers += output["bytes"][:2] == bytes([0, 0])
        self.assertEqual(answers, 2)

    async def test_big_state_vectors_are_ignored(self):
        """A state vector: how far the editor knows each Yjs client (a few
        per doc); a huge one answered would make the server work for
        nothing"""
        bob = await self.connect(self.bob, self.shared)
        clients = consumers.MAX_STATE_VECTOR // 4
        state = Encoder()
        state.write_var_uint(clients)
        for client in range(1, clients + 1):
            state.write_var_uint(2**20 + client)
            state.write_var_uint(1)
        state = state.to_bytes()
        self.assertGreater(len(state), consumers.MAX_STATE_VECTOR)
        length = Encoder()
        length.write_var_uint(len(state))
        await bob.communicator.send_to(
            bytes_data=bytes([YMessageType.SYNC, YSyncMessageType.SYNC_STEP1])
            + length.to_bytes()
            + state
        )
        self.assertTrue(await bob.communicator.receive_nothing(timeout=0.2))
        # A normal one is answered
        await bob.communicator.send_to(bytes_data=create_sync_message(bob.doc))
        self.assertFalse(await bob.communicator.receive_nothing(timeout=0.2))
