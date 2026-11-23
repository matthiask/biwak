"""Edits from elsewhere keep what people type at the same time
(specs/rich-editor.md, the spike's table): the server's state has the
last saved text, editors type (not saved yet), the API saves a new text
made from the saved one; everything merged keeps both."""

import tempfile
from pathlib import Path

from django.test import SimpleTestCase
from pycrdt import Doc, XmlFragment, XmlText

from biwak.richtext.checklists import tick
from biwak.richtext.diff import document, edit
from biwak.richtext.parse import parse
from biwak.richtext.serialize import serialize
from biwak.richtext.test_parity import available, node
from biwak.richtext.ydoc import FRAGMENT, to_ydoc


M0 = """# Weekly meeting

Present: Ada, Bob and Cleo.

## Decisions

- We launch on Monday.
- The budget stays.

## To-dos

- [ ] Ada sends the offer
- [ ] Bob books the room
- [ ] Ask the client about the logo

Next meeting: **Thursday** at 10."""

# Blocks: 0 h1, 1 present, 2 h2, 3 decisions list, 4 h2, 5 to-dos, 6 next
SCENARIOS = [
    (
        "different blocks",
        M0,
        [[([1], -1, " Dan joined late.")]],
        M0.replace("at 10.", "at 11."),
        ["Dan joined late", "at 11."],
    ),
    (
        "a tick in a list while typing in another item",
        M0,
        [[([5, 0, 0], -1, " by Friday")]],
        tick(M0, 2, checked=True),
        ["Ada sends the offer by Friday", "[x] Ask the client"],
    ),
    (
        "the same paragraph: typing at its end, the API changes its start",
        M0,
        [[([1], -1, " Dan joined late.")]],
        M0.replace("Present: Ada", "Present: Ada Example"),
        ["Dan joined late", "Present: Ada Example"],
    ),
    (
        "the same list item",
        M0,
        [[([5, 1, 0], -1, " for Tuesday")]],
        M0.replace("Bob books the room", "Bob books the big room"),
        ["big room for Tuesday"],
    ),
    (
        "the API adds a paragraph before",
        M0,
        [[([6], -1, " Room 3.")]],
        M0.replace("Next meeting", "Lunch after.\n\nNext meeting"),
        ["Lunch after.", "at 10. Room 3."],
    ),
    (
        "two typing in one paragraph, the API elsewhere",
        M0,
        [[([1], -1, " (A)")], [([1], 0, "(B) ")]],
        M0.replace("We launch on Monday", "We launch on Tuesday"),
        ["(B) Present", "Cleo. (A)", "Tuesday"],
    ),
    (
        "the API makes a word bold in the typed paragraph",
        M0,
        [[([1], -1, " Dan too.")]],
        M0.replace("Bob and Cleo", "**Bob** and Cleo"),
        ["**Bob** and Cleo", "Dan too."],
    ),
    (
        "a paragraph with a mention: the API changes text after it",
        "Thanks [@Ada](person:12) for the plan.",
        [[([0], 0, "Big ")]],
        "Thanks [@Ada](person:12) for the new plan.",
        ["Big Thanks [@Ada](person:12) for the new plan."],
    ),
    (
        "a paragraph with a mention: the API adds one",
        "Ask Bob about it.",
        [[([0], -1, " Soon!")]],
        "Ask Bob and [@Cleo](person:3) about it.",
        ["Ask Bob and [@Cleo](person:3) about it. Soon!"],
    ),
    (
        "a paragraph with a break and an image",
        "Line one\nline two ![plan.png](attachment:ab12) end",
        [[([0], 0, "First: ")]],
        "Line one\nline 2 ![plan.png](attachment:ab12) end",
        ["First: Line one\nline 2 ![plan.png](attachment:ab12) end"],
    ),
    (
        "outside the Basic Plane: positions in UTF-8 and UTF-16",
        "Grüße 😀 und mehr",
        [[([0], -1, " 🏔️")]],
        "Grüße 😀😀 and more",
        ["Grüße 😀😀 and more 🏔️"],
    ),
]


def element(fragment, path):
    el = fragment
    for i in path:
        el = el.children[i]
    return el


def typing(state, ops):
    """An editor's update: ``ops`` are (path to a textblock, character
    offset or -1 for the end, text), typed into its first text"""
    doc = Doc()
    doc.apply_update(state)
    fragment = doc.get(FRAGMENT, type=XmlFragment)
    before = doc.get_state()
    for path, offset, text in ops:
        block = element(fragment, path)
        ytext = next(c for c in block.children if isinstance(c, XmlText))
        value = (
            str(ytext) if not ytext.diff()[1:] else "".join(t for t, _ in ytext.diff())
        )
        at = len(value.encode()) if offset < 0 else len(value[:offset].encode())
        ytext.insert(at, text)
    return doc.get_update(before)


def merged(state, updates):
    doc = Doc()
    for update in [state, *updates]:
        doc.apply_update(update)
    return doc


class DeepDiffTest(SimpleTestCase):
    def test_scenarios(self):
        for name, m0, typed, m1, expected in SCENARIOS:
            with self.subTest(name):
                server = to_ydoc(parse(m0))
                state = server.get_update()
                updates = [typing(state, ops) for ops in typed]
                api = edit(server, m1)
                self.assertTrue(api)
                result = serialize(document(merged(state, [*updates, api])))
                for text in expected:
                    self.assertIn(text, result)

    def test_nothing_changed_is_no_update(self):
        server = to_ydoc(parse(M0))
        self.assertEqual(edit(server, M0), b"")

    def test_a_tick_is_an_attribute(self):
        server = to_ydoc(parse(M0))
        update = edit(server, tick(M0, 0, checked=True))
        self.assertLess(len(update), 60)
        self.assertEqual(serialize(document(server)), tick(M0, 0, checked=True))

    def test_the_deleted_block_loses_the_typing(self):
        """Accepted (decided 2026-11-22)"""
        server = to_ydoc(parse(M0))
        state = server.get_update()
        typed = typing(state, [([6], 0, "Moved! ")])
        api = edit(server, M0.replace("\n\nNext meeting: **Thursday** at 10.", ""))
        result = serialize(document(merged(state, [typed, api])))
        self.assertNotIn("Next meeting", result)

    def test_y_prosemirror_reads_the_merged_documents(self):
        """Every merged state is a valid document for y-prosemirror, which
        serializes it like Python"""
        if not available():
            self.skipTest("Node or node_modules missing")
        results = {}
        with tempfile.TemporaryDirectory() as tmp:
            for i, (_name, m0, typed, m1, _expected) in enumerate(SCENARIOS):
                server = to_ydoc(parse(m0))
                state = server.get_update()
                updates = [typing(state, ops) for ops in typed]
                api = edit(server, m1)
                doc = merged(state, [*updates, api])
                results[f"{i:03}.bin"] = serialize(document(doc))
                Path(tmp, f"{i:03}.bin").write_bytes(doc.get_update())
            loaded = node("load", tmp)
        for name, markdown in results.items():
            self.assertEqual(loaded[name]["markdown"], markdown)
