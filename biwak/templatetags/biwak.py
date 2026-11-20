from django import template
from django.utils.html import format_html, strip_tags
from django.utils.safestring import mark_safe
from django.utils.translation import gettext
from markdown_it import MarkdownIt


register = template.Library()

# Texts are stored as Markdown (specs/core.md): no HTML, links clickable
_markdown = MarkdownIt("commonmark", {"html": False, "linkify": True, "breaks": True})
_markdown.enable(["linkify", "strikethrough", "table"])


@register.filter
def markdown(text):
    return mark_safe(_markdown.render(str(text or "")))


@register.filter
def plain(text):
    """The text without Markdown, e.g. for snippets"""
    return " ".join(strip_tags(markdown(text)).split())


@register.simple_tag
def icon(name):
    """A Bootstrap Icon (frontend/styles/icons.css lists those in use),
    hidden from screen readers: the button's label or title says it"""
    return format_html('<i class="bi bi-{}" aria-hidden="true"></i>', name)


@register.simple_tag
def client_badge(item):
    """The bright badge on everything visible to clients (specs/access.md)"""
    if not item.is_client_visible:
        return ""
    return format_html(
        '<span class="badge wb-client-badge" title="{}">{}</span>',
        gettext("Clients can see this"),
        gettext("Clients"),
    )
