"""A doc's title is its text's first line (specs/doc-titles.md)"""

import re

from django.utils.translation import gettext as _

from biwak.items.models import Item


HEADING = re.compile(r"^\s{0,3}#{1,6}[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")


def doc_title(text):
    """The first line of ``text`` (the first one with anything in it): a
    heading without its ``#``s, else the line as plain text; cut at a word
    boundary within ``Item.title``'s length, with "…". "Untitled" for an
    empty text."""
    from biwak.templatetags.biwak import excerpt

    limit = Item._meta.get_field("title").max_length
    for line in str(text or "").splitlines():
        if line.strip():
            break
    else:
        return _("Untitled")
    heading = HEADING.match(line)
    # The limit minus the "…" the cut adds
    return excerpt(heading[1] if heading else line, limit - 1) or _("Untitled")


def with_heading(title, content=""):
    """The text of a new doc: ``# title``, an empty line, then ``content``"""
    title = " ".join(str(title).split())
    return f"# {title}\n\n{content or ''}"
