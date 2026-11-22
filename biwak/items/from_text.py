"""Adding to-dos from text (specs/todos-from-text.md)

One parser for the modal, the API and the CLI: headings become groups,
list items to-dos (the first line the title, what's indented under it the
notes, nested items as a checklist), ticked items completed to-dos. A text
without any list items makes a to-do of every line that isn't a heading.

``parse()`` reads the text alone; ``plan()`` matches its headings with the
groups of a list and says what's in the way (``Plan.problem``).
``operations.add_from_text()`` adds what ``plan()`` planned.
"""

import dataclasses
import re

from django.utils.text import Truncator
from django.utils.translation import gettext, ngettext
from markdown_it import MarkdownIt

from biwak import checklists
from biwak.text import line_breaks


# Decided 2026-11-22
MAX_TODOS = 500
MAX_BYTES = 200 * 1024
# The fields' lengths (``Item.title``, ``Group.title``)
TITLE_LENGTH = 500
GROUP_LENGTH = 200

# Plain CommonMark, no HTML: the text is source, nothing is rendered
_parser = MarkdownIt("commonmark", {"html": False})
_parser.enable("strikethrough")

# A list item's line up to its text: indentation, the marker, the box
_ITEM = re.compile(r"^(\s*)([-*+]|\d{1,9}[.)])(?:[ \t]+|$)(?:\[([ xX])\](?:[ \t]+|$))?")
_BOX = re.compile(r"^\[([ xX])\](?:[ \t]+|$)")
# What isn't an item or a heading and isn't left out either
_IGNORED = {"hr"}


@dataclasses.dataclass
class Todo:
    title: str
    notes: str = ""
    completed: bool = False
    # The to-do's ID once added
    id: int | None = None

    def __post_init__(self):
        # The notes' checklist, as the to-do will store it (``Checklist``)
        self.done, self.total = checklists.count(self.notes)


@dataclasses.dataclass
class Section:
    """The to-dos under a heading (``title``), or before the first one
    (``None``); with ``plan()`` the group they go to (``None``: a new one,
    or ungrouped)"""

    title: str | None
    todos: list = dataclasses.field(default_factory=list)
    group: object = None
    # Its group was created by adding the text
    created: bool = False

    @property
    def is_new(self):
        return self.created or (self.title is not None and self.group is None)


@dataclasses.dataclass
class Parsed:
    sections: list
    # Top-level paragraphs (and code, quotes, tables) of a text with list
    # items: not to-dos
    left_out: int = 0

    @property
    def todos(self):
        return [todo for section in self.sections for todo in section.todos]

    @property
    def count(self):
        return sum(len(section.todos) for section in self.sections)


def _plain(children, *, first_line=True):
    """The text of inline tokens without Markdown: the first line only, or
    every line joined"""
    parts = []
    for token in children or ():
        if token.type in {"softbreak", "hardbreak"}:
            if first_line:
                break
            parts.append(" ")
        elif token.type in {"text", "code_inline"} or token.type == "image":
            parts.append(token.content)
    return " ".join("".join(parts).split())


def _dedent(lines, width):
    """The lines without up to ``width`` leading spaces (tabs count four)"""
    result = []
    for line in lines:
        expanded = line.expandtabs(4)
        spaces = len(expanded) - len(expanded.lstrip(" "))
        result.append(expanded[min(spaces, width) :])
    return result


def _trim(lines):
    while lines and not lines[0].strip():
        lines = lines[1:]
    while lines and not lines[-1].strip():
        lines = lines[:-1]
    return lines


def as_checklist(notes):
    """The notes' top-level list items as a checklist (``- [ ]``, ticked
    ones stay ticked); deeper levels and everything else as written"""
    if not notes:
        return notes
    lines = notes.split("\n")
    for token in _parser.parse(notes):
        if token.type != "list_item_open" or token.level != 1:
            continue
        number = token.map[0]
        match = _ITEM.match(lines[number])
        if match is None or not lines[number][match.end() :].strip():
            continue
        mark = "x" if (match[3] or " ").lower() == "x" else " "
        lines[number] = f"{match[1]}- [{mark}] {lines[number][match.end() :].lstrip()}"
    return "\n".join(lines)


def _todo(title, notes, *, completed):
    """A to-do; a title too long for the field is cut, the whole line kept
    at the top of the notes"""
    if len(title) > TITLE_LENGTH:
        notes = f"{title}\n\n{notes}" if notes else title
        title = Truncator(title).chars(TITLE_LENGTH)
    return Todo(title=title, notes=notes, completed=completed)


def _items(tokens, start, lines):
    """The to-dos of the top-level list opening at ``tokens[start]``, and
    the index after it"""
    todos = []
    index = start + 1
    while tokens[index].type not in {"bullet_list_close", "ordered_list_close"}:
        token = tokens[index]
        if token.type != "list_item_open" or token.level != 1:
            index += 1
            continue
        begin, end = token.map
        match = _ITEM.match(lines[begin])
        width = len(match[0].expandtabs(4)) if match else 2
        # The first line: the inline tokens of its paragraph (or heading)
        inline = tokens[index + 2] if index + 2 < len(tokens) else None
        if not (
            inline is not None
            and inline.type == "inline"
            and tokens[index + 1].type in {"paragraph_open", "heading_open"}
            and tokens[index + 1].map[0] == begin
        ):
            inline = None
        children = list(inline.children) if inline is not None else []
        completed = False
        if children and children[0].type == "text":
            box = _BOX.match(children[0].content)
            if box:
                completed = box[1].lower() == "x"
                first = children[0].copy()
                first.content = first.content[box.end() :]
                children[0] = first
        title = _plain(children)
        if inline is None:
            # Nothing, or code or a quote right after the marker: the line
            # as written
            title = " ".join(lines[begin][len(match[0]) if match else 0 :].split())
            completed = bool(match and (match[3] or "").lower() == "x")
        rest = _trim(_dedent(lines[begin + 1 : end], width))
        if title:
            todos.append(
                _todo(title, as_checklist("\n".join(rest)), completed=completed)
            )
        # On to the next item of this list
        level = token.level
        index += 1
        while not (
            tokens[index].type == "list_item_close" and tokens[index].level == level
        ):
            index += 1
        index += 1
    return todos, index + 1


def _line_todos(token, lines):
    """Every non-empty line of a block as a to-do (a text without list
    items)"""
    if token.type in {"fence", "code_block"}:
        texts = token.content.split("\n")
    else:
        begin, end = token.map
        texts = [
            _plain(child.children, first_line=False)
            for child in (_parser.parseInline(line)[0] for line in lines[begin:end])
        ]
    return [
        _todo(" ".join(text.split()), "", completed=False)
        for text in texts
        if text.strip()
    ]


def parse(text):
    """The text's sections and what's left out (``Parsed``)"""
    text = line_breaks(text or "")
    lines = text.split("\n")
    tokens = _parser.parse(text)
    with_items = any(token.type == "list_item_open" for token in tokens)
    sections = [Section(None)]
    left_out = 0
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.level != 0 or token.type.endswith("_close"):
            index += 1
            continue
        if token.type == "heading_open":
            title = _plain(tokens[index + 1].children, first_line=False)
            if title:
                sections.append(Section(title[:GROUP_LENGTH].strip()))
            index += 3
        elif token.type in {"bullet_list_open", "ordered_list_open"}:
            todos, index = _items(tokens, index, lines)
            sections[-1].todos.extend(todos)
        elif token.type in _IGNORED or token.map is None:
            index += 1
        else:
            if with_items:
                left_out += 1
            else:
                sections[-1].todos.extend(_line_todos(token, lines))
            # Past the block's closing token
            level_close = token.type.removesuffix("_open") + "_close"
            if token.nesting == 1:
                while tokens[index].type != level_close or tokens[index].level != 0:
                    index += 1
            index += 1
    return Parsed(sections=_merged(sections), left_out=left_out)


def _key(title):
    return " ".join(title.split()).casefold()


def _merged(sections):
    """Sections of the same heading as one, in the order they first
    appear; the to-dos before the first heading first"""
    merged = {}
    for section in sections:
        key = None if section.title is None else _key(section.title)
        if key in merged:
            merged[key].todos.extend(section.todos)
        else:
            merged[key] = section
    return list(merged.values())


@dataclasses.dataclass
class Plan(Parsed):
    """What adding the text to a list does: the sections with their
    groups, and ``problem``, why nothing can be added (else empty)"""

    problem: str = ""
    # Headings needing a group the person may not create
    refused: list = dataclasses.field(default_factory=list)

    @property
    def new_groups(self):
        return [section for section in self.sections if section.is_new]

    @property
    def left_out_note(self):
        if not self.left_out:
            return ""
        return ngettext(
            "%(count)d paragraph isn’t a list item and is left out.",
            "%(count)d paragraphs aren’t list items and are left out.",
            self.left_out,
        ) % {"count": self.left_out}

    @property
    def submit_label(self):
        if not self.count or self.problem:
            return gettext("Add to-dos")
        return ngettext("Add %(count)d to-do", "Add %(count)d to-dos", self.count) % {
            "count": self.count
        }


def plan(todolist, text, *, may_add_groups=True):
    """``parse()`` of the text for ``todolist`` (a ``TodoList``): headings
    matching a group of the list (ignoring case and surrounding spaces) go
    there, the others are new groups at the end. ``may_add_groups``:
    whether the person may create groups (clients only in lists they
    created, specs/access.md)."""
    text = text or ""
    if len(text.encode()) > MAX_BYTES:
        return Plan(
            sections=[],
            problem=gettext(
                "This text is larger than 200 KB; up to 200 KB can be added at once."
            ),
        )
    parsed = parse(text)
    groups = {}
    for group in todolist.groups.all():
        groups.setdefault(_key(group.title), group)
    for section in parsed.sections:
        if section.title is not None:
            section.group = groups.get(_key(section.title))
    result = Plan(sections=parsed.sections, left_out=parsed.left_out)
    if not may_add_groups:
        result.refused = [section.title for section in result.new_groups]
    if not text.strip():
        result.problem = gettext("Paste a text or choose a file.")
    elif not result.count:
        result.problem = gettext("This text has no to-dos.")
    elif result.count > MAX_TODOS:
        result.problem = gettext(
            "This text has %(count)d to-dos; up to %(max)d can be added at once."
        ) % {"count": result.count, "max": MAX_TODOS}
    elif result.refused:
        result.problem = ngettext(
            "Only the list’s creator can add groups. Remove this heading or "
            "use the name of an existing group: %(headings)s",
            "Only the list’s creator can add groups. Remove these headings "
            "or use the names of existing groups: %(headings)s",
            len(result.refused),
        ) % {"headings": ", ".join(result.refused)}
    return result
