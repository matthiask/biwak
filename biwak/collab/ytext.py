"""A doc's text as a Yjs document (pycrdt), shared with the browsers' rich
editor (``frontend/editor/live.js``): y-prosemirror's ``Y.XmlFragment`` of
the editor's document (specs/rich-editor.md, "Live docs"), read and written
here through ``biwak.richtext``. ``Doc.content`` stays Markdown: written
by our serializer, which writes what the browser's would, keeping the old
text where the document didn't change."""

from pycrdt import Decoder, Doc

from biwak.richtext import diff
from biwak.richtext.parse import parse
from biwak.richtext.preserve import to_markdown
from biwak.richtext.ydoc import FRAGMENT, to_ydoc
from biwak.text import line_breaks


__all__ = ["FRAGMENT"]


def ydoc(state=b"", updates=()):
    """A Yjs document from a state and the updates after it"""
    doc = Doc()
    for update in [state, *updates]:
        if update:
            doc.apply_update(bytes(update))
    return doc


def document(doc):
    """The editor's document (``biwak.richtext.tree``)"""
    return diff.document(doc)


def text(doc, old=""):
    """The document as Markdown; ``old``, the text it was made from (the
    stored content), is kept where nothing changed"""
    return to_markdown(document(doc), line_breaks(old or ""))


def means(doc, content):
    """Whether the document is what ``content`` says"""
    return document(doc) == parse(line_breaks(content))


def initial_state(content):
    """The state of a doc edited live for the first time"""
    return to_ydoc(parse(line_breaks(content))).get_update()


def edit(doc, new):
    """Changes the document to the Markdown ``new`` with as few changes as
    possible (a deep diff), so that what others type at the same time
    stays; returns the update (empty when nothing changed)"""
    return diff.edit(doc, line_breaks(new))


def clocks(doc):
    """The document's state vector: what it has of every Yjs client, as
    ``{client ID: clock}``"""
    decoder = Decoder(doc.get_state())
    return {
        decoder.read_var_uint(): decoder.read_var_uint()
        for _ in range(decoder.read_var_uint())
    }


def is_valid(update):
    """Whether the bytes are a Yjs update at all"""
    try:
        Doc().apply_update(bytes(update))
    except RuntimeError, ValueError:
        return False
    return True
