from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from biwak.forms import next_url
from biwak.items.models import Comment, Item
from biwak.items.views import item_for
from biwak.reactions import operations as ops
from biwak.reactions.emoji import MAX_LENGTH, QUICK


def block_context(request, item, comment=None, *, error=""):
    """What ``reactions/_reactions.html`` shows: the reactions of the item
    or comment, the picker and the text field"""
    return {
        "request": request,
        "item": item,
        "comment": comment,
        "dom_id": f"reactions-{'comment' if comment else 'item'}-{(comment or item).pk}",
        "url": reaction_url(item, comment),
        "reactions": ops.summary(item, comment, request.user),
        "quick": QUICK,
        "max_length": MAX_LENGTH,
        "error": error,
    }


def reaction_url(item, comment=None):
    if comment:
        return reverse("comment_reactions", args=[comment.pk])
    return reverse("item_reactions", args=[item.pk])


def comment_for(request, pk):
    """The comment if the person may see its item, else 404"""
    return get_object_or_404(
        Comment.objects.filter(
            item__in=Item.objects.visible_to(request.user)
        ).select_related("item", "item__project"),
        pk=pk,
    )


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
