"""Reactions (specs/reactions.md): anybody who sees the item reacts, to
to-dos, comments and to-dos getting completed (their ``completed``
events); everybody removes only their own."""

from ninja import Router, Schema, Status

from biwak.items.views import comment_for, item_for
from biwak.reactions import operations as ops
from biwak.reactions.schemas import ReactionOut, reactions_out
from biwak.reactions.views import completion_for


router = Router(tags=["reactions"])


class ReactionIn(Schema):
    content: str


def _target(request, item_id=None, comment_id=None, event_id=None):
    """``(item, comment, event)`` as the operations want them, 404 for what
    the person can't see"""
    if comment_id is not None:
        comment = comment_for(request, comment_id)
        return comment.item, comment, None
    if event_id is not None:
        event = completion_for(request, event_id)
        return event.item, None, event
    return item_for(request, item_id), None, None


def _show(request, item, comment, event):
    """The reactions as they are now: ``summary()`` loads them (one query
    for one item)"""
    return reactions_out(item, comment, request.user, event)


def _change(change, request, data, item, comment, event):
    change(
        request.user,
        data.content,
        item=None if comment or event else item,
        comment=comment,
        event=event,
    )


def _add(request, data, item, comment, event):
    _change(ops.add_reaction, request, data, item, comment, event)
    return Status(201, _show(request, item, comment, event))


def _remove(request, data, item, comment, event):
    _change(ops.remove_reaction, request, data, item, comment, event)
    return _show(request, item, comment, event)


@router.get("items/{item_id}/reactions/", response=list[ReactionOut])
def item_reactions(request, item_id: int):
    return _show(request, *_target(request, item_id=item_id))


@router.post("items/{item_id}/reactions/", response={201: list[ReactionOut]})
def item_reaction_add(request, item_id: int, data: ReactionIn):
    """Idempotent; returns the item's reactions"""
    return _add(request, data, *_target(request, item_id=item_id))


@router.delete("items/{item_id}/reactions/", response=list[ReactionOut])
def item_reaction_remove(request, item_id: int, data: ReactionIn):
    """Removes your own reaction with this content; returns the item's
    reactions"""
    return _remove(request, data, *_target(request, item_id=item_id))


@router.get("comments/{comment_id}/reactions/", response=list[ReactionOut])
def comment_reactions(request, comment_id: int):
    return _show(request, *_target(request, comment_id=comment_id))


@router.post("comments/{comment_id}/reactions/", response={201: list[ReactionOut]})
def comment_reaction_add(request, comment_id: int, data: ReactionIn):
    return _add(request, data, *_target(request, comment_id=comment_id))


@router.delete("comments/{comment_id}/reactions/", response=list[ReactionOut])
def comment_reaction_remove(request, comment_id: int, data: ReactionIn):
    return _remove(request, data, *_target(request, comment_id=comment_id))


@router.get("events/{event_id}/reactions/", response=list[ReactionOut])
def event_reactions(request, event_id: int):
    """Reactions to a to-do getting completed: its ``completed`` event (the
    feed's events have the IDs)"""
    return _show(request, *_target(request, event_id=event_id))


@router.post("events/{event_id}/reactions/", response={201: list[ReactionOut]})
def event_reaction_add(request, event_id: int, data: ReactionIn):
    return _add(request, data, *_target(request, event_id=event_id))


@router.delete("events/{event_id}/reactions/", response=list[ReactionOut])
def event_reaction_remove(request, event_id: int, data: ReactionIn):
    return _remove(request, data, *_target(request, event_id=event_id))
