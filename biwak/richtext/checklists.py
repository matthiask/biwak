"""GitHub's task lists in Markdown texts (specs/editor.md): ``- [ ] open``
and ``- [x] done``.

Counting and ticking use the same parser as rendering, so a checkbox is
whatever the page shows as one (not one in a code block). A checkbox is
named by its position among the text's checkboxes, in reading order.
"""

import hashlib
import re


CHECKBOX = "task-list-item-checkbox"
# The start of a task list line up to its box: quotes, indentation, the
# list marker
_BOX = re.compile(r"^((?:[ \t]|>)*(?:[-*+]|\d+[.)])[ \t]+)\[([ xX])\]")
_LINES = re.compile(r"(\r\n|\r|\n)")


class NoCheckbox(LookupError):
    """The text has no such checkbox"""


def text_hash(text):
    """The version of a text, what a page sends back when ticking"""
    return hashlib.sha256((text or "").encode()).hexdigest()[:16]


def is_checkbox(token):
    return token.type == "html_inline" and token.content.startswith(
        f'<input class="{CHECKBOX}"'
    )


def boxes(tokens):
    """``[(first line, checked)]`` of the checkboxes in the parsed tokens
    (before ``biwak.templatetags.biwak`` rewrites them), in reading order"""
    result = []
    for token in tokens:
        if token.type != "inline" or not token.children:
            continue
        if is_checkbox(token.children[0]):
            result.append((token.map[0], "checked" in token.children[0].content))
    return result


def _parse(text):
    from biwak.templatetags.biwak import _markdown

    return _markdown.parse(text, {})


def count(text):
    """``(done, total)``"""
    if not text or "[" not in text:
        return 0, 0
    found = boxes(_parse(text))
    return sum(checked for _line, checked in found), len(found)


def tick(text, index, checked=None):
    """The text with checkbox ``index`` toggled (or set to ``checked``);
    ``NoCheckbox`` if there's none, or the line isn't what the parser said
    (never changes anything else)"""
    found = boxes(_parse(text)) if text and "[" in text else []
    if not 0 <= index < len(found):
        raise NoCheckbox(index)
    line, was_checked = found[index]
    parts = _LINES.split(text)
    number = line * 2
    match = _BOX.match(parts[number]) if number < len(parts) else None
    if match is None:
        raise NoCheckbox(index)
    now = (not was_checked) if checked is None else checked
    mark = "x" if now else " "
    start = match.end() - 2
    parts[number] = parts[number][:start] + mark + parts[number][start + 1 :]
    return "".join(parts)
