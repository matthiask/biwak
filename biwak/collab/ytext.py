"""The Markdown of a doc as a Yjs document (pycrdt), shared with the
browsers' Yjs (``frontend/collab.js``: ``ydoc.getText("content")``)"""

from difflib import SequenceMatcher

from pycrdt import Doc, Text


TEXT = "content"


def ydoc(state=b"", updates=()):
    """A Yjs document from a state and the updates after it"""
    doc = Doc()
    for update in [state, *updates]:
        if update:
            doc.apply_update(bytes(update))
    return doc


def text(doc):
    return str(doc.get(TEXT, type=Text))


def initial_state(content):
    """The state of a doc edited live for the first time"""
    doc = Doc()
    doc.get(TEXT, type=Text).insert(0, content)
    return doc.get_update()


def edit(doc, new):
    """Changes the text to ``new`` with as few edits as possible, so that
    what others type at the same time stays; returns the update (empty
    when nothing changed)"""
    ytext = doc.get(TEXT, type=Text)
    old = str(ytext)
    if old == new:
        return b""
    before = doc.get_state()
    # pycrdt counts in UTF-8 bytes; the diff is in characters. Edited from
    # the end, so that the positions before each edit stay valid.
    opcodes = SequenceMatcher(None, old, new, autojunk=False).get_opcodes()
    with doc.transaction():
        for tag, i1, i2, j1, j2 in reversed(opcodes):
            if tag == "equal":
                continue
            # Inserting first: the new text then follows what's before it
            # and precedes what it replaces, so text others add after the
            # replaced text stays after it
            start = len(old[:i1].encode())
            inserted = new[j1:j2].encode()
            if inserted:
                ytext.insert(start, new[j1:j2])
            if i2 > i1:
                begin = start + len(inserted)
                del ytext[begin : begin + len(old[i1:i2].encode())]
    return doc.get_update(before)


def is_valid(update):
    """Whether the bytes are a Yjs update at all"""
    try:
        Doc().apply_update(bytes(update))
    except RuntimeError, ValueError:
        return False
    return True
