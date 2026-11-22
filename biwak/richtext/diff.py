"""Edits from elsewhere (the API, a tick, restoring a version) on a live
doc's Yjs document: the new Markdown parsed, and only what differs changed
in the XmlFragment, so that what people type elsewhere at the same time
stays.

``depth="top"``: top-level blocks that differ are replaced (the proposal
in specs/rich-editor.md). ``depth="deep"``: blocks of the same kind are
matched and changed inside: attributes (a tick), children of lists and
quotes, and the text of paragraphs and headings by a character diff.
"""

import json
from difflib import SequenceMatcher

from pycrdt import XmlElement, XmlFragment, XmlText

from .parse import parse
from .tree import Mark, Node, Text, join_texts
from .ycrdt import FRAGMENT, _fill, _value


TEXTBLOCKS = {"paragraph", "heading", "table_header", "table_cell"}


def _key(node):
    return json.dumps(node.to_json(), sort_keys=True)


def _tree(y):
    """One Y child as a tree node"""
    if isinstance(y, XmlText):
        raise TypeError("text at block level")
    attrs = {k: _value(v) for k, v in y.attributes}
    children = []
    for child in y.children:
        if isinstance(child, XmlText):
            for text, a in child.diff():
                children.append(
                    Text(text, [Mark(n, v or {}) for n, v in (a or {}).items()])
                )
        else:
            children.append(_tree(child))
    return Node(y.tag, attrs, join_texts(children))


def _only_text(y):
    kids = list(y.children)
    return len(kids) <= 1 and all(isinstance(k, XmlText) for k in kids)


def _runs(node):
    """[(char, attrs)] of a textblock with only text"""
    out = []
    for child in node.children:
        attrs = {m.type: dict(m.attrs) for m in child.marks} or None
        out.extend((ch, attrs) for ch in child.text)
    return out


def _edit_text(y, old, new):
    """Changes the XmlText of textblock ``y`` from ``old`` to ``new`` (tree
    nodes with only text) by a character diff; pycrdt counts UTF-8 bytes"""
    kids = list(y.children)
    if not kids:
        y.children.append(XmlText())
        kids = list(y.children)
    text = kids[0]
    a, b = _runs(old), _runs(new)
    old_str = "".join(c for c, _ in a)
    new_str = "".join(c for c, _ in b)
    ops = SequenceMatcher(None, old_str, new_str, autojunk=False).get_opcodes()
    for tag, i1, i2, j1, j2 in reversed(ops):
        start = len(old_str[:i1].encode())
        if tag == "equal":
            # marks changed on unchanged characters?
            for k in range(i2 - i1):
                if a[i1 + k][1] != b[j1 + k][1]:
                    pos = len(old_str[: i1 + k].encode())
                    size = len(old_str[i1 + k].encode())
                    want = b[j1 + k][1] or {}
                    had = a[i1 + k][1] or {}
                    attrs = {**{n: None for n in had if n not in want}, **want}
                    text.format(pos, pos + size, attrs)
            continue
        # insert first, then delete what it replaces (as ytext.edit())
        index = start
        for ch, attrs in b[j1:j2]:
            text.insert(index, ch, attrs)
            index += len(ch.encode())
        if i2 > i1:
            del text[index : index + len(old_str[i1:i2].encode())]


def _sync(yparent, old, new, deep):
    """Changes the Y children of ``yparent`` (trees ``old``) to ``new``"""
    ykids = list(yparent.children)
    ops = SequenceMatcher(
        None, [_key(n) for n in old], [_key(n) for n in new], autojunk=False
    ).get_opcodes()
    # From the end, so that the indices before stay valid
    for tag, i1, i2, j1, j2 in reversed(ops):
        if tag == "equal":
            continue
        pairs = 0
        if deep and tag == "replace":
            pairs = min(i2 - i1, j2 - j1)
        # what isn't paired: removed or added after the pairs
        extra_old = range(i1 + pairs, i2)
        extra_new = new[j1 + pairs : j2]
        if extra_old:
            del yparent.children[extra_old.start : extra_old.stop]
        for k, node in enumerate(extra_new):
            _insert(yparent, i1 + pairs + k, node)
        for k in reversed(range(pairs)):
            o, n, y = old[i1 + k], new[j1 + k], ykids[i1 + k]
            if (
                o.type != n.type
                or (o.type in TEXTBLOCKS and not (_only_text(y) and _plain(n)))
                or n.type in {"code_block", "table"}
            ):
                del yparent.children[i1 + k]
                _insert(yparent, i1 + k, n)
                continue
            for name, value in n.attrs.items():
                if o.attrs.get(name) != value:
                    if value is None:
                        del y.attributes[name]
                    else:
                        y.attributes[name] = value
            if o.type in TEXTBLOCKS:
                _edit_text(y, o, n)
            else:
                _sync(y, o.children, n.children, deep)


def _plain(node):
    return all(c.is_text for c in node.children)


def _insert(yparent, index, node):
    """A new Y element for ``node`` at ``index``"""
    attrs = {k: v for k, v in node.attrs.items() if v is not None}
    element = yparent.children.insert(index, XmlElement(node.type, attrs))
    _fill(element, node.children)


def edit(ydoc, markdown, *, depth="top"):
    """The update that changes the live doc to ``markdown`` (empty when
    nothing changed)"""
    fragment = ydoc.get(FRAGMENT, type=XmlFragment)
    old = [_tree(y) for y in fragment.children]
    new = parse(markdown).children
    before = ydoc.get_state()
    with ydoc.transaction():
        _sync(fragment, old, new, depth == "deep")
    return ydoc.get_update(before)
