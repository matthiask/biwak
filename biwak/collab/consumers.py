"""The websocket of a doc edited live (specs/collaboration.md)

Speaks the protocol of y-websocket's provider (``frontend/collab.js``):
Yjs' sync and awareness messages, plus one of ours telling the editor
whether it may type. Whoever is connected with write access holds the
doc's editing marker (``items.editing``: no ticks meanwhile), renewed
with the periodic access check, gone when the connection closes. Every update somebody may make is stored as it
arrives (``LiveUpdate``) and sent to the doc's other editors through the
channel layer; ``Doc.content``, the events and the versions follow on a
debounce (``files.operations.save_live()``). The state lives in the
database, so any number of processes can serve the same doc.
"""

import asyncio
import json
import logging
import secrets
import time

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from pycrdt import (
    Decoder,
    Encoder,
    YMessageType,
    YSyncMessageType,
    create_awareness_message,
    create_sync_message,
    create_update_message,
    handle_sync_message,
    read_message,
)

from biwak.collab import live, ytext
from biwak.items import editing
from biwak.items.models import Item


logger = logging.getLogger(__name__)

# Ours: whether the editor may type (a varuint, 1 or 0) after connecting
# and whenever it changes
MESSAGE_MODE = 100
# The editor asks (the message alone) whether the server has what it typed;
# the answer is the server's state vector as the Yjs clients and their
# clocks (specs/connection.md): the editor clears the copy it keeps in the
# browser once the vector covers its own
MESSAGE_HAVE = 101
QUERY_AWARENESS = 3
EMPTY_UPDATE = b"\x00\x00"
# The doc doesn't exist for the person, or not anymore: like the pages'
# 404; the editor doesn't reconnect (4400-4499)
CLOSE_NOT_FOUND = 4404

# Doc.content follows this long after the last update from the editor, at
# least this often while somebody keeps typing (seconds)
SAVE_AFTER = 3
SAVE_AT_LEAST_EVERY = 30
# Checks whether the person may still see and edit the doc this often
# besides the changes telling the editors (live.check_access()), and
# renews the editing marker (well within ``editing.TTL``)
CHECK_EVERY = 60
# ... and before passing on what others typed or where their cursors are,
# when the last check is older than this (seconds): losing access doesn't
# depend on the one message telling the editors (lost when Redis evicts
# it, or never sent when something changed in the database directly).
# Not before every update: a few queries for every keystroke of everybody.
RECHECK_AFTER = 5

# Limits per connection (**?** values the spec didn't fix): at most the
# first number of messages at once, then the second per second; more are
# dropped. Awareness: every cursor move (typing fast, about 10 a second);
# asking for the others' awareness makes every editor answer; syncing
# loads the whole doc. Updates (typing) aren't limited.
AWARENESS_RATE = (20, 10)
QUERY_AWARENESS_RATE = (2, 0.1)
SYNC_RATE = (3, 0.1)
HAVE_RATE = (2, 1)
# Bytes of an awareness message, of the cursor's JSON in it, and of the
# state vector of a sync (a few bytes per Yjs client that ever edited the
# doc); bigger ones are dropped
MAX_AWARENESS = 4096
MAX_CURSOR = 1024
MAX_STATE_VECTOR = 16384

# The colors of the others' cursors, by person
COLORS = [
    "#d63384",
    "#0d6efd",
    "#198754",
    "#fd7e14",
    "#6f42c1",
    "#20c997",
    "#dc3545",
    "#0dcaf0",
]


def decode_awareness(update):
    """[(client ID, clock, state JSON)] of an awareness update"""
    decoder = Decoder(update)
    return [
        (decoder.read_var_uint(), decoder.read_var_uint(), decoder.read_var_string())
        for _ in range(decoder.read_var_uint())
    ]


def encode_awareness(entries):
    encoder = Encoder()
    encoder.write_var_uint(len(entries))
    for client, clock, state in entries:
        encoder.write_var_uint(client)
        encoder.write_var_uint(clock)
        encoder.write_var_string(state)
    return encoder.to_bytes()


class Bucket:
    """At most ``burst`` at once, then ``rate`` per second (a token
    bucket)"""

    def __init__(self, burst, rate):
        self.burst = self.tokens = burst
        self.rate = rate
        self.at = time.monotonic()

    def take(self):
        now = time.monotonic()
        self.tokens = min(self.burst, self.tokens + (now - self.at) * self.rate)
        self.at = now
        if self.tokens < 1:
            return False
        self.tokens -= 1
        return True


class DocConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.pk = self.scope["url_route"]["kwargs"]["pk"]
        self.user = self.scope["user"]
        session = self.scope.get("session")
        self.session_key = session.session_key if session else None
        self.mode = None
        self.groups_joined = []
        # The ID of the editor's Yjs client (the first it announces), and
        # the one the server gives it for the others: nobody can change or
        # remove the state of somebody else's editor
        self.client = None
        self.public_client = secrets.randbits(32)
        self.clock = 0
        self.save_task = self.check_task = None
        self.dirty_since = None
        self.checked_at = 0
        self.limits = {
            YMessageType.AWARENESS: Bucket(*AWARENESS_RATE),
            QUERY_AWARENESS: Bucket(*QUERY_AWARENESS_RATE),
            YMessageType.SYNC: Bucket(*SYNC_RATE),
            MESSAGE_HAVE: Bucket(*HAVE_RATE),
        }
        self.dropped = set()
        self.marked = False
        await self.accept()
        found = await database_sync_to_async(self._found)()
        if found is None:
            await self.refuse()
            return
        self.mode, self.project_id = found
        self.user_state = {
            "name": self.user.get_short_name(),
            "color": COLORS[self.user.pk % len(COLORS)],
        }
        for group in [
            live.doc_group(self.pk),
            live.project_group(self.project_id),
            live.user_group(self.user.pk),
        ]:
            await self.channel_layer.group_add(group, self.channel_name)
            self.groups_joined.append(group)
        # Once more: a change before joining told nobody
        self.mode = await database_sync_to_async(self._access)()
        if self.mode is None:
            await self.refuse()
            return
        await self.send_mode()
        await self.mark()
        self.check_task = asyncio.create_task(self.check_periodically())

    def _found(self):
        """The mode and the doc's project, or None"""
        if not self.user.is_authenticated:
            return None
        mode = live.access(self.user, self.pk, session_key=self.session_key)
        if mode is None:
            return None
        return mode, live.prepare(self.pk)

    async def disconnect(self, code):
        for task in [self.save_task, self.check_task]:
            if task is not None:
                task.cancel()
        if self.dirty_since is not None:
            await self.save()
        if self.marked:
            await self.unmark()
            # The person's other tabs on the doc set it again
            await self.group_send("doc.left", user=self.user.pk)
        if self.client is not None:
            await self.group_send(
                "doc.awareness",
                update=encode_awareness([(self.public_client, self.clock + 1, "null")]),
            )
        for group in self.groups_joined:
            await self.channel_layer.group_discard(group, self.channel_name)

    # From the editor ---------------------------------------------------

    async def receive(self, text_data=None, bytes_data=None):
        if not bytes_data or self.mode is None:
            return
        try:
            await self.handle(bytes_data)
        except (
            AssertionError,
            IndexError,
            RuntimeError,
            UnicodeDecodeError,
            ValueError,
        ):
            logger.warning(
                "Broken message from user %s for doc %s", self.user.pk, self.pk
            )

    async def handle(self, data):
        kind = data[0]
        if kind == YMessageType.SYNC:
            await self.receive_sync(data[1:])
        elif kind == YMessageType.AWARENESS:
            if len(data) > MAX_AWARENESS:
                self.drop("an awareness message too big")
            elif self.allowed(kind):
                await self.receive_awareness(read_message(data[1:]))
        elif kind == MESSAGE_HAVE and self.allowed(kind):
            await self.send_have()
        elif kind == QUERY_AWARENESS and self.allowed(kind):
            await self.group_send("doc.query_awareness")

    def allowed(self, kind):
        """Within the limits of this kind of message"""
        if self.limits[kind].take():
            return True
        self.drop(f"too many messages of kind {kind}")
        return False

    def drop(self, why):
        """Logs dropping something, once per connection and reason"""
        if why not in self.dropped:
            self.dropped.add(why)
            logger.warning(
                "Dropped %s from user %s for doc %s", why, self.user.pk, self.pk
            )

    async def receive_sync(self, data):
        if data[0] == YSyncMessageType.SYNC_STEP1:
            # What we have that the editor doesn't, then what we have, so
            # that it sends what we don't (typed offline); to who may still
            # see it. It loads the whole doc: limited.
            if len(read_message(data[1:])) > MAX_STATE_VECTOR:
                self.drop("a state vector too big")
                return
            if not self.allowed(YMessageType.SYNC):
                return
            await self.access_check()
            if self.mode is None:
                return
            doc = await database_sync_to_async(live.load)(self.pk)
            await self.send(bytes_data=handle_sync_message(data, doc))
            await self.send(bytes_data=create_sync_message(doc))
            return
        if self.mode != live.WRITE:
            return
        update = read_message(data[1:])
        if update == EMPTY_UPDATE or not ytext.is_valid(update):
            return
        await database_sync_to_async(live.append)(self.pk, update, self.user)
        await self.group_send("doc.update", update=update)
        self.schedule_save()

    async def receive_awareness(self, update):
        """Only the editor's own state (the first it announces) under the
        ID the server gave it, only the cursor, with the name and color of
        the person: nobody passes for somebody else"""
        entries = []
        for client, clock, state in decode_awareness(update):
            if self.client is None:
                self.client = client
            if client != self.client:
                continue
            if state != "null":
                data = json.loads(state)
                if not isinstance(data, dict):
                    continue
                if len(json.dumps(data.get("cursor"))) > MAX_CURSOR:
                    self.drop("a cursor too big")
                    continue
                state = json.dumps(  # noqa: PLW2901
                    {"cursor": data.get("cursor"), "user": self.user_state}
                )
            self.clock = clock
            entries.append((self.public_client, clock, state))
        if entries:
            await self.group_send("doc.awareness", update=encode_awareness(entries))

    # From the channel layer --------------------------------------------

    async def group_send(self, kind, **data):
        await self.channel_layer.group_send(
            live.doc_group(self.pk),
            {
                "type": kind,
                "sender": self.channel_name,
                **data,
            },
        )

    async def recheck(self):
        """Checks access again when the last check is older than
        ``RECHECK_AFTER``; returns whether the session is still open"""
        if asyncio.get_running_loop().time() - self.checked_at >= RECHECK_AFTER:
            await self.access_check()
        return self.mode is not None

    async def doc_update(self, event):
        if event.get("sender") != self.channel_name and await self.recheck():
            await self.send(bytes_data=create_update_message(event["update"]))

    async def doc_awareness(self, event):
        if not await self.recheck():
            return
        # To the sender too: y-websocket reconnects when it hears nothing
        # for 30 seconds, not even its own awareness. Its own state under
        # its own ID: the editor doesn't show itself among the others.
        update = event["update"]
        if event["sender"] == self.channel_name:
            update = encode_awareness([
                (self.client, clock, state)
                for _client, clock, state in decode_awareness(update)
            ])
        await self.send(bytes_data=create_awareness_message(update))

    async def doc_left(self, event):
        if event["sender"] != self.channel_name and event["user"] == self.user.pk:
            await self.mark()

    async def doc_query_awareness(self, event):
        if event["sender"] != self.channel_name and await self.recheck():
            await self.send(bytes_data=bytes([QUERY_AWARENESS]))

    async def access_check(self, event=None):
        """Closes the session when the person can't see the doc anymore,
        tells the editor when it may type or not anymore"""
        if event and event.get("session") and event["session"] == self.session_key:
            # Logged out (the session may not be deleted yet)
            await self.refuse()
            return
        self.checked_at = asyncio.get_running_loop().time()
        mode = await database_sync_to_async(self._access)()
        if mode is None:
            await self.refuse()
            return
        if mode != self.mode:
            self.mode = mode
            await self.send_mode()
        await self.mark()

    async def refuse(self):
        """Closes the session: nothing goes out anymore, the editor doesn't
        reconnect"""
        self.mode = None
        await self.unmark()
        for group in self.groups_joined:
            await self.channel_layer.group_discard(group, self.channel_name)
        self.groups_joined = []
        if self.check_task not in {None, asyncio.current_task()}:
            self.check_task.cancel()
        await self.close(code=CLOSE_NOT_FOUND)

    async def send(self, text_data=None, bytes_data=None, close=False):  # noqa: FBT002, Channels' signature
        if self.mode is None and not close:
            # Closed, or closing
            return
        await super().send(text_data=text_data, bytes_data=bytes_data, close=close)

    def _access(self):
        # The person as they are now: deactivated, a client now
        self.user.refresh_from_db()
        return live.access(self.user, self.pk, session_key=self.session_key)

    async def send_have(self):
        """The state vector of the doc as the server has it now"""
        doc = await database_sync_to_async(live.load)(self.pk)
        clocks = ytext.clocks(doc)
        encoder = Encoder()
        encoder.write_var_uint(MESSAGE_HAVE)
        encoder.write_var_uint(len(clocks))
        for client, clock in clocks.items():
            encoder.write_var_uint(client)
            encoder.write_var_uint(clock)
        await self.send(bytes_data=encoder.to_bytes())

    async def send_mode(self):
        await self.send(
            bytes_data=bytes([MESSAGE_MODE, 1 if self.mode == live.WRITE else 0])
        )

    async def mark(self):
        """Sets or renews the editing marker while the person may type,
        removes it when they may not anymore (specs/editor.md, "Ticking
        while someone edits")"""
        if self.mode == live.WRITE:
            await database_sync_to_async(self._start)()
            self.marked = True
        else:
            await self.unmark()

    def _start(self):
        editing.start(Item.objects.get(pk=self.pk), self.user)

    async def unmark(self):
        if self.marked:
            self.marked = False
            await database_sync_to_async(editing.stop)(self.pk, self.user)

    async def check_periodically(self):
        while True:
            await asyncio.sleep(CHECK_EVERY)
            await self.access_check()

    # Saving ------------------------------------------------------------

    def schedule_save(self):
        now = asyncio.get_running_loop().time()
        if self.dirty_since is None:
            self.dirty_since = now
        delay = min(SAVE_AFTER, max(0, self.dirty_since + SAVE_AT_LEAST_EVERY - now))
        if self.save_task is not None:
            self.save_task.cancel()
        self.save_task = asyncio.create_task(self.save_later(delay))

    async def save_later(self, delay):
        await asyncio.sleep(delay)
        # Not cancelled anymore once saving
        self.save_task = None
        await self.save()

    async def save(self):
        from biwak.files import operations

        self.dirty_since = None
        try:
            await database_sync_to_async(operations.save_live)(self.pk, self.user)
        except Exception:
            logger.exception("Saving doc %s failed", self.pk)
