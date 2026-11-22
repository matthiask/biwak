"""The editor's document in Python: the shape of the ProseMirror schema
(``frontend/editor/schema.js``; change both together), enough to parse,
serialize, compare and build Yjs documents (specs/rich-editor.md)"""

import json


# Attributes and their defaults, as in schema.js (y-prosemirror leaves out
# attributes that are null)
NODES = {
    "doc": {},
    "paragraph": {},
    "heading": {"level": 1, "markup": None},
    "blockquote": {},
    "code_block": {"params": "", "markup": None},
    "horizontal_rule": {"markup": None},
    "bullet_list": {"tight": True, "markup": None},
    "ordered_list": {"order": 1, "tight": True, "markup": None},
    "list_item": {"checked": None},
    "table": {},
    "table_row": {},
    "table_header": {"colspan": 1, "rowspan": 1, "colwidth": None, "align": None},
    "table_cell": {"colspan": 1, "rowspan": 1, "colwidth": None, "align": None},
    # href: the link around the image (an attribute: y-prosemirror drops
    # marks on inline nodes)
    "image": {"src": None, "alt": None, "title": None, "href": None, "hrefTitle": None},
    "mention": {"id": None, "label": ""},
    "hard_break": {},
}
INLINE = {"image", "mention", "hard_break"}
# In the schema's order, which is the order of marks on a text
MARKS = {
    "em": {"markup": None},
    "strong": {"markup": None},
    "strikethrough": {},
    "link": {"href": None, "title": None, "markup": None},
    "code": {},
}
MARK_RANK = {name: i for i, name in enumerate(MARKS)}


class Mark:
    def __init__(self, type, attrs=None):
        self.type = type
        self.attrs = {**MARKS[type], **(attrs or {})}

    def __eq__(self, other):
        return (
            isinstance(other, Mark)
            and self.type == other.type
            and self.attrs == other.attrs
        )

    __hash__ = None

    def __repr__(self):
        return f"Mark({self.type}, {self.attrs})"


def sort_marks(marks):
    return sorted(marks, key=lambda m: MARK_RANK[m.type])


class Node:
    is_text = False

    def __init__(self, type, attrs=None, children=None, marks=()):
        self.type = type
        self.attrs = {**NODES[type], **(attrs or {})}
        self.children = children or []
        self.marks = list(marks)

    @property
    def is_inline(self):
        return self.type in INLINE

    @property
    def text_content(self):
        return "".join(c.text if c.is_text else c.text_content for c in self.children)

    def __eq__(self, other):
        return isinstance(other, Node) and key(self) == key(other)

    __hash__ = None

    def to_json(self):
        out = {"type": self.type}
        attrs = dict(self.attrs.items())
        if NODES[self.type]:
            out["attrs"] = attrs
        if self.children:
            out["content"] = [c.to_json() for c in self.children]
        if self.marks:
            out["marks"] = [m_json(m) for m in self.marks]
        return out


class Text:
    is_text = True
    attrs = {}
    children = ()
    is_inline = True
    type = "text"

    def __init__(self, text, marks=()):
        self.text = text
        self.marks = sort_marks(marks)

    def with_text(self, text):
        return Text(text, self.marks)

    def to_json(self):
        out = {"type": "text", "text": self.text}
        if self.marks:
            out["marks"] = [m_json(m) for m in self.marks]
        return out


def m_json(mark):
    out = {"type": mark.type}
    if MARKS[mark.type]:
        out["attrs"] = mark.attrs
    return out


def join_texts(children):
    """Adjacent texts with the same marks are one (as in ProseMirror)"""
    out = []
    for child in children:
        if child.is_text and out and out[-1].is_text and out[-1].marks == child.marks:
            out[-1] = out[-1].with_text(out[-1].text + child.text)
        elif child.is_text and not child.text:
            continue
        else:
            out.append(child)
    return out


def key(node):
    """The node as a string, equal for equal nodes"""
    return json.dumps(node.to_json(), sort_keys=True)
