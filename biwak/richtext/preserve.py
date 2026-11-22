"""Markdown for an edited document that changes no more of the old text
than the edit did (specs/rich-editor.md, "Round trips must not change
texts nobody edited"): the old text itself when it parses to the same
document; else the top-level blocks equal to blocks of the old text keep
their old source (line ranges from markdown-it's token maps) and only the
changed blocks are serialized."""

from difflib import SequenceMatcher

from .parse import _md, parse
from .serialize import serialize
from .tree import Node, key


def _sources(markdown):
    """The source lines of each top-level block, in order"""
    lines = markdown.split("\n")
    out = []
    for token in _md.parse(markdown):
        if token.level == 0 and token.map and token.nesting in {0, 1}:
            start, end = token.map
            out.append("\n".join(lines[start:end]).rstrip("\n"))
    return out


def to_markdown(doc, old=""):
    """``doc`` as Markdown, keeping what it can of ``old``"""
    if not old:
        return serialize(doc)
    before = parse(old)
    if before == doc:
        return old
    sources = _sources(old)
    if len(sources) != len(before.children):  # (shouldn't happen)
        return serialize(doc)
    # Adjacent lists of the same kind need a separator a block alone can't
    # know: then everything is serialized
    for a, b in zip(doc.children, doc.children[1:], strict=False):
        if a.type == b.type and a.type in {"bullet_list", "ordered_list"}:
            return serialize(doc)
    opcodes = SequenceMatcher(
        None,
        [key(n) for n in before.children],
        [key(n) for n in doc.children],
        autojunk=False,
    ).get_opcodes()
    parts = []
    for tag, i1, _i2, j1, j2 in opcodes:
        for k in range(j2 - j1):
            if tag == "equal":
                parts.append(sources[i1 + k])
            else:
                block = doc.children[j1 + k]
                parts.append(serialize(Node("doc", {}, [block])).rstrip("\n"))
    text = "\n\n".join(parts)
    # Only if it means what the document says (a kept block's source can
    # depend on what was before it, e.g. a lazy continuation line)
    return text if parse(text) == doc else serialize(doc)
