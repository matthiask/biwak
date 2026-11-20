"""SPIKE: pycrdt-websocket's Channels consumer with a permission check"""

from channels.db import database_sync_to_async
from pycrdt import Doc as YDoc, Text
from pycrdt.websocket.django_channels_consumer import YjsConsumer

from biwak.items import operations as ops
from biwak.items.models import Item, Kind


@database_sync_to_async
def _load(user, pk):
    if not user.is_authenticated:
        return None
    item = (
        Item.objects
        .visible_to(user)
        .filter(kind=Kind.DOC, pk=pk)
        .select_related("doc")
        .first()
    )
    if item is None:
        return None
    return item, ops.can_change(user, item)


class DocConsumer(YjsConsumer):
    def make_room_name(self):
        return f"doc-{self.scope['url_route']['kwargs']['pk']}"

    async def make_ydoc(self):
        ydoc = YDoc()
        ydoc["content"] = Text(self.item.doc.content)
        return ydoc

    async def connect(self):
        found = await _load(self.scope["user"], self.scope["url_route"]["kwargs"]["pk"])
        if found is None:
            await self.close(code=4404)
            return
        self.item, self.writable = found
        await super().connect()

    async def receive(self, text_data=None, bytes_data=None):
        if (
            not self.writable
            and bytes_data
            and bytes_data[0] == 0
            and bytes_data[1] != 0
        ):
            return
        await super().receive(text_data, bytes_data)
