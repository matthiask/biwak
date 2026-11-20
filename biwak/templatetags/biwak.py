import html
import re

from django import template
from django.conf import settings
from django.utils.html import escape, format_html, strip_tags
from django.utils.safestring import mark_safe
from django.utils.translation import gettext
from markdown_it import MarkdownIt
from markdown_it.token import Token


register = template.Library()

# Texts are stored as Markdown (specs/core.md): no HTML, links clickable
_markdown = MarkdownIt("commonmark", {"html": False, "linkify": True, "breaks": True})
_markdown.enable(["linkify", "strikethrough", "table"])

_PERSON = re.compile(r"person:(\d+)")


def _mentions(state):
    """Mentions (``[@Ada](person:12)``, biwak/activity/mentions.py) are
    links to ``person:``: shown with the current name of people who can see
    the item (``env["names"]``), as plain text otherwise"""
    names = state.env.get("names") or {}
    for block in state.tokens:
        if block.type != "inline" or not block.children:
            continue
        children, result = block.children, []
        index = 0
        while index < len(children):
            token = children[index]
            match = token.type == "link_open" and _PERSON.fullmatch(
                token.attrGet("href") or ""
            )
            if not match:
                result.append(token)
                index += 1
                continue
            end = index + 1
            while children[end].type != "link_close":
                end += 1
            label = "".join(t.content for t in children[index + 1 : end])
            name = names.get(int(match[1]))
            mention = Token("html_inline", "", 0)
            mention.content = (
                f'<span class="wb-mention">@{escape(name)}</span>'
                if name
                else escape(f"@{label.removeprefix('@')}")
            )
            result.append(mention)
            index = end + 1
        block.children = result


_markdown.core.ruler.push("mentions", _mentions)


@register.filter
def markdown(text, item=None):
    """Markdown as HTML; mentions with current names when the item they're
    in is given (``{{ comment.content|markdown:item }}``)"""
    return render_markdown(text, item)


@register.filter
def mail_markdown(text, item=None):
    """For mails: like ``markdown``, attachment URLs with BASE_URL"""
    return render_markdown(text, item, absolute=True)


def render_markdown(text, item=None, *, absolute=False):
    """``absolute`` for the API and mails: attachment URLs with BASE_URL"""
    from biwak.activity.mentions import mentioned_ids, visible_names

    text = str(text or "")
    names = visible_names(item, mentioned_ids(text)) if item is not None else {}
    env = {"names": names}
    tokens = _markdown.parse(text, env)
    _attachment_urls(tokens, absolute=absolute)
    return mark_safe(_markdown.renderer.render(tokens, _markdown.options, env))


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
def item_title(item):
    """An item's title with the mentions as ``@`` and current names"""
    from biwak.activity.mentions import plain as plain_mentions

    return plain_mentions(item.title, item)


@register.filter
def title_text(title):
    """A stored title (e.g. an event's) with the mentions as ``@`` and their
    labels, without looking anybody up"""
    from biwak.activity.mentions import plain as plain_mentions

    return plain_mentions(title)


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


@register.inclusion_tag("activity/_item_notifications.html", takes_context=True)
def item_notifications(context, item):
    """The person's level for an item, next to its subscribe button"""
    from biwak.activity.views import item_level_context

    user = context["request"].user
    return {"item": item, "csrf_token": context.get("csrf_token")} | (
        item_level_context(user, item)
    )
