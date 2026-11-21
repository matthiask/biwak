"""Telling the open pages that something changed (specs/lantern.md)

Never content: only "this item changed" with the IDs and the kind of
change, after the commit. The pages fetch what changed through the normal
views, with their permission checks (``frontend/live.js``).

A page showing an item joins the item's group for staff or for clients
(``consumers.LiveConsumer`` checks that the person sees the item). What
happened while the item wasn't visible to clients goes to the staff group
only: a client's page never hears of an internal change, not even that
there was one.
"""

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction


def item_group(pk, *, clients):
    return f"live-item-{pk}-{'clients' if clients else 'staff'}"


def person_group(pk):
    """The lantern's count of a person's tabs"""
    return f"live-person-{pk}"


def _send(groups, message):
    layer = get_channel_layer()
    if layer is None:
        return
    for group in groups:
        async_to_sync(layer.group_send)(group, message)


def changed(item, *, action, actor=None, visible=None, also=()):
    """After the commit: the item changed (``action``: what happened, an
    event's action or e.g. "reordered"), for the pages showing it and its
    parent (a to-do's list, an answer's question), and ``also`` (IDs of
    more items, e.g. the list a to-do left). ``visible``: whether it
    happened while clients saw the item (an event's
    ``is_client_visible``); else the item's visibility now. ``actor``'s
    own pages aren't told: their change is on them already."""
    if visible is None:
        visible = item.is_client_visible
    pks = {item.pk, item.parent_id, *also} - {None}
    message = {
        "type": "live.changed",
        "item": item.pk,
        "action": str(action),
        "actor": actor.pk if actor is not None else None,
    }

    def send():
        for pk in pks:
            _send(
                [item_group(pk, clients=False)]
                + ([item_group(pk, clients=True)] if visible else []),
                message | {"watched": pk},
            )

    transaction.on_commit(send, robust=True)


def lantern_changed(people):
    """After the commit: the lantern of these people (IDs) changed, their
    tabs fetch the count"""
    people = set(people)
    if people:
        transaction.on_commit(
            lambda: _send(
                [person_group(pk) for pk in people], {"type": "lantern.changed"}
            ),
            robust=True,
        )
