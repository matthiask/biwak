"""The editor's document in a Yjs document (pycrdt), in the shape
y-prosemirror gives it (the live docs, ``frontend/editor/live.js``): an XmlFragment ("prosemirror") of XmlElements named
like the nodes, their non-null attributes as attributes, runs of text as
XmlText with each mark as a formatting attribute (name: the mark's
attributes)"""

from pycrdt import Doc, XmlElement, XmlFragment, XmlText

from .tree import MARKS, Mark, Node, Text, join_texts


# frontend/editor/live-schema.js
FRAGMENT = "prosemirror"


def _value(v):
    # Python writes numbers as floats; y-prosemirror's are what PM had
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def from_fragment(fragment):
    return Node("doc", {}, _children(fragment.children))


def _children(children):
    out = []
    for child in children:
        if isinstance(child, XmlText):
            for text, attrs in child.diff():
                if not isinstance(text, str):
                    raise TypeError(f"embed in text: {text!r}")
                marks = [
                    Mark(name, attrs_ or {}) for name, attrs_ in (attrs or {}).items()
                ]
                out.append(Text(text, marks))
        else:
            attrs = {k: _value(v) for k, v in child.attributes}
            out.append(Node(child.tag, attrs, _children(child.children)))
    return join_texts(out)


def from_ydoc(doc):
    return from_fragment(doc.get(FRAGMENT, type=XmlFragment))


def _element(node):
    attrs = {k: v for k, v in node.attrs.items() if v is not None}
    return XmlElement(node.type, attrs)


def _fill(container, children):
    """Appends the children: runs of text as one XmlText"""
    run = []

    def flush():
        if not run:
            return
        text = XmlText()
        container.children.append(text)
        index = 0
        for t in run:
            attrs = {m.type: dict(m.attrs) for m in t.marks} or None
            text.insert(index, t.text, attrs)
            # pycrdt counts in UTF-8 bytes (y-prosemirror in UTF-16 units)
            index += len(t.text.encode())
        run.clear()

    for child in children:
        if child.is_text:
            run.append(child)
            continue
        flush()
        element = _element(child)
        container.children.append(element)
        _fill(element, child.children)
    flush()


def to_fragment(doc, fragment):
    with fragment.doc.transaction():
        _fill(fragment, doc.children)


def to_ydoc(doc):
    ydoc = Doc()
    to_fragment(doc, ydoc.get(FRAGMENT, type=XmlFragment))
    return ydoc


__all__ = ["FRAGMENT", "MARKS", "from_fragment", "from_ydoc", "to_fragment", "to_ydoc"]
