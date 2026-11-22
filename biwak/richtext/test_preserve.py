from django.test import SimpleTestCase

from biwak.richtext.parse import parse
from biwak.richtext.preserve import to_markdown
from biwak.richtext.serialize import serialize


OLD = """Intro with __old__ style
and a second line.

* a
* b

Last paragraph."""


class PreserveTest(SimpleTestCase):
    def test_unchanged_document_keeps_the_text(self):
        for text in [OLD, "Hello\r\n", "a\n\n\n\nb\n", "+ x\n+ y\n"]:
            self.assertEqual(to_markdown(parse(text), text), text)

    def test_changed_block_only(self):
        doc = parse(OLD.replace("Last paragraph.", "Last *one*."))
        self.assertEqual(
            to_markdown(doc, OLD),
            "Intro with __old__ style\nand a second line.\n\n* a\n* b\n\nLast *one*.",
        )

    def test_new_text(self):
        doc = parse("_new_")
        self.assertEqual(to_markdown(doc), "_new_")
        self.assertEqual(to_markdown(doc, ""), serialize(doc))

    def test_adjacent_lists(self):
        old = "- a\n\nText"
        doc = parse("- a\n\n* b")
        self.assertEqual(to_markdown(doc, old), serialize(doc))
        self.assertEqual(parse(to_markdown(doc, old)), doc)
