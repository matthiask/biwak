from django import template

from biwak.bookmarks import operations as ops
from biwak.bookmarks.models import Link
from biwak.items.models import Item


register = template.Library()


@register.inclusion_tag("bookmarks/_bookmark_button.html", takes_context=True)
def bookmark_button(context, target):
    """The bookmark icon button on the page of an item or a project"""
    user = context["request"].user
    is_item = isinstance(target, Item)
    return {
        "request": context["request"],
        "target": target,
        "is_item": is_item,
        "is_bookmarked": ops.is_bookmarked(
            user, **({"item": target} if is_item else {"project": target})
        ),
    }


@register.inclusion_tag("bookmarks/_links.html", takes_context=True)
def show_links(context, target):
    """The links of a project (at the top of its page) or an item (under
    its title) the person sees, with the forms for staff"""
    request = context["request"]
    is_item = isinstance(target, Item)
    found = Link.objects.visible_to(request.user)
    if is_item:
        found = found.filter(item=target)
    else:
        found = found.filter(project=target, item=None)
    can_manage = ops.can_manage_links(request.user)
    return {
        "request": request,
        "target": target,
        "is_item": is_item,
        "links": list(found),
        "can_manage": can_manage,
        "csrf_token": context.get("csrf_token"),
    }
