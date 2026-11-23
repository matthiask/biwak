"""The JavaScript and the Python side of the Markdown layer give the same
documents and the same Markdown, byte for byte (specs/rich-editor.md):
the corpus (``corpus/``) and random documents of the editor's schema,
through ``frontend/editor/tests/dump.js``. Needs Node and the
``node_modules`` (CI has both)."""

import base64
import json
import shutil
import subprocess
import tempfile
from functools import cache
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase
from pycrdt import Doc

from biwak.richtext import checklists
from biwak.richtext.parse import parse
from biwak.richtext.serialize import serialize
from biwak.richtext.ydoc import from_ydoc, to_ydoc


DUMP = Path(settings.BASE_DIR) / "frontend" / "editor" / "tests" / "dump.js"
NODE = shutil.which("node")


def node(*args):
    return json.loads(
        subprocess.run(
            [NODE, str(DUMP), *map(str, args)],
            check=True,
            capture_output=True,
            text=True,
            cwd=settings.BASE_DIR,
        ).stdout
    )


@cache
def dump():
    return node(300)


def sorted_json(data):
    return json.dumps(data, sort_keys=True)


def ydoc(encoded):
    doc = Doc()
    doc.apply_update(base64.b64decode(encoded))
    return doc


def available():
    return NODE is not None and (Path(settings.BASE_DIR) / "node_modules").exists()


class ParityTest(SimpleTestCase):
    def setUp(self):
        if not available():
            self.skipTest("Node or node_modules missing")

    def test_corpus_parses_alike(self):
        for entry in dump()["corpus"]:
            text = (Path(__file__).parent / "corpus" / entry["name"]).read_text()
            with self.subTest(entry["name"]):
                self.assertEqual(
                    sorted_json(parse(text).to_json()), sorted_json(entry["doc"])
                )

    def test_corpus_serializes_alike(self):
        for entry in dump()["corpus"]:
            text = (Path(__file__).parent / "corpus" / entry["name"]).read_text()
            with self.subTest(entry["name"]):
                self.assertEqual(serialize(parse(text)), entry["markdown"])

    def test_checklist_positions(self):
        """The boxes of the editor are the server's boxes, also after
        saving"""
        for entry in dump()["corpus"]:
            text = (Path(__file__).parent / "corpus" / entry["name"]).read_text()
            with self.subTest(entry["name"]):
                for markdown in (text, entry["markdown"]):
                    found = checklists.boxes(checklists._parse(markdown))
                    self.assertEqual([c for _line, c in found], entry["boxes"])

    def test_y_documents_of_the_browser(self):
        """y-prosemirror's documents read with pycrdt"""
        for entry in dump()["corpus"]:
            with self.subTest(entry["name"]):
                self.assertEqual(
                    serialize(from_ydoc(ydoc(entry["y"]))), entry["ymarkdown"]
                )

    def test_random_documents(self):
        for i, entry in enumerate(dump()["random"]):
            with self.subTest(i):
                self.assertEqual(
                    serialize(from_ydoc(ydoc(entry["y"]))), entry["markdown"]
                )
                self.assertEqual(serialize(parse(entry["markdown"])), entry["again"])

    def test_y_documents_of_the_server(self):
        """Python's documents read by y-prosemirror"""
        corpus = dump()["corpus"]
        with tempfile.TemporaryDirectory() as tmp:
            for i, entry in enumerate(corpus):
                text = (Path(__file__).parent / "corpus" / entry["name"]).read_text()
                Path(tmp, f"{i:03}.bin").write_bytes(to_ydoc(parse(text)).get_update())
            loaded = node("load", tmp)
        for i, entry in enumerate(corpus):
            with self.subTest(entry["name"]):
                self.assertEqual(loaded[f"{i:03}.bin"]["markdown"], entry["ymarkdown"])
