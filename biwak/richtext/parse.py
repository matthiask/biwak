"""Markdown into the editor's document with markdown-it-py, configured like
``render_markdown`` and like the browser's parser
(``frontend/editor/markdown.js``): task lists and mentions by the same
rules, the same document for the same text"""

import re

from markdown_it import MarkdownIt
from markdown_it.token import Token

from .tree import Mark, Node, Text, join_texts, sort_marks


TODO = re.compile(r"^\[[ xX]\][ \t\n\v\f\r]+")
BOX = re.compile(r"^\[[ xX]\] ")
PERSON = re.compile(r"^person:(\d+)$")


def _tasklists(state):
    tokens = state.tokens
    for i in range(2, len(tokens) - 1):
        t = tokens[i]
        if (
            t.type == "inline"
            and tokens[i - 1].type == "paragraph_open"
            and tokens[i - 2].type == "list_item_open"
            and TODO.match(t.content)
            and BOX.match(t.content)
        ):
            m = TODO.match(t.content)
            tokens[i - 2].meta = {"checked": m[0][1] != " "}
            first = t.children[0] if t.children else None
            if first is not None and first.type == "text":
                first.content = first.content[3:].lstrip(" \t")
            t.content = t.content[len(m[0]) :]


def _mentions(state):
    for block in state.tokens:
        if block.type != "inline" or not block.children:
            continue
        out, c, i = [], block.children, 0
        while i < len(c):
            t = c[i]
            m = t.type == "link_open" and PERSON.match(t.attrGet("href") or "")
            if (
                not m
                or i + 1 >= len(c)
                or c[i + 1].type != "text"
                or not c[i + 1].content.startswith("@")
            ):
                out.append(t)
                i += 1
                continue
            end = i + 1
            while c[end].type != "link_close":
                end += 1
            label = "".join(x.content for x in c[i + 1 : end])
            mention = Token("mention", "", 0)
            mention.meta = {"id": m[1], "label": label.removeprefix("@")}
            out.append(mention)
            i = end + 1
        block.children = out


def markdown_it():
    md = MarkdownIt("commonmark", {"html": False, "linkify": True, "breaks": True})
    md.enable(["linkify", "strikethrough", "table"])
    md.core.ruler.after("inline", "github-tasklists", _tasklists)
    md.core.ruler.push("mentions", _mentions)
    return md


_md = markdown_it()


class _State:
    """prosemirror-markdown's MarkdownParseState"""

    def __init__(self):
        self.stack = [{"type": "doc", "attrs": {}, "content": [], "marks": []}]

    def top(self):
        return self.stack[-1]

    def add_text(self, text):
        if not text:
            return
        nodes = self.top()["content"]
        marks = list(self.top()["marks"])
        last = nodes[-1] if nodes else None
        if last is not None and last.is_text and last.marks == sort_marks(marks):
            nodes[-1] = last.with_text(last.text + text)
        else:
            nodes.append(Text(text, marks))

    def open_mark(self, mark):
        top = self.top()
        top["marks"] = [m for m in top["marks"] if m.type != mark.type] + [mark]

    def close_mark(self, mark_type):
        top = self.top()
        top["marks"] = [m for m in top["marks"] if m.type != mark_type]

    def add_node(self, type, attrs=None, content=None):
        node = Node(type, attrs, join_texts(content or []))
        if node.is_inline:
            node.marks = list(self.top()["marks"])
        self.top()["content"].append(node)
        return node

    def open_node(self, type, attrs=None):
        self.stack.append({
            "type": type,
            "attrs": attrs or {},
            "content": [],
            "marks": [],
        })

    def close_node(self):
        info = self.stack.pop()
        return self.add_node(info["type"], info["attrs"], info["content"])


def _list_is_tight(tokens, i):
    i += 1
    while i < len(tokens):
        if tokens[i].type != "list_item_open":
            return tokens[i].hidden
        i += 1
    return False


def _align(tok):
    m = re.search(r"text-align:(\w+)", tok.attrGet("style") or "")
    return m[1] if m else None


def _tokens(state, tokens):  # noqa: C901 (one branch per token type)
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        t = tok.type
        if t == "inline":
            _tokens(state, tok.children or [])
        elif t == "text":
            state.add_text(tok.content)
        elif t in {"softbreak", "hardbreak"}:
            state.add_node("hard_break")
        elif t in {"paragraph_open", "blockquote_open", "tr_open", "table_open"}:
            state.open_node(
                {
                    "paragraph_open": "paragraph",
                    "blockquote_open": "blockquote",
                    "tr_open": "table_row",
                    "table_open": "table",
                }[t]
            )
        elif t in {
            "paragraph_close",
            "blockquote_close",
            "tr_close",
            "table_close",
            "bullet_list_close",
            "ordered_list_close",
            "list_item_close",
            "heading_close",
        }:
            state.close_node()
        elif t in {"thead_open", "thead_close", "tbody_open", "tbody_close"}:
            pass
        elif t in {"th_open", "td_open"}:
            state.open_node(
                "table_header" if t == "th_open" else "table_cell",
                {"align": _align(tok)},
            )
            state.open_node("paragraph")
        elif t in {"th_close", "td_close"}:
            state.close_node()
            state.close_node()
        elif t == "list_item_open":
            state.open_node("list_item", {"checked": (tok.meta or {}).get("checked")})
        elif t == "bullet_list_open":
            state.open_node(
                "bullet_list",
                {"tight": _list_is_tight(tokens, i), "markup": tok.markup},
            )
        elif t == "ordered_list_open":
            state.open_node(
                "ordered_list",
                {
                    "order": int(tok.attrGet("start") or 1) or 1,
                    "tight": _list_is_tight(tokens, i),
                    "markup": tok.markup,
                },
            )
        elif t == "heading_open":
            state.open_node(
                "heading", {"level": int(tok.tag[1:]), "markup": tok.markup}
            )
        elif t in {"code_block", "fence"}:
            content = tok.content.removesuffix("\n")
            attrs = (
                {"markup": "indent"}
                if t == "code_block"
                else {"params": tok.info or "", "markup": tok.markup}
            )
            state.open_node("code_block", attrs)
            state.add_text(content)
            state.close_node()
        elif t == "hr":
            # markdown-it-py 4.3 writes one character too many (JS: as many
            # as the line has)
            state.add_node("horizontal_rule", {"markup": tok.markup[:-1]})
        elif t == "image":
            # A linked image: the link is the image's attribute, not a mark
            marks = state.top()["marks"]
            link = next((m for m in marks if m.type == "link"), None)
            state.top()["marks"] = [m for m in marks if m.type != "link"]
            state.add_node(
                "image",
                {
                    "src": tok.attrGet("src"),
                    "title": tok.attrGet("title") or None,
                    "alt": "".join(c.content for c in tok.children or []) or None,
                    "href": link.attrs["href"] if link else None,
                    "hrefTitle": link.attrs["title"] if link else None,
                },
            )
            state.top()["marks"] = marks
        elif t == "mention":
            state.add_node("mention", tok.meta)
        elif t in {"em_open", "strong_open"}:
            state.open_mark(Mark(t[:-5], {"markup": tok.markup}))
        elif t in {"em_close", "strong_close", "s_close", "link_close"}:
            state.close_mark({"s_close": "strikethrough"}.get(t, t[:-6]))
        elif t == "s_open":
            state.open_mark(Mark("strikethrough"))
        elif t == "link_open":
            markup = tok.markup if tok.markup in {"linkify", "autolink"} else None
            state.open_mark(
                Mark(
                    "link",
                    {
                        "href": tok.attrGet("href"),
                        "title": tok.attrGet("title") or None,
                        "markup": markup,
                    },
                )
            )
        elif t == "code_inline":
            state.open_mark(Mark("code"))
            state.add_text(tok.content)
            state.close_mark("code")
        elif t == "text_special":
            state.add_text(tok.content)
        else:
            raise ValueError(f"Unknown token {t}")
        i += 1


def parse(text):
    state = _State()
    _tokens(state, _md.parse(text or ""))
    while len(state.stack) > 1:
        state.close_node()
    info = state.stack[0]
    doc = Node("doc", {}, join_texts(info["content"]))
    if not doc.children:
        doc.children = [Node("paragraph")]
    return doc
