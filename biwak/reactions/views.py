from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from biwak.forms import next_url
from biwak.items.models import Item
from biwak.items.views import comment_for, item_for
from biwak.reactions import operations as ops
from biwak.reactions.emoji import MAX_LENGTH, QUICK
from biwak.reactions.models import Reaction


def block_context(request, item, comment=None, *, error=""):
    """What ``reactions/_reactions.html`` shows: the reactions of the item
    or comment, the picker and the text field"""
    return {
        "request": request,
        "item": item,
        "comment": comment,
        "dom_id": f"reactions-{'comment' if comment else 'item'}-{(comment or item).pk}",
        "url": reaction_url(item, comment),
        "target": comment or item,
        "remove_url_name": "comment_reaction_remove"
        if comment
        else "item_reaction_remove",
        "reactions": ops.summary(item, comment, request.user),
        "quick": QUICK,
        "max_length": MAX_LENGTH,
        "error": error,
    }


def reaction_url(item, comment=None):
    if comment:
        return reverse("comment_reactions", args=[comment.pk])
    return reverse("item_reactions", args=[item.pk])


def _toggle(request, item, comment=None):
    error = ""
    try:
        ops.toggle_reaction(
            request.user,
            request.POST.get("content", ""),
            item=None if comment else item,
            comment=comment,
        )
    except ValidationError as exc:
        error = " ".join(exc.messages)
    if request.headers.get("HX-Request"):
        # Only the block swaps itself
        item = Item.objects.get(pk=item.pk)
        return render(
            request,
            "reactions/_reactions.html",
            block_context(request, item, comment, error=error),
        )
    if error:
        messages.error(request, error)
    anchor = f"#comment-{comment.pk}" if comment else ""
    return redirect(next_url(request) or f"{item.get_absolute_url()}{anchor}")


@require_POST
def item_reactions(request, pk):
    """Adds the reaction (``content``) to the item, or removes it again"""
    item = item_for(request, pk)
    return _toggle(request, item)


@require_POST
def comment_reactions(request, pk):
    comment = comment_for(request, pk)
    return _toggle(request, comment.item, comment)


def _confirm_removal(request, item, comment=None):
    """Without JavaScript clicking one's own reaction lands here: a form
    removing it"""
    content = request.GET.get("content", "")
    mine = Reaction.objects.filter(
        item=item, comment=comment, user=request.user, content=content
    )
    if not mine.exists():
        return redirect(item.get_absolute_url())
    return render(
        request,
        "reactions/confirm_remove.html",
        {
            "content": content,
            "url": reaction_url(item, comment),
            "cancel": next_url(request)
            or f"{item.get_absolute_url()}{f'#comment-{comment.pk}' if comment else ''}",
        },
    )


def item_reaction_remove(request, pk):
    return _confirm_removal(request, item_for(request, pk))


def comment_reaction_remove(request, pk):
    comment = comment_for(request, pk)
    return _confirm_removal(request, comment.item, comment)
