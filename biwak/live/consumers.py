"""The websocket of every page (specs/lantern.md): ``/ws/live/``, one per
browser tab, ``?item=ID`` for a page showing an item (or a list)

The server only ever sends that something changed, with IDs, as JSON:
``{"type": "changed", "item": ID, "watched": ID, "action": "commented"}``
(``item`` changed; the page shows ``watched``, the item or its parent)
and ``{"type": "lantern"}`` (the person's notifications changed). The page
then fetches what changed through the normal views, with their permission
checks (``frontend/live.js``, ``frontend/lantern.js``).

Joining an item's group checks that the person sees the item, like the
pages (``Item.objects.visible_to()``); clients join the group that hears
only of what happened while clients saw the item (``announce``). Access is
checked again whenever the live editor's sessions check theirs
(``collab.live.check_access()``: moves, visibility, the trash, members,
people and projects changed in the admin), and every 60 seconds; a page
that can't see its item anymore is closed with 4404 (it then fetches the
page, which says so).
"""

import asyncio
import json
from collections import Counter
from importlib import import_module

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.conf import settings

from biwak.collab import live as collab
from biwak.items.models import Item
from biwak.live import announce


# Not logged in, or the session ended (logged out): the page doesn't
# reconnect
CLOSE_NO_LOGIN = 4401
# Too many tabs of the person: the page reconnects later (backing off)
CLOSE_TOO_MANY = 4429
# The item doesn't exist for the person (anymore), like the pages' 404
CLOSE_NOT_FOUND = 4404
# Open websockets of a person in one process (**?**, a value the spec
# didn't fix): one per tab, so generous; it protects the server from a
# script opening many. Per process: nothing to clean up after a process
# died, and the workers together allow a few times as many.
MAX_PER_PERSON = 50
# The open websockets by person, in this process
connections = Counter()
# The most digits of an item's ID (fits a bigint)
MAX_ID_DIGITS = 18
# Access is checked this often besides the changes telling the pages
# (seconds, as in the live editor)
CHECK_EVERY = 60


class LiveConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope["user"]
        session = self.scope.get("session")
        self.session_key = session.session_key if session else None
        self.groups_joined = []
        self.check_task = None
        self.closed = False
        self.item = None
        self.project_id = None
        self.as_client = None
        self.counted = False
        await self.accept()
        if not self.user.is_authenticated:
            await self.refuse(CLOSE_NO_LOGIN)
            return
        if connections[self.user.pk] >= MAX_PER_PERSON:
            await self.refuse(CLOSE_TOO_MANY)
            return
        connections[self.user.pk] += 1
        self.counted = True
        value = dict(
            pair.split("=", 1)
            for pair in self.scope.get("query_string", b"").decode().split("&")
            if "=" in pair
        ).get("item", "")
        if value:
            # IDs are positive bigints: anything longer doesn't exist (and
            # would raise in int() or the database)
            if (
                not (value.isascii() and value.isdecimal())
                or len(value) > MAX_ID_DIGITS
            ):
                await self.refuse(CLOSE_NOT_FOUND)
                return
            self.item = int(value)
        found = await database_sync_to_async(self._access)()
        if found is not True:
            await self.refuse(found)
            return
        await self.join(announce.person_group(self.user.pk))
        await self.join(collab.user_group(self.user.pk))
        if self.item is not None:
            await self.join(collab.project_group(self.project_id))
            await self.join_item()
        # Once more: a change before joining told nobody
        await self.access_check()
        if self.closed:
            return
        await self.send_json({"type": "ready"})
        self.check_task = asyncio.create_task(self.check_periodically())

    async def join(self, group):
        await self.channel_layer.group_add(group, self.channel_name)
        self.groups_joined.append(group)

    async def join_item(self):
        """The item's group for staff or for clients, as the person is now"""
        self.as_client = self.user.is_client
        await self.join(announce.item_group(self.item, clients=self.as_client))

    def _access(self):
        """True, or the code to close with. The person as they are now
        (deactivated, a client now), the login session still there, the
        item visible to them."""
        self.user.refresh_from_db()
        if not self.user.is_active:
            return CLOSE_NO_LOGIN
        if self.session_key is not None:
            store = import_module(settings.SESSION_ENGINE).SessionStore
            if not store().exists(self.session_key):
                return CLOSE_NO_LOGIN
        if self.item is None:
            return True
        project_id = (
            Item.objects
            .visible_to(self.user)
            .filter(pk=self.item)
            .values_list("project_id", flat=True)
            .first()
        )
        if project_id is None:
            return CLOSE_NOT_FOUND
        self.project_id = project_id
        return True

    async def disconnect(self, code):
        if self.check_task is not None:
            self.check_task.cancel()
        await self.leave()

    async def leave(self):
        """Leaves the groups, and doesn't count as one of the person's
        websockets anymore"""
        if self.counted:
            self.counted = False
            connections[self.user.pk] -= 1
            if not connections[self.user.pk]:
                del connections[self.user.pk]
        for group in self.groups_joined:
            await self.channel_layer.group_discard(group, self.channel_name)
        self.groups_joined = []

    async def receive(self, text_data=None, bytes_data=None):
        """Nothing to receive: the page said what it shows when connecting"""

    # From the channel layer --------------------------------------------

    async def live_changed(self, event):
        # One's own changes are on one's page already
        if event.get("actor") == self.user.pk:
            return
        await self.send_json({
            "type": "changed",
            "item": event["item"],
            "watched": event["watched"],
            "action": event["action"],
        })

    async def lantern_changed(self, event):
        await self.send_json({"type": "lantern"})

    async def access_check(self, event=None):
        if event and event.get("session") and event["session"] == self.session_key:
            # Logged out (the session may not be deleted yet)
            await self.refuse(CLOSE_NO_LOGIN)
            return
        found = await database_sync_to_async(self._access)()
        if found is not True:
            await self.refuse(found)
            return
        if self.item is not None and self.as_client != self.user.is_client:
            # Made a client (or staff) meanwhile: the other group
            old = announce.item_group(self.item, clients=self.as_client)
            await self.channel_layer.group_discard(old, self.channel_name)
            self.groups_joined.remove(old)
            await self.join_item()

    async def check_periodically(self):
        while True:
            await asyncio.sleep(CHECK_EVERY)
            await self.access_check()

    # Sending -----------------------------------------------------------

    async def send_json(self, data):
        if not self.closed:
            await self.send(text_data=json.dumps(data))

    async def refuse(self, code):
        """Closes: nothing goes out anymore"""
        self.closed = True
        await self.leave()
        if self.check_task not in {None, asyncio.current_task()}:
            self.check_task.cancel()
        await self.close(code=code)
