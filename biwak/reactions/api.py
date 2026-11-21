"""Reactions (specs/reactions.md): anybody who sees the item reacts, to
to-dos and comments; everybody removes only their own."""

from ninja import Router, Schema, Status

from biwak.items.models import Item
from biwak.items.views import comment_for, item_for
from biwak.reactions import operations as ops
from biwak.reactions.operations import prefetch
from biwak.reactions.schemas import ReactionOut, reactions_out


router = Router(tags=["reactions"])


class ReactionIn(Schema):
    content: str


def _target(request, item_id=None, comment_id=None):
    """``(item, comment)`` as the operations want them, 404 for what the
    person can't see; the item's reactions loaded"""
    if comment_id is not None:
        comment = comment_for(request, comment_id)
        item = comment.item
    else:
        comment, item = None, item_for(request, item_id)
    prefetch(item)
    return item, comment


def _show(request, item, comment):
    item = Item.objects.get(pk=item.pk)
    prefetch(item)
    return reactions_out(item, comment, request.user)


def _add(request, data, item, comment):
    ops.add_reaction(
        request.user, data.content, item=None if comment else item, comment=comment
    )
    return Status(201, _show(request, item, comment))


def _remove(request, data, item, comment):
    ops.remove_reaction(
        request.user, data.content, item=None if comment else item, comment=comment
    )
    return _show(request, item, comment)


@router.get("items/{item_id}/reactions/", response=list[ReactionOut])
def item_reactions(request, item_id: int):
    item, comment = _target(request, item_id=item_id)
    return reactions_out(item, comment, request.user)


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
    item, comment = _target(request, comment_id=comment_id)
    return reactions_out(item, comment, request.user)


@router.post("comments/{comment_id}/reactions/", response={201: list[ReactionOut]})
def comment_reaction_add(request, comment_id: int, data: ReactionIn):
    return _add(request, data, *_target(request, comment_id=comment_id))


@router.delete("comments/{comment_id}/reactions/", response=list[ReactionOut])
def comment_reaction_remove(request, comment_id: int, data: ReactionIn):
    return _remove(request, data, *_target(request, comment_id=comment_id))
