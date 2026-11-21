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
def show_links(context, project):
    """The "Links" section of the project page: the links the person
    sees, with the controls for staff"""
    request = context["request"]
    return {
        "request": request,
        "project": project,
        "links": list(Link.objects.visible_to(request.user).filter(project=project)),
        "can_manage": ops.can_manage_links(request.user),
        "csrf_token": context.get("csrf_token"),
    }
