from django import template

from biwak.reactions.models import can_react
from biwak.reactions.views import block_context


register = template.Library()


@register.inclusion_tag("reactions/_reactions.html", takes_context=True)
def reactions(context, item, comment=None):
    """The reactions under a to-do or a comment, with the picker. Parts
    with new kinds of items add the tag to their pages and the kind to
    ``REACTABLE``."""
    request = context["request"]
    if not can_react(item, comment):
        return {"hidden": True}
    return block_context(request, item, comment) | {
        "csrf_token": context.get("csrf_token")
    }
