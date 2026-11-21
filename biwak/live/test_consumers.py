"""The websocket of live updates and the lantern's count (specs/lantern.md):
who may watch what, losing access, announcements after the commit only,
and to the pages showing the item only. Clients never hear of internal
changes."""

import asyncio
import json
from unittest.mock import patch

from allauth.usersessions.models import UserSession
from channels.auth import AuthMiddlewareStack
from channels.db import database_sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.sessions.models import Session
from django.db import transaction
from django.test import Client, TransactionTestCase
from django.urls import reverse

from biwak.activity.operations import subscribe
from biwak.collab.routing import websocket_urlpatterns
from biwak.items import operations as ops
from biwak.live import announce, consumers
from biwak.projects import operations as project_ops
from biwak.projects.models import Membership
from biwak.reactions.operations import add_reaction, remove_reaction
from biwak.test_utils import organization, person, project


application = AuthMiddlewareStack(URLRouter(websocket_urlpatterns))


class LiveConsumerTest(TransactionTestCase):
    """A transaction test: operations commit, so their announcements go out
    as in production"""

    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")  # Staff, not a member
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.cleo])
        self.shared = ops.create_list(
            project=self.project, title="Shared", creator=self.ada, visible=True
        )
        self.internal = ops.create_list(
            project=self.project, title="Internal", creator=self.ada
        )
        self.todo = ops.create_todo(
            todolist=self.shared, title="Order the tent", creator=self.ada
        )
        self.secret = ops.create_todo(
            todolist=self.internal, title="Budget", creator=self.ada
        )
        self.communicators = []

    async def asyncTearDown(self):
        for communicator in self.communicators:
            await communicator.disconnect()

    def session(self, user):
        client = Client()
        client.force_login(user)
        return client.cookies["sessionid"].value

    async def connect(self, user, item=None, *, query=None, ready=True, key=None):
        """``key``: the login session's, else a new one's"""
        headers = []
        if user is not None:
            if key is None:
                key = await database_sync_to_async(self.session)(user)
            headers = [(b"cookie", f"sessionid={key}".encode())]
        path = "/ws/live/"
        if query is not None:
            path += f"?{query}"
        elif item is not None:
            path += f"?item={item.pk}"
        communicator = WebsocketCommunicator(application, path, headers=headers)
        self.communicators.append(communicator)
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        if ready:
            self.assertEqual(await self.receive(communicator), {"type": "ready"})
        return communicator

    async def receive(self, communicator):
        return json.loads(await communicator.receive_from(timeout=2))

    async def assertClosed(self, communicator, code=consumers.CLOSE_NOT_FOUND):
        """Closed, and nothing else came before"""
        output = await communicator.receive_output(timeout=2)
        self.assertEqual(output, {"type": "websocket.close", "code": code})

    async def assertQuiet(self, *communicators):
        for communicator in communicators:
            self.assertTrue(await communicator.receive_nothing(timeout=0.2))

    def run_op(self, function, *args, **kwargs):
        return database_sync_to_async(function)(*args, **kwargs)

    # Who may watch what ------------------------------------------------------

    async def test_internal_items_are_refused_to_clients_like_the_pages(self):
        for item in [self.internal, self.secret]:
            with self.subTest(item=item):
                cleo = await self.connect(self.cleo, item, ready=False)
                await self.assertClosed(cleo)

    async def test_others_limited_projects_are_refused(self):
        other = await self.run_op(project, "Other", all_access=False)
        todolist = await self.run_op(
            ops.create_list, project=other, title="Plans", creator=self.ada
        )
        bob = await self.connect(self.bob, todolist, ready=False)
        await self.assertClosed(bob)

    async def test_nobody_without_a_login_and_no_nonsense(self):
        await self.assertClosed(
            await self.connect(None, self.shared, ready=False), consumers.CLOSE_NO_LOGIN
        )
        await self.assertClosed(
            await self.connect(self.ada, query="item=x", ready=False)
        )
        await self.assertClosed(
            await self.connect(self.ada, query="item=999999", ready=False)
        )

    async def test_huge_item_ids_are_refused(self):
        for value in [str(2**63), "9" * 5000]:
            with self.subTest(value=value[:10]):
                await self.assertClosed(
                    await self.connect(self.ada, query=f"item={value}", ready=False)
                )

    async def test_tabs_per_person_are_capped(self):
        with patch.object(consumers, "MAX_PER_PERSON", 2):
            first = await self.connect(self.ada)
            await self.connect(self.ada, self.todo)
            await self.assertClosed(
                await self.connect(self.ada, ready=False), consumers.CLOSE_TOO_MANY
            )
            # Others aren't affected, and a tab closed makes room
            await self.connect(self.bob)
            await first.disconnect()
            self.communicators.remove(first)
            # Refused ones don't count
            await self.assertClosed(
                await self.connect(self.ada, query="item=999999", ready=False)
            )
            await self.connect(self.ada)

    async def test_trashed_items_are_refused(self):
        await self.run_op(ops.trash, self.todo, actor=self.ada)
        await self.assertClosed(await self.connect(self.ada, self.todo, ready=False))

    # What is announced -------------------------------------------------------

    async def test_a_comment_reaches_the_item_and_its_list(self):
        on_todo = await self.connect(self.cleo, self.todo)
        on_list = await self.connect(self.bob, self.shared)
        comment = await self.run_op(
            ops.add_comment, self.todo, author=self.ada, content="Hi"
        )
        for communicator, watched in [(on_todo, self.todo), (on_list, self.shared)]:
            message = await self.receive(communicator)
            self.assertEqual(
                message,
                {
                    "type": "changed",
                    "item": self.todo.pk,
                    "watched": watched.pk,
                    "action": "commented",
                },
            )
            # Only IDs: no text, no name
            self.assertNotIn("Hi", json.dumps(message))
        self.assertTrue(comment)

    async def test_reactions_added_and_removed(self):
        bob = await self.connect(self.bob, self.todo)
        await self.run_op(add_reaction, self.ada, "👍", item=self.todo)
        self.assertEqual((await self.receive(bob))["action"], "reacted")
        await self.run_op(remove_reaction, self.ada, "👍", item=self.todo)
        self.assertEqual((await self.receive(bob))["action"], "reacted")

    async def test_lists_hear_of_moves_reordering_and_groups(self):
        shared = await self.connect(self.bob, self.shared)
        internal = await self.connect(self.bob, self.internal)
        other = await self.run_op(
            ops.create_todo, todolist=self.internal, title="Pack", creator=self.ada
        )
        self.assertEqual((await self.receive(internal))["action"], "created")
        await self.run_op(
            ops.move_todo, other, todolist=self.internal, index=0, actor=self.ada
        )
        self.assertEqual((await self.receive(internal))["action"], "reordered")
        # Moved to the shared list: both lists hear of it
        await self.run_op(ops.move_todo, other, todolist=self.shared, actor=self.ada)
        actions = {(await self.receive(shared))["action"] for _n in range(2)}
        self.assertEqual(actions, {"moved", "reordered"})
        # The list it left only to reorder
        self.assertEqual((await self.receive(internal))["action"], "reordered")
        todolist = await self.run_op(lambda: self.shared.todolist)
        group = await self.run_op(ops.create_group, todolist=todolist, title="Later")
        self.assertEqual((await self.receive(shared))["action"], "grouped")
        for change in [
            lambda: ops.rename_group(group, title="Soon"),
            lambda: ops.move_group(group, index=0),
            lambda: ops.delete_group(group),
        ]:
            await self.run_op(change)
            self.assertEqual((await self.receive(shared))["action"], "grouped")

    async def test_own_changes_dont_come_back(self):
        ada = await self.connect(self.ada, self.todo)
        await self.run_op(ops.add_comment, self.todo, author=self.ada, content="Hi")
        await self.assertQuiet(ada)

    async def test_nothing_reaches_pages_not_showing_the_item(self):
        ada = await self.connect(self.ada, self.todo)
        bob = await self.connect(self.bob, self.internal)
        cleo = await self.connect(self.cleo, self.shared)
        other = await self.run_op(
            ops.create_list, project=self.project, title="Other", creator=self.bob
        )
        await self.run_op(
            ops.create_todo, todolist=other, title="Elsewhere", creator=self.bob
        )
        await self.assertQuiet(ada, bob, cleo)

    async def test_announcements_after_the_commit_only(self):
        from channels.layers import get_channel_layer

        bob = await self.connect(self.bob, self.todo)
        layer = get_channel_layer()
        channel = await layer.new_channel()
        await layer.group_add(announce.item_group(self.todo.pk, clients=False), channel)

        def change():
            with transaction.atomic():
                ops.add_comment(self.todo, author=self.ada, content="Hi")
                # Inside the transaction nothing went out
                self.assertFalse(get_channel_layer().channels.get(channel))

        # Rolled back: never
        def rolled_back():
            try:
                with transaction.atomic():
                    ops.add_comment(self.todo, author=self.ada, content="Never")
                    raise RuntimeError
            except RuntimeError:
                pass

        await self.run_op(rolled_back)
        await self.assertQuiet(bob)
        await self.run_op(change)
        self.assertEqual((await self.receive(bob))["action"], "commented")

    async def test_a_client_never_hears_of_an_internal_change(self):
        """The list hidden from clients: the client's page hears nothing of
        it, and closes; what happens afterwards doesn't reach it"""
        cleo = await self.connect(self.cleo, self.shared)
        on_todo = await self.connect(self.cleo, self.todo)
        ada = await self.connect(self.bob, self.shared)
        await self.run_op(
            ops.set_visibility, self.shared, visible=False, actor=self.ada
        )
        await self.assertClosed(cleo)
        await self.assertClosed(on_todo)
        self.assertEqual((await self.receive(ada))["action"], "visibility_changed")

    async def test_internal_changes_go_to_staff_pages_only(self):
        """Even if a client's page were in the item's group: what happened
        while the item was internal goes to the staff group only"""
        from channels.layers import get_channel_layer

        layer = get_channel_layer()
        clients = await layer.new_channel()
        staff = await layer.new_channel()
        await layer.group_add(
            announce.item_group(self.internal.pk, clients=True), clients
        )
        await layer.group_add(
            announce.item_group(self.internal.pk, clients=False), staff
        )
        await self.run_op(ops.add_comment, self.secret, author=self.ada, content="Psst")
        message = await layer.receive(staff)
        self.assertEqual(message["type"], "live.changed")
        with self.assertRaises(TimeoutError):
            async with asyncio.timeout(0.2):
                await layer.receive(clients)

    # Losing access -----------------------------------------------------------

    async def test_partners_only_in_their_projects(self):
        """Staff of another organization (specs/access.md): all-access
        projects they aren't members of are refused, and becoming a partner
        closes the page"""
        bob = await self.connect(self.bob, self.todo)

        def make_partner():
            self.bob.organization = organization("Example Partner Agency")
            self.bob.save()

        await self.run_op(make_partner)
        await self.assertClosed(bob)
        bob = await self.connect(self.bob, self.todo, ready=False)
        await self.assertClosed(bob)
        await self.run_op(
            Membership.objects.create, project=self.project, user=self.bob
        )
        await self.connect(self.bob, self.todo)

    async def test_removed_from_the_project(self):
        cleo = await self.connect(self.cleo, self.shared)
        await self.run_op(
            project_ops.remove_member, self.project, self.cleo, actor=self.ada
        )
        await self.assertClosed(cleo)

    async def test_made_a_client_in_the_admin(self):
        """Visible still (a member, the list visible to clients), but from
        now on the page only hears what clients may hear"""
        from channels.layers import get_channel_layer

        bob = await self.connect(self.bob, self.shared)

        def make_client():
            with transaction.atomic():
                self.bob.is_client = True
                self.bob.save()
                project_ops.add_member(self.project, self.bob, actor=self.ada)

        await self.run_op(make_client)
        await self.assertQuiet(bob)
        groups = get_channel_layer().groups
        self.assertEqual(
            len(groups.get(announce.item_group(self.shared.pk, clients=True), {})), 1
        )
        self.assertEqual(
            len(groups.get(announce.item_group(self.shared.pk, clients=False), {})), 0
        )

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

    async def test_logging_out_closes(self):
        client, key = await self.logged_in(self.ada)
        ada = await self.connect(self.ada, self.todo, key=key)
        elsewhere = await self.connect(self.ada, self.todo)
        await self.run_op(client.post, reverse("account_logout"))
        await self.assertClosed(ada, consumers.CLOSE_NO_LOGIN)
        # Only that session's tabs
        await self.assertQuiet(elsewhere)

    async def test_logging_out_everywhere_closes(self):
        _client, key = await self.logged_in(self.ada)
        ada = await self.connect(self.ada, self.todo, key=key)
        here, here_key = await self.logged_in(self.ada)
        tab = await self.connect(self.ada, self.todo, key=here_key)
        await self.run_op(here.post, reverse("usersessions_list"))
        await self.assertClosed(ada, consumers.CLOSE_NO_LOGIN)
        await self.assertQuiet(tab)

    async def test_access_lost_without_a_message_closes_at_the_next_change(self):
        """The access check's message lost (or never sent: changed in the
        database directly): the next announcement checks first"""
        cleo = await self.connect(self.cleo, self.todo)
        await self.run_op(
            Membership.objects.filter(project=self.project, user=self.cleo).delete
        )
        await self.run_op(ops.add_comment, self.todo, author=self.ada, content="Hi")
        await self.assertClosed(cleo)

    async def test_made_a_client_without_a_message(self):
        """Made a client in the database directly: an announcement still on
        its way to the staff group doesn't reach the page, which joins the
        clients' group"""
        from channels.layers import get_channel_layer

        bob = await self.connect(self.bob, self.shared)

        def make_client():
            type(self.bob).objects.filter(pk=self.bob.pk).update(is_client=True)
            Membership.objects.create(project=self.project, user=self.bob)

        await self.run_op(make_client)
        await get_channel_layer().group_send(
            announce.item_group(self.shared.pk, clients=False),
            {
                "type": "live.changed",
                "item": self.secret.pk,
                "watched": self.shared.pk,
                "action": "moved",
                "actor": self.ada.pk,
            },
        )
        await self.assertQuiet(bob)
        groups = get_channel_layer().groups
        self.assertIn(announce.item_group(self.shared.pk, clients=True), groups)

    async def test_logged_out_without_a_message_closes_at_the_next_change(self):
        ada = await self.connect(self.ada, self.todo)
        await self.run_op(Session.objects.all().delete)
        await self.run_op(ops.add_comment, self.todo, author=self.bob, content="Hi")
        await self.assertClosed(ada, consumers.CLOSE_NO_LOGIN)

    # The lantern -------------------------------------------------------------

    async def test_the_lantern_count(self):
        await self.run_op(subscribe, self.bob, self.secret)
        bob = await self.connect(self.bob)
        await self.run_op(ops.add_comment, self.secret, author=self.ada, content="Hi")
        self.assertEqual(await self.receive(bob), {"type": "lantern"})
        from biwak.activity import lantern

        await self.run_op(lantern.read, self.bob)
        self.assertEqual(await self.receive(bob), {"type": "lantern"})
        # Others' lanterns aren't touched
        ada = await self.connect(self.ada)
        await self.run_op(ops.add_comment, self.secret, author=self.ada, content="Hi")
        await self.assertQuiet(ada)

    async def test_no_lantern_ping_about_items_one_cant_see(self):
        """A reaction removed on an item the client can't see anymore: her
        tabs aren't told"""
        comment = await self.run_op(
            ops.add_comment, self.todo, author=self.cleo, content="Hello"
        )
        await self.run_op(add_reaction, self.ada, "👍", comment=comment)
        await self.run_op(
            ops.set_visibility, self.shared, visible=False, actor=self.ada
        )
        cleo = await self.connect(self.cleo)
        await self.run_op(remove_reaction, self.ada, "👍", comment=comment)
        await self.assertQuiet(cleo)
