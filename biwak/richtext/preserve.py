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


def _ranges(markdown):
    """The line ranges ``(start, end)`` of each top-level block, in order"""
    return [
        tuple(token.map)
        for token in _md.parse(markdown)
        if token.level == 0 and token.map and token.nesting in {0, 1}
    ]


def _source(lines, start, end):
    return "\n".join(lines[start:end]).rstrip("\n")


def _merge(opcodes, old, new_part):
    """The text: runs of unchanged blocks as the old text has them
    (``old``: its lines and block ranges), the others from ``new_part(j)``"""
    lines, ranges = old
    last = opcodes[-1][4] if opcodes else 0
    parts = []
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            # With what's before the first block and after the last
            start = 0 if i1 == 0 and j1 == 0 else ranges[i1][0]
            if i2 == len(ranges) and j2 == last:
                parts.append("\n".join(lines[start:]))
            else:
                parts.append(_source(lines, start, ranges[i2 - 1][1]))
        else:
            parts.extend(new_part(j) for j in range(j1, j2))
    return "\n\n".join(parts)


def to_markdown(doc, old=""):
    """``doc`` as Markdown, keeping what it can of ``old``"""
    if not old:
        return serialize(doc)
    before = parse(old)
    if before == doc:
        return old
    lines, ranges = old.split("\n"), _ranges(old)
    if len(ranges) != len(before.children):  # (shouldn't happen)
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
    text = _merge(
        opcodes,
        (lines, ranges),
        lambda j: serialize(Node("doc", {}, [doc.children[j]])).rstrip("\n"),
    )
    # The old text's line breaks at the end too
    text = text.rstrip("\n") + old[len(old.rstrip("\n")) :]
    # Only if it means what the document says (a kept block's source can
    # depend on what was before it, e.g. a lazy continuation line)
    return text if parse(text) == doc else serialize(doc)


def keep_source(new, old):
    """``new`` (Markdown somebody saved, e.g. from the editor) with the old
    source of its top-level blocks that didn't change, and ``old`` itself
    when ``new`` means the same: the editor writes its whole document in its
    style, an edit shouldn't rewrite the rest. Changed blocks stay as
    ``new`` has them."""
    if not old or not new or new == old:
        return new
    before, after = parse(old), parse(new)
    if before == after:
        return old
    old_ranges, new_ranges = _ranges(old), _ranges(new)
    if len(old_ranges) != len(before.children) or len(new_ranges) != len(
        after.children
    ):
        return new
    opcodes = SequenceMatcher(
        None,
        [key(n) for n in before.children],
        [key(n) for n in after.children],
        autojunk=False,
    ).get_opcodes()
    if not any(tag == "equal" for tag, *_ in opcodes):
        return new
    new_lines = new.split("\n")
    text = _merge(
        opcodes,
        (old.split("\n"), old_ranges),
        lambda j: _source(new_lines, *new_ranges[j]),
    )
    return text if parse(text) == after else new
