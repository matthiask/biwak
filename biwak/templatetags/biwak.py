import html

from django import template
from django.conf import settings
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
    return render_markdown(text)


def render_markdown(text, *, absolute=False):
    """``absolute`` for the API and mails: attachment URLs with BASE_URL"""
    tokens = _markdown.parse(str(text or ""))
    _attachment_urls(tokens, absolute=absolute)
    return mark_safe(_markdown.renderer.render(tokens, _markdown.options, {}))


def _attachment_urls(tokens, *, absolute):
    """``attachment:KEY`` (specs/files.md) becomes the download URL; images
    show inline, scaled to the text's width. Whoever reads the text may
    not see the attachment: the download checks."""
    from biwak.files.models import REFERENCE, Attachment

    references = []
    for token in tokens:
        for child in token.children or ():
            attr = {"link_open": "href", "image": "src"}.get(child.type)
            if attr and (match := REFERENCE.fullmatch(child.attrGet(attr) or "")):
                references.append((child, attr, match[1]))
    if not references:
        return
    found = {
        a.key: a
        for a in Attachment.objects.filter(key__in={key for *_, key in references})
    }
    for token, attr, key in references:
        if attachment := found.get(key):
            url = attachment.get_absolute_url()
            token.attrSet(attr, settings.BASE_URL + url if absolute else url)
        else:
            token.attrSet(attr, "#")
        if attr == "src":
            token.attrJoin("class", "wb-attachment-image")
            token.attrSet("loading", "lazy")


@register.filter
def plain(text):
    """The text without Markdown, e.g. for snippets"""
    return " ".join(strip_tags(markdown(text)).split())


@register.filter
def excerpt(text, chars=200):
    """The text as plain text of at most about ``chars`` characters
    (specs/glance.md): Markdown rendered like ``|markdown``, tags
    stripped, whitespace collapsed, cut at a word boundary, "…" added.
    Images and attachments become nothing, links their text. Plain
    ``str``: templates escape it."""
    chars = int(chars)
    rendered = str(render_markdown(text)).replace("</p>", " ").replace("<br>", " ")
    # strip_tags leaves entities; unescape the text (it is escaped again on
    # output) so that "&amp;" doesn't show
    result = " ".join(html.unescape(strip_tags(rendered)).split())
    if len(result) <= chars:
        return result
    cut = result[:chars]
    if not result[chars].isspace():
        # In the middle of a word: back to the last space, if there is one
        cut = cut.rsplit(" ", 1)[0] if " " in cut else cut
    return cut.rstrip() + "…"


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
