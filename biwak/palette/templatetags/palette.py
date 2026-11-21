from django import template
from django.urls import reverse
from django.utils.translation import gettext as _

from biwak.palette import actions


register = template.Library()


@register.inclusion_tag("palette/_palette.html", takes_context=True)
def palette(context):
    """The command palette's dialog and the page's actions as JSON
    (specs/keyboard.md); only for people who are logged in"""
    request = context["request"]
    return {
        "data": {
            "actions": actions.for_page(request, context),
            "shortcuts": request.user.keyboard_shortcuts,
            "jumps_url": reverse("palette"),
            "search_url": reverse("search"),
            "texts": {
                "search_for": _("Search for “%s”"),
                "recent": _("Visited recently"),
                "bookmarks": _("Bookmarks"),
                "actions": _("Actions"),
                "jumps": _("Go to"),
                "archived": _("Archived"),
                "clients": _("For clients"),
                "no_page_shortcuts": _("This page has none of its own."),
                "copied": _("Link copied."),
                "failed": _("That didn't work. Please try again."),
            },
        }
    }
