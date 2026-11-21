"""Basecamp's rich text (HTML) to Markdown (specs/import-basecamp.md)

Mentions (``<bc-attachment content-type="application/vnd.basecamp.mention">``)
become ``[@Name](person:ID)``, embedded files ``![name](attachment:KEY)`` or
``[name](attachment:KEY)``; what the callbacks of ``Resolver`` don't know
stays readable text. Links to other Basecamp recordings are rewritten by
``Resolver.link()``.
"""

from bs4 import BeautifulSoup

from biwak.htmlmarkdown import Converter, tidy


MENTION = "application/vnd.basecamp.mention"


class Resolver:
    """What the converter asks the importer; the defaults keep texts as
    they are"""

    def mention(self, sgid, label):
        """The Markdown of a mention, or None"""

    def attachment(self, element):
        """The Markdown of an embedded file (``element``: the
        ``bc-attachment`` tag), or None"""

    def link(self, href):
        """The URL a link should point to"""
        return href


class _Converter(Converter):
    def __init__(self, resolver, **options):
        super().__init__(**options)
        self.resolver = resolver

    def convert_bc_attachment(self, el, text, parent_tags):
        if el.get("content-type") == MENTION:
            caption = el.find("figcaption")
            label = caption.get_text(strip=True) if caption else ""
            found = self.resolver.mention(el.get("sgid", ""), label)
            return found or (f"@{label}" if label else "")
        found = self.resolver.attachment(el)
        if found:
            return found
        # Unknown file: a link if Basecamp gave one, else its name
        name = el.get("filename") or el.get("caption") or ""
        href = el.get("href") or el.get("url")
        if href and name:
            return f"[{name}]({href})"
        return name

    def convert_a(self, el, text, parent_tags):
        if el.get("href"):
            el["href"] = self.resolver.link(el["href"])
        return super().convert_a(el, text, parent_tags)


def to_markdown(html, resolver=None):
    """Markdown from Basecamp's HTML"""
    if not html or not html.strip():
        return ""
    soup = BeautifulSoup(html, "html.parser")
    # Basecamp writes paragraphs as divs
    for div in soup.find_all("div"):
        div.name = "p"
    return tidy(_Converter(resolver or Resolver()).convert_soup(soup))
