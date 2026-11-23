"""HTML to Markdown, one converter for the importer (Basecamp's rich text,
``biwak/importer/convert.py``) and for pasting rich text into a Markdown
field (``from_clipboard()``, specs/editor.md).

Pasted HTML is whatever the clipboard holds (a web page, a mail, Word,
Google Docs): bold, emphasis, links, headings, lists, task lists, quotes,
code and tables become Markdown, everything else plain text. No colors,
fonts or images from other sites, no links but http(s) and mailto.
"""

import re
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup, Comment
from markdownify import MarkdownConverter


class Converter(MarkdownConverter):
    """Markdown the way Biwak writes it: ATX headings, "-" bullets, task
    lists"""

    def __init__(self, **options):
        super().__init__(heading_style="ATX", bullets="-", **options)

    def convert_li(self, el, text, parent_tags):
        markdown = super().convert_li(el, text, parent_tags)
        box = _checkbox(el)
        if box is None:
            return markdown
        mark = "[x] " if box.has_attr("checked") else "[ ] "
        return re.sub(
            r"^(\s*(?:[-*+]|\d+\.) )\s*", lambda m: m[1] + mark, markdown, count=1
        )


def _checkbox(li):
    """The checkbox of a task list item: GitHub's and our own are children
    of the item (or of its paragraph or label)"""
    for child in li.children:
        if getattr(child, "name", None) == "input" and child.get("type") == "checkbox":
            return child
        if getattr(child, "name", None) in {"p", "label", "div"}:
            for grandchild in child.children:
                if (
                    getattr(grandchild, "name", None) == "input"
                    and grandchild.get("type") == "checkbox"
                ):
                    return grandchild
    return None


def tidy(text):
    """No trailing spaces (a line break is one already), no stacks of blank
    lines, no outer blank lines"""
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# Clipboard HTML ------------------------------------------------------------

_DROPPED = [
    "head",
    "script",
    "style",
    "template",
    "noscript",
    "meta",
    "link",
    "title",
    "img",
    "picture",
    "svg",
    "canvas",
    "iframe",
    "object",
    "embed",
    "video",
    "audio",
    "form",
    "button",
    "select",
    "textarea",
]
# Block elements markdownify doesn't know: paragraphs of their own
_BLOCKS = [
    "section",
    "article",
    "header",
    "footer",
    "main",
    "nav",
    "aside",
    "address",
    "figure",
    "figcaption",
    "center",
    "fieldset",
    "dl",
    "dt",
    "dd",
    "details",
    "summary",
]
_MONOSPACE = re.compile(r"mono|courier|consolas|menlo|source code", re.IGNORECASE)
_BOLD = re.compile(r"font-weight:\s*(bold|bolder|[6-9]00)\b", re.IGNORECASE)
_PLAIN_WEIGHT = re.compile(r"font-weight:\s*(normal|[1-5]00)\b", re.IGNORECASE)
_ITALIC = re.compile(r"font-style:\s*italic", re.IGNORECASE)
_STRUCK = re.compile(r"text-decoration[^;]*line-through", re.IGNORECASE)
_SAFE_LINK = re.compile(r"(https?://|mailto:)", re.IGNORECASE)


def _styled(soup, span):
    """Google Docs and mail clients style spans instead of using ``b``:
    their bold, italic, strikethrough and monospace become tags"""
    style = span.get("style", "")
    tags = []
    if _BOLD.search(style):
        tags.append("strong")
    if _ITALIC.search(style):
        tags.append("em")
    if _STRUCK.search(style):
        tags.append("del")
    if _MONOSPACE.search(style.split("font-family:")[-1].split(";")[0]) and (
        "font-family" in style
    ):
        tags.append("code")
    if not tags:
        span.unwrap()
        return
    span.name = tags[0]
    span.attrs = {}
    for name in tags[1:]:
        inner = soup.new_tag(name)
        inner.extend(list(span.contents))
        span.append(inner)
        span = inner


def _link(a):
    href = (a.get("href") or "").strip()
    # Google Docs and others send links through a redirect
    parts = urlsplit(href)
    if parts.netloc.endswith("google.com") and parts.path == "/url":
        href = (parse_qs(parts.query).get("q") or [href])[0]
    if _SAFE_LINK.match(href):
        a.attrs = {"href": href}
    else:
        a.unwrap()


def _clean(soup):
    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()
    for tag in soup.find_all(_DROPPED):
        tag.decompose()
    for tag in soup.find_all("input"):
        if tag.get("type") != "checkbox":
            tag.decompose()
    for span in soup.find_all("span"):
        _styled(soup, span)
    # Google Docs wraps everything in <b style="font-weight:normal">
    for tag in soup.find_all(["b", "strong", "i", "em"]):
        if _PLAIN_WEIGHT.search(tag.get("style", "")) or (
            tag.get("id", "").startswith("docs-internal-guid")
        ):
            tag.unwrap()
    for a in soup.find_all("a"):
        _link(a)
    for tag in soup.find_all(_BLOCKS):
        tag.name = "div"
    # A table's header is its first row, if it has no header cells
    for table in soup.find_all("table"):
        if table.find("th") is None and (row := table.find("tr")):
            for cell in row.find_all("td", recursive=False):
                cell.name = "th"


def from_clipboard(html):
    """Markdown from the HTML of the clipboard"""
    if not html or not html.strip():
        return ""
    soup = BeautifulSoup(html, "html.parser")
    _clean(soup)
    return tidy(Converter().convert_soup(soup))
