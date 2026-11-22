"""The editor's document as Markdown: a port of prosemirror-markdown's
MarkdownSerializerState and of our node and mark serializers
(``frontend/editor/markdown.js``), so that the server writes the same
Markdown as the browser, byte for byte. Change both together."""

# A port that keeps prosemirror-markdown's shape (positional flags, long
# functions), so that it can be compared with it line by line
# ruff: noqa: FBT002, FBT003, C901

import re

from .tree import Mark, Node, sort_marks


A = re.ASCII  # JavaScript's \w and \d are ASCII


def _sub(pattern, repl, string, flags=0):
    return re.sub(pattern, repl, string, flags=flags | A)


LINE_START = [
    (r"^(\s*)([-+*>=])", r"\1\\\2"),
    (r"^(\s*)(#{1,6})(\s|$)", r"\1\\\2\3"),
    (r"^(\s*\d+)([.)])(\s|$)", r"\1\\\2\3"),
    (r"^(\s*)(\|)", r"\1\\\2"),
]


def esc(string, start_of_line=False):
    def one(m):
        ch, i = m[0], m.start()
        if (
            ch == "_"
            and i > 0
            and i + 1 < len(string)
            and re.match(r"\w", string[i - 1], A)
            and re.match(r"\w", string[i + 1], A)
        ):
            return ch
        return "\\" + ch

    string = re.sub(r"[`*\\~\[\]_]", one, string)
    string = _sub(r"&(?=#?\w+;)", r"\\&", string)
    string = _sub(r"<(?=[a-zA-Z][\w+.-]*:|[^\s@<>]+@)", r"\\<", string)
    if start_of_line:
        for pattern, repl in LINE_START:
            string = re.sub(pattern, repl, string, count=1, flags=A)
    return string


class State:
    def __init__(self, serializer):
        self.s = serializer
        self.delim = ""
        self.parts = []  # the output (a string grows quadratically)
        self.closed = None
        self.in_autolink = None
        self.at_block_start = False
        self.in_tight_list = False
        self.last = ""

    # -- prosemirror-markdown's state ---------------------------------------

    def flush_close(self, size=2):
        if self.closed is not None:
            if not self.at_blank():
                self.append("\n")
            if size > 1:
                delim_min = re.sub(r"\s+$", "", self.delim)
                for _ in range(1, size):
                    self.append(delim_min + "\n")
            self.closed = None

    def wrap_block(self, delim, first_delim, node, f):
        old = self.delim
        self.write(first_delim if first_delim is not None else delim)
        self.delim += delim
        f()
        self.delim = old
        self.close_block(node)

    def at_blank(self):
        return not self.parts or self.last[-1:] == "\n"

    def ensure_new_line(self):
        if not self.at_blank():
            self.append("\n")

    @property
    def out(self):
        return "".join(self.parts)

    def append(self, text):
        if text:
            self.parts.append(text)
            self.last = text if len(text) > 1 else self.last[-1:] + text

    def write(self, content=None):
        self.flush_close()
        if self.delim and self.at_blank():
            self.append(self.delim)
        if content:
            self.append(content)

    def close_block(self, node):
        self.closed = node

    def text(self, text, escape=True):
        lines = text.split("\n")
        for i, line in enumerate(lines):
            self.write()
            # Escape exclamation marks in front of links
            if not escape and line[:1] == "[" and self.last.endswith("!"):
                escaped = len(self.last) > 1 and self.last[-2] == "\\"
                if escaped:
                    backslashes = 1
                    out = self.out
                    j = len(out) - 2
                    while j > 0:
                        if out[j - 1] == "\\":
                            backslashes += 1
                            j -= 1
                        else:
                            break
                    escaped = backslashes % 2 > 0
                if not escaped:
                    self.parts[-1] = self.parts[-1][:-1] + "\\!"
            self.append(self.esc(line, self.at_block_start) if escape else line)
            if i != len(lines) - 1:
                self.append("\n")

    def esc(self, string, start_of_line=False):
        return esc(string, start_of_line)

    def render(self, node, parent, index):
        getattr(self.s, f"node_{node.type}")(self, node, parent, index)

    def render_content(self, parent):
        for i, child in enumerate(parent.children):
            self.render(child, parent, i)

    def render_inline(self, parent, from_block_start=True):
        parent = _relink(parent)
        self.at_block_start = from_block_start
        active = []
        trailing = ""
        marks_of = self.s.marks
        children = parent.children

        def progress(node, index):
            nonlocal active, trailing
            marks = list(node.marks) if node is not None else []
            if node is not None and node.type == "hard_break":

                def keep_mark(m):
                    if index + 1 == len(children):
                        return False
                    nxt = children[index + 1]
                    return m in nxt.marks and (
                        not nxt.is_text or re.search(r"\S", nxt.text)
                    )

                marks = [m for m in marks if keep_mark(m)]
            inner = marks[-1] if marks else None
            no_esc = inner is not None and marks_of[inner.type].get("escape") is False
            length = len(marks) - (1 if no_esc else 0)
            # Reorder mixable marks to match the order of the active ones
            i = 0
            while i < length:
                mark = marks[i]
                if not marks_of[mark.type].get("mixable"):
                    break
                for j, other in enumerate(active):
                    if not marks_of[other.type].get("mixable"):
                        break
                    if mark == other:
                        if i > j:
                            # (as in JavaScript: what's after length is dropped)
                            marks = [
                                *marks[:j],
                                mark,
                                *marks[j:i],
                                *marks[i + 1 : length],
                            ]
                        elif j > i:
                            marks = (
                                marks[:i] + marks[i + 1 : j] + [mark] + marks[j:length]
                            )
                        break
                i += 1
            keep = 0
            while keep < min(len(active), length) and marks[keep] == active[keep]:
                keep += 1
            leading = trailing
            trailing = ""
            if (
                node is not None
                and node.is_text
                and len(marks) > keep
                and marks_of[marks[-1].type].get("expel")
            ):
                m = re.match(r"^(\s*)(.*)$", node.text, re.MULTILINE)
                lead, rest = m[1], m[2]
                if lead:
                    leading += lead
                    node = node.with_text(rest) if rest else None
                    if node is None:
                        marks = active
            if node is not None and node.is_text and marks:
                for k in range(len(marks) - 1, -1, -1):
                    mark = marks[k]
                    if not marks_of[mark.type].get("expel"):
                        break
                    if not self.is_mark_ahead(parent, index + 1, mark):
                        m = re.match(r"^(.*?)(\s*)$", node.text, re.MULTILINE)
                        rest, trail = m[1], m[2]
                        if trail:
                            trailing = trail
                            node = node.with_text(rest) if rest else None
                            if node is None:
                                marks = active
                        break
            if node is not None or index == len(children):
                while keep < len(active):
                    self.text(
                        self.mark_string(active.pop(), False, parent, index), False
                    )
            if leading:
                self.text(leading)
            if node is not None:
                while len(active) < length:
                    add = marks[len(active)]
                    active.append(add)
                    self.text(self.mark_string(add, True, parent, index), False)
                    self.at_block_start = False
                if no_esc and node.is_text:
                    self.text(
                        self.mark_string(inner, True, parent, index)
                        + node.text
                        + self.mark_string(inner, False, parent, index + 1),
                        False,
                    )
                else:
                    self.render(node, parent, index)
                self.at_block_start = False

        for index, child in enumerate(children):
            progress(child, index)
        progress(None, len(children))
        self.at_block_start = False

    def is_mark_ahead(self, parent, index, mark):
        while True:
            if index >= len(parent.children):
                return False
            nxt = parent.children[index]
            if nxt.type != "hard_break":
                return mark in nxt.marks
            index += 1

    def render_list(self, node, delim, first_delim):
        if self.closed is not None and self.closed.type == node.type:
            self.flush_close(3)
        elif self.in_tight_list:
            self.flush_close(1)
        is_tight = node.attrs.get("tight", True)
        prev_tight = self.in_tight_list
        self.in_tight_list = is_tight
        for i, child in enumerate(node.children):
            if i and is_tight:
                self.flush_close(1)
            self.wrap_block(
                delim,
                first_delim(i),
                node,
                lambda child=child, i=i: self.render(child, node, i),
            )
        self.in_tight_list = prev_tight

    def mark_string(self, mark, is_open, parent, index):
        info = self.s.marks[mark.type]
        value = info["open" if is_open else "close"]
        return value if isinstance(value, str) else value(self, mark, parent, index)


def _relink(parent):
    """Images with a link attribute get their link mark back, so that a
    link around text and an image stays one link"""
    if not any(c.type == "image" and c.attrs["href"] for c in parent.children):
        return parent
    children = []
    for child in parent.children:
        if child.type == "image" and child.attrs["href"]:
            link = Mark(
                "link", {"href": child.attrs["href"], "title": child.attrs["hrefTitle"]}
            )
            marks = [m for m in child.marks if m.type != "link"]
            children.append(
                Node(
                    "image",
                    {**child.attrs, "href": None, "hrefTitle": None},
                    marks=sort_marks([*marks, link]),
                )
            )
        else:
            children.append(child)
    return Node(parent.type, parent.attrs, children, parent.marks)


def backticks_for(node, side):
    length = 0
    if node.is_text:
        for m in re.finditer(r"`+", node.text):
            length = max(length, len(m[0]))
    result = " `" if length > 0 and side > 0 else "`"
    result += "`" * length
    if length > 0 and side < 0:
        result += " "
    return result


def linkifies(mark, parent, index):
    content = parent.children[index]
    if not content.is_text or mark.attrs["title"]:
        return False
    t, href = content.text, mark.attrs["href"]
    if not (t == href or f"http://{t}" == href or f"mailto:{t}" == href):
        return False
    if content.marks[-1] != mark:
        return False
    return (
        index == len(parent.children) - 1
        or mark not in parent.children[index + 1].marks
    )


class Serializer:
    def __init__(self, *, bullet="-", em="*", strong="**", linkify=True, preserve=True):
        self.o = {
            "bullet": bullet,
            "em": em,
            "strong": strong,
            "linkify": linkify,
            "preserve": preserve,
            "fence": "```",
            "hr": "---",
        }
        pick = self.pick
        self.marks = {
            "em": {
                "open": lambda s, m, p, i: pick(m.attrs["markup"], self.o["em"]),
                "close": lambda s, m, p, i: pick(m.attrs["markup"], self.o["em"]),
                "mixable": True,
                "expel": True,
            },
            "strong": {
                "open": lambda s, m, p, i: pick(m.attrs["markup"], self.o["strong"]),
                "close": lambda s, m, p, i: pick(m.attrs["markup"], self.o["strong"]),
                "mixable": True,
                "expel": True,
            },
            "strikethrough": {
                "open": "~~",
                "close": "~~",
                "mixable": True,
                "expel": True,
            },
            "link": {"open": self.link_open, "close": self.link_close, "mixable": True},
            "code": {
                "open": lambda s, m, p, i: backticks_for(p.children[i], -1),
                "close": lambda s, m, p, i: backticks_for(p.children[i - 1], 1),
                "escape": False,
            },
        }

    def pick(self, markup, fallback):
        return (self.o["preserve"] and markup) or fallback

    def serialize(self, doc):
        self.used = {}
        state = State(self)
        state.render_content(doc)
        return state.out

    # -- marks --------------------------------------------------------------

    def link_open(self, state, mark, parent, index):
        if (
            self.o["linkify"]
            and mark.attrs["markup"] != "autolink"
            and linkifies(mark, parent, index)
        ):
            state.in_autolink = "bare"
            return ""
        child = parent.children[index]
        plain = (
            not mark.attrs["title"]
            and re.match(r"^\w+:", mark.attrs["href"], A)
            and child.is_text
            and mark.attrs["href"] in {child.text, f"mailto:{child.text}"}
            and (mark.attrs["markup"] == "autolink" or not self.o["linkify"])
        )
        state.in_autolink = "angle" if plain else None
        return "<" if plain else "["

    def link_close(self, state, mark, parent, index):
        how = state.in_autolink
        state.in_autolink = None
        if how == "bare":
            return ""
        if how == "angle":
            return ">"
        href = re.sub(
            r'[()"\s]',
            lambda m: "%20" if m[0] == " " else "\\" + m[0],
            mark.attrs["href"],
        )
        title = mark.attrs["title"]
        title = f' "{title.replace(chr(34), chr(92) + chr(34))}"' if title else ""
        return f"]({href}{title})"

    # -- nodes --------------------------------------------------------------

    def node_blockquote(self, state, node, parent, index):
        state.wrap_block("> ", None, node, lambda: state.render_content(node))

    def node_code_block(self, state, node, parent, index):
        markup = node.attrs["markup"]
        text = node.text_content
        if self.o["preserve"] and markup == "indent" and text:
            state.wrap_block("    ", None, node, lambda: state.text(text, False))
            return
        base = (
            markup
            if self.o["preserve"] and markup and markup != "indent"
            else self.o["fence"]
        )
        ch = base[0]
        runs = re.findall(r"`{3,}" if ch == "`" else r"~{3,}", text, re.MULTILINE)
        fence = base
        if runs:
            longest = max(len(r) for r in runs)
            if longest >= len(fence):
                fence = ch * (longest + 1)
        state.write(f"{fence}{node.attrs['params'] or ''}\n")
        state.text(text, False)
        state.ensure_new_line()
        state.write(fence)
        state.close_block(node)

    def node_heading(self, state, node, parent, index):
        markup = node.attrs["markup"] if self.o["preserve"] else None
        if markup in {"=", "-"} and node.children:
            state.render_inline(node, False)
            state.ensure_new_line()
            state.write("===" if markup == "=" else "---")
            state.close_block(node)
            return
        state.write("#" * node.attrs["level"] + " ")
        state.render_inline(node, False)
        state.close_block(node)

    def node_horizontal_rule(self, state, node, parent, index):
        state.write(self.pick(node.attrs["markup"], self.o["hr"]))
        state.close_block(node)

    def node_bullet_list(self, state, node, parent, index):
        b = self.pick(node.attrs["markup"], self.o["bullet"])
        prev = parent.children[index - 1] if index > 0 else None
        if prev is not None and prev.type == node.type and self.used.get(id(prev)) == b:
            b = "*" if b == "-" else "-"
        self.used[id(node)] = b
        state.render_list(node, "  ", lambda i: f"{b} ")

    def node_ordered_list(self, state, node, parent, index):
        start = node.attrs["order"] if node.attrs["order"] is not None else 1
        delim = self.pick(node.attrs["markup"], ".")
        prev = parent.children[index - 1] if index > 0 else None
        if (
            prev is not None
            and prev.type == node.type
            and self.used.get(id(prev)) == delim
        ):
            delim = ")" if delim == "." else "."
        self.used[id(node)] = delim
        max_w = len(str(start + len(node.children) - 1))
        space = " " * (max_w + 2)

        def first(i):
            n = str(start + i)
            return " " * (max_w - len(n)) + n + delim + " "

        state.render_list(node, space, first)

    def node_list_item(self, state, node, parent, index):
        if node.attrs["checked"] is not None:
            state.write("[x] " if node.attrs["checked"] else "[ ] ")
        for i, child in enumerate(node.children):
            if i and state.in_tight_list and child.type != "paragraph":
                state.flush_close(
                    2
                    if child.type == "ordered_list" and child.attrs["order"] != 1
                    else 1
                )
            state.render(child, node, i)

    def node_paragraph(self, state, node, parent, index):
        state.render_inline(node)
        state.close_block(node)

    def node_image(self, state, node, parent, index):
        src = re.sub(
            r"[()\s]",
            lambda m: "%20" if m[0] == " " else "\\" + m[0],
            node.attrs["src"],
        )
        title = node.attrs["title"]
        title = f' "{title.replace(chr(34), chr(92) + chr(34))}"' if title else ""
        state.write(f"![{state.esc(node.attrs['alt'] or '')}]({src}{title})")

    def node_mention(self, state, node, parent, index):
        label = re.sub(r"[\\\[\]]", lambda m: "\\" + m[0], node.attrs["label"])
        state.write(f"[@{label}](person:{node.attrs['id']})")

    def node_hard_break(self, state, node, parent, index):
        for child in parent.children[index + 1 :]:
            if child.type != node.type:
                empty = index == 0 or parent.children[index - 1].type == node.type
                state.write("\\\n" if empty else "\n")
                return

    def node_text(self, state, node, parent, index):
        if index > 0 and parent.children[index - 1].type == "hard_break":
            state.at_block_start = True
        state.text(node.text, not state.in_autolink)

    def node_table(self, state, node, parent, index):
        rows = []
        for row in node.children:
            cells = []
            for cell in row.children:
                sub = State(self)
                sub.render_inline(cell.children[0])
                text = sub.out.replace("\n", " ").replace("|", "\\|")
                cells.append((text, cell.attrs["align"]))
            rows.append(cells)
        sep = {"left": ":---", "right": "---:", "center": ":---:"}

        def line(cells):
            return "| " + " | ".join(text for text, _ in cells) + " |"

        out = [
            line(rows[0]),
            "| " + " | ".join(sep.get(align, "---") for _, align in rows[0]) + " |",
            *(line(r) for r in rows[1:]),
        ]
        for i, text in enumerate(out):
            if i:
                state.ensure_new_line()
            state.write(text)
        state.close_block(node)


def serialize(doc: Node, **options):
    return Serializer(**options).serialize(doc)
