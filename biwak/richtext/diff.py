"""Edits from elsewhere (the API, the CLI, restoring a version, a tick) on a
live doc's Yjs document (specs/rich-editor.md, "Edits from elsewhere"): the
new Markdown parsed, and only what differs changed in the XmlFragment, so
that what people type elsewhere at the same time stays.

A deep diff (decided 2026-11-22 after the spike): nodes of the same kind
are paired in the changed ranges, changed attributes set (a tick is one),
lists, quotes and tables recursed into, and the text of textblocks diffed
character by character with its marks, around their inline nodes
(mentions, images, breaks). Typing in a block the edit deletes is lost.

pycrdt counts UTF-8 bytes where Yjs (and the browsers) count UTF-16 units:
positions here are bytes.
"""

import itertools
from difflib import SequenceMatcher

from pycrdt import XmlElement, XmlFragment, XmlText

from .parse import parse
from .tree import Mark, Node, Text, join_texts, key
from .ydoc import FRAGMENT, _fill, _value


TEXTBLOCKS = {"paragraph", "heading", "table_header", "table_cell"}
# Replaced as a whole when they differ (their text is one string)
WHOLE = {"code_block"}


def _text_runs(ytext):
    return [
        Text(text, [Mark(name, attrs or {}) for name, attrs in (marks or {}).items()])
        for text, marks in ytext.diff()
    ]


def tree(y):
    """One Y element as a tree node"""
    attrs = {k: _value(v) for k, v in y.attributes}
    children = []
    for child in y.children:
        if isinstance(child, XmlText):
            children.extend(_text_runs(child))
        else:
            children.append(tree(child))
    return Node(y.tag, attrs, join_texts(children))


def _plain(node):
    """What a Y document can hold of a node: inline nodes without marks
    (y-prosemirror drops them)"""
    if node.is_text:
        return node
    marks = [] if node.is_inline else node.marks
    return Node(node.type, node.attrs, [_plain(c) for c in node.children], marks)


def _chars(texts):
    """[(character, marks as Y attributes)] of text nodes"""
    out = []
    for t in texts:
        attrs = {m.type: dict(m.attrs) for m in t.marks} or None
        out.extend((ch, attrs) for ch in t.text)
    return out


def _edit_text(ytext, old, new):
    """Changes ``ytext`` from the text nodes ``old`` to ``new`` by a
    character diff, marks included"""
    a, b = _chars(old), _chars(new)
    old_str = "".join(c for c, _ in a)
    new_str = "".join(c for c, _ in b)
    opcodes = SequenceMatcher(None, old_str, new_str, autojunk=False).get_opcodes()
    for tag, i1, i2, j1, j2 in reversed(opcodes):
        if tag == "equal":
            # Marks changed on unchanged characters?
            for k in range(i2 - i1):
                had, want = a[i1 + k][1] or {}, b[j1 + k][1] or {}
                if had != want:
                    pos = len(old_str[: i1 + k].encode())
                    size = len(old_str[i1 + k].encode())
                    ytext.format(
                        pos,
                        pos + size,
                        {**dict.fromkeys(set(had) - set(want)), **want},
                    )
            continue
        # Inserting first, then deleting what it replaces (as ytext.edit()):
        # what others add after the replaced text stays after it
        index = len(old_str[:i1].encode())
        for ch, attrs in b[j1:j2]:
            ytext.insert(index, ch, attrs or {})
            index += len(ch.encode())
        if i2 > i1:
            del ytext[index : index + len(old_str[i1:i2].encode())]


def _segments(children):
    """A textblock's children grouped: runs of text, inline nodes"""
    out = []
    for child in children:
        if child.is_text:
            if out and out[-1][0] == "text":
                out[-1][1].append(child)
            else:
                out.append(("text", [child]))
        else:
            out.append(("node", child))
    return out


def _segment_key(segment):
    return "text" if segment[0] == "text" else key(segment[1])


def _insert_segment(y, index, segment):
    if segment[0] == "text":
        ytext = y.children.insert(index, XmlText())
        _fill_text(ytext, segment[1])
    else:
        _insert(y, index, segment[1])


def _fill_text(ytext, texts):
    index = 0
    for t in texts:
        ytext.insert(index, t.text, {m.type: dict(m.attrs) for m in t.marks})
        index += len(t.text.encode())


def _text_of(texts):
    return "".join(t.text for t in texts)


def _common(a, b):
    """How much two texts have in common: the longest piece first, then
    all of them"""
    blocks = SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks()
    return max(b.size for b in blocks) * 10000 + sum(b.size for b in blocks)


def _pairs(old_texts, new_texts):
    """The best order-keeping pairing of the old and new runs of text in a
    gap between unchanged inline nodes (most characters in common), so that
    a run split by a new mention keeps its Y text where most of it went:
    ``[(old index, new index)]``"""
    if not old_texts or not new_texts:
        return []
    score = [[_common(_text_of(o), _text_of(n)) for n in new_texts] for o in old_texts]
    rows, cols = len(old_texts), len(new_texts)
    best = [[0] * (cols + 1) for _ in range(rows + 1)]
    for i in range(rows - 1, -1, -1):
        for j in range(cols - 1, -1, -1):
            best[i][j] = max(
                best[i + 1][j], best[i][j + 1], score[i][j] + best[i + 1][j + 1]
            )
    pairs, i, j = [], 0, 0
    while i < rows and j < cols:
        if best[i][j] == score[i][j] + best[i + 1][j + 1]:
            pairs.append((i, j))
            i += 1
            j += 1
        elif best[i][j] == best[i + 1][j]:
            i += 1
        else:
            j += 1
    return pairs


def _edit_textblock(y, new):
    """Changes the Y textblock ``y`` to the node ``new``: its inline nodes
    which stay as they are anchor it, the runs of text between them are
    diffed by characters"""
    old = []  # (kind, value, Y child), one per Y child
    for child in list(y.children):
        if isinstance(child, XmlText):
            old.append(("text", _text_runs(child), child))
        else:
            old.append(("node", tree(child), child))
    new_segments = _segments(new.children)
    # The inline nodes that stay, in order
    old_nodes = [i for i, s in enumerate(old) if s[0] == "node"]
    new_nodes = [j for j, s in enumerate(new_segments) if s[0] == "node"]
    blocks = SequenceMatcher(
        None,
        [key(old[i][1]) for i in old_nodes],
        [key(new_segments[j][1]) for j in new_nodes],
        autojunk=False,
    ).get_matching_blocks()
    anchors = [
        (old_nodes[b.a + k], new_nodes[b.b + k]) for b in blocks for k in range(b.size)
    ]
    # The gaps between the anchors, from the end (indices stay valid)
    bounds = [(-1, -1), *anchors, (len(old), len(new_segments))]
    for (a1, b1), (a2, b2) in reversed(list(itertools.pairwise(bounds))):
        olds = list(range(a1 + 1, a2))
        news = list(range(b1 + 1, b2))
        old_texts = [i for i in olds if old[i][0] == "text"]
        new_texts = [j for j in news if new_segments[j][0] == "text"]
        paired = {
            old_texts[i]: new_texts[j]
            for i, j in _pairs(
                [old[i][1] for i in old_texts],
                [new_segments[j][1] for j in new_texts],
            )
        }
        for i in reversed(olds):
            if i not in paired:
                del y.children[i]
        position = a1 + 1
        reused = iter(sorted(paired.items()))
        current = next(reused, None)
        for j in news:
            if current is not None and current[1] == j:
                _kind, value, child = old[current[0]]
                _edit_text(child, value, new_segments[j][1])
                current = next(reused, None)
            else:
                _insert_segment(y, position, new_segments[j])
            position += 1


def _set_attributes(y, old, new):
    for name, value in new.attrs.items():
        if old.attrs.get(name) != value:
            if value is None:
                del y.attributes[name]
            else:
                y.attributes[name] = value


def _sync(yparent, old, new):
    """Changes the Y children of ``yparent`` (the tree nodes ``old``) to
    ``new``"""
    ykids = list(yparent.children)
    opcodes = SequenceMatcher(
        None, [key(n) for n in old], [key(n) for n in new], autojunk=False
    ).get_opcodes()
    # From the end, so that the indices before stay valid
    for tag, i1, i2, j1, j2 in reversed(opcodes):
        if tag == "equal":
            continue
        pairs = min(i2 - i1, j2 - j1) if tag == "replace" else 0
        # What isn't paired is removed or added after the pairs
        if i2 > i1 + pairs:
            del yparent.children[i1 + pairs : i2]
        for k, node in enumerate(new[j1 + pairs : j2]):
            _insert(yparent, i1 + pairs + k, node)
        for k in reversed(range(pairs)):
            o, n, y = old[i1 + k], new[j1 + k], ykids[i1 + k]
            if o.type != n.type or n.type in WHOLE:
                del yparent.children[i1 + k]
                _insert(yparent, i1 + k, n)
                continue
            _set_attributes(y, o, n)
            if n.type in TEXTBLOCKS:
                _edit_textblock(y, n)
            else:
                _sync(y, o.children, n.children)


def _insert(yparent, index, node):
    """A new Y element for ``node`` at ``index``"""
    attrs = {k: v for k, v in node.attrs.items() if v is not None}
    element = yparent.children.insert(index, XmlElement(node.type, attrs))
    _fill(element, node.children)


def document(ydoc):
    """The live doc's document (a tree)"""
    fragment = ydoc.get(FRAGMENT, type=XmlFragment)
    return Node("doc", {}, [tree(y) for y in fragment.children])


def edit(ydoc, markdown):
    """Changes the live doc to ``markdown``; returns the update (empty when
    nothing changed)"""
    return edit_document(ydoc, parse(markdown))


def edit_document(ydoc, doc):
    fragment = ydoc.get(FRAGMENT, type=XmlFragment)
    old = [tree(y) for y in fragment.children]
    new = [_plain(n) for n in doc.children]
    if [key(n) for n in old] == [key(n) for n in new]:
        return b""
    before = ydoc.get_state()
    with ydoc.transaction():
        _sync(fragment, old, new)
    return ydoc.get_update(before)
