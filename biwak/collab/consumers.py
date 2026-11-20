"""The websocket of a doc edited live (specs/collaboration.md)

Speaks the protocol of y-websocket's provider (``frontend/collab.js``):
Yjs' sync and awareness messages, plus one of ours telling the editor
whether it may type. Every update somebody may make is stored as it
arrives (``LiveUpdate``) and sent to the doc's other editors through the
channel layer; ``Doc.content``, the events and the versions follow on a
debounce (``files.operations.save_live()``). The state lives in the
database, so any number of processes can serve the same doc.
"""

import asyncio
import json
import logging

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


logger = logging.getLogger(__name__)

# Ours: whether the editor may type (a varuint, 1 or 0) after connecting
# and whenever it changes
MESSAGE_MODE = 100
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
# besides the changes telling the editors (live.check_access())
CHECK_EVERY = 60

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


class DocConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.pk = self.scope["url_route"]["kwargs"]["pk"]
        self.user = self.scope["user"]
        session = self.scope.get("session")
        self.session_key = session.session_key if session else None
        self.mode = None
        self.groups_joined = []
        self.client = None
        self.clock = 0
        self.save_task = self.check_task = None
        self.dirty_since = None
        await self.accept()
        found = await database_sync_to_async(self._found)()
        if found is None:
            await self.refuse()
            return
        self.mode, project = found
        self.user_state = {
            "name": self.user.get_short_name(),
            "color": COLORS[self.user.pk % len(COLORS)],
        }
        for group in [
            live.doc_group(self.pk),
            live.project_group(project),
            live.user_group(self.user.pk),
        ]:
            await self.channel_layer.group_add(group, self.channel_name)
            self.groups_joined.append(group)
        await self.send_mode()
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
        if self.client is not None:
            await self.group_send(
                "doc.awareness",
                update=encode_awareness([(self.client, self.clock + 1, "null")]),
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
            await self.receive_awareness(read_message(data[1:]))
        elif kind == QUERY_AWARENESS:
            await self.group_send("doc.query_awareness")

    async def receive_sync(self, data):
        if data[0] == YSyncMessageType.SYNC_STEP1:
            # What we have that the editor doesn't, then what we have, so
            # that it sends what we don't (typed offline)
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
        """Only the editor's own state (the first it announces), with the
        name and color of the person: nobody passes for somebody else"""
        entries = []
        for client, clock, state in decode_awareness(update):
            if self.client is None:
                self.client = client
            if client != self.client:
                continue
            self.clock = clock
            if state != "null":
                data = json.loads(state)
                data["user"] = self.user_state
                state = json.dumps(data)  # noqa: PLW2901
            entries.append((client, clock, state))
        if entries:
            await self.group_send("doc.awareness", update=encode_awareness(entries))

    # From the channel layer --------------------------------------------

    async def group_send(self, kind, **data):
        await self.channel_layer.group_send(
            live.doc_group(self.pk),
            {"type": kind, "sender": self.channel_name, **data},
        )

    async def doc_update(self, event):
        if event.get("sender") != self.channel_name:
            await self.send(bytes_data=create_update_message(event["update"]))

    async def doc_awareness(self, event):
        # To the sender too: y-websocket reconnects when it hears nothing
        # for 30 seconds, not even its own awareness
        await self.send(bytes_data=create_awareness_message(event["update"]))

    async def doc_query_awareness(self, event):
        if event["sender"] != self.channel_name:
            await self.send(bytes_data=bytes([QUERY_AWARENESS]))

    async def access_check(self, event=None):
        """Closes the session when the person can't see the doc anymore,
        tells the editor when it may type or not anymore"""
        mode = await database_sync_to_async(self._access)()
        if mode is None:
            await self.refuse()
        elif mode != self.mode:
            self.mode = mode
            await self.send_mode()

    async def refuse(self):
        """Closes the session: nothing goes out anymore, the editor doesn't
        reconnect"""
        self.mode = None
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

    async def send_mode(self):
        await self.send(
            bytes_data=bytes([MESSAGE_MODE, 1 if self.mode == live.WRITE else 0])
        )

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
