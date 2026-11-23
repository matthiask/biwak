from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from biwak.activity.models import Action, Event
from biwak.forms import next_url
from biwak.items.models import Item, Kind
from biwak.items.views import comment_for, item_for
from biwak.reactions import operations as ops
from biwak.reactions.emoji import MAX_LENGTH, QUICK
from biwak.reactions.models import Reaction


def completion_for(request, pk):
    """A to-do's ``completed`` event if the person sees it, else 404: its
    to-do through ``Item.objects.visible_to()``, and for clients only
    while they saw it (``Event.objects.visible_to()``)"""
    return get_object_or_404(
        Event.objects
        .visible_to(request.user)
        .filter(action=Action.COMPLETED, item__kind=Kind.TODO)
        .select_related("item", "item__project", "actor"),
        pk=pk,
    )


def _kind(comment, event):
    return "comment" if comment else "event" if event else "item"


def anchor(comment=None, event=None):
    """Where on the item's page the thing reacted to is"""
    if comment:
        return f"#comment-{comment.pk}"
    if event:
        return f"#reactions-event-{event.pk}"
    return ""


def block_context(request, item, comment=None, *, event=None, error=""):
    """What ``reactions/_reactions.html`` shows: the reactions of the item,
    a comment or a completing, the picker and the text field"""
    kind = _kind(comment, event)
    target = comment or event or item
    return {
        "request": request,
        "item": item,
        "comment": comment,
        "dom_id": f"reactions-{kind}-{target.pk}",
        "url": reaction_url(item, comment, event),
        "target": target,
        "remove_url_name": f"{kind}_reaction_remove",
        "reactions": (reactions := ops.summary(item, comment, request.user, event)),
        # Marked in the picker: choosing one again keeps it
        "mine": {entry["content"] for entry in reactions if entry["mine"]},
        "quick": QUICK,
        "max_length": MAX_LENGTH,
        "error": error,
    }


def reaction_url(item, comment=None, event=None):
    if comment:
        return reverse("comment_reactions", args=[comment.pk])
    if event:
        return reverse("event_reactions", args=[event.pk])
    return reverse("item_reactions", args=[item.pk])


def _toggle(request, item, comment=None, event=None):
    error = ""
    # ``action``: "add" (the picker and others' pills: choosing a reaction
    # one already has keeps it) or "remove" (one's own pill, after asking);
    # without it the same reaction again removes it, as the API did first
    change = {
        "add": ops.add_reaction,
        "remove": ops.remove_reaction,
    }.get(request.POST.get("action"), ops.toggle_reaction)
    try:
        change(
            request.user,
            request.POST.get("content", ""),
            item=None if comment or event else item,
            comment=comment,
            event=event,
        )
    except ValidationError as exc:
        error = " ".join(exc.messages)
    if request.headers.get("HX-Request"):
        # Only the block swaps itself
        item = Item.objects.get(pk=item.pk)
        return render(
            request,
            "reactions/_reactions.html",
            block_context(request, item, comment, event=event, error=error),
        )
    if error:
        messages.error(request, error)
    return redirect(
        next_url(request) or f"{item.get_absolute_url()}{anchor(comment, event)}"
    )


@require_POST
def item_reactions(request, pk):
    """Adds the reaction (``content``) to the item, or removes it again"""
    item = item_for(request, pk)
    return _toggle(request, item)


@require_POST
def comment_reactions(request, pk):
    comment = comment_for(request, pk)
    return _toggle(request, comment.item, comment)


@require_POST
def event_reactions(request, pk):
    """Reactions to a to-do getting completed (specs/reactions.md)"""
    event = completion_for(request, pk)
    return _toggle(request, event.item, event=event)


def _confirm_removal(request, item, comment=None, event=None):
    """Without JavaScript clicking one's own reaction lands here: a form
    removing it"""
    content = request.GET.get("content", "")
    mine = Reaction.objects.filter(
        item=item, comment=comment, event=event, user=request.user, content=content
    )
    if not mine.exists():
        return redirect(item.get_absolute_url())
    return render(
        request,
        "reactions/confirm_remove.html",
        {
            "content": content,
            "url": reaction_url(item, comment, event),
            "cancel": next_url(request)
            or f"{item.get_absolute_url()}{anchor(comment, event)}",
        },
    )


def item_reaction_remove(request, pk):
    return _confirm_removal(request, item_for(request, pk))


def comment_reaction_remove(request, pk):
    comment = comment_for(request, pk)
    return _confirm_removal(request, comment.item, comment)


def event_reaction_remove(request, pk):
    event = completion_for(request, pk)
    return _confirm_removal(request, event.item, event=event)
