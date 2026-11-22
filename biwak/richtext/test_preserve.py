from django.test import SimpleTestCase

from biwak.richtext.parse import parse
from biwak.richtext.preserve import keep_source, to_markdown
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


class KeepSourceTest(SimpleTestCase):
    def test_same_meaning_is_the_old_text(self):
        self.assertEqual(
            keep_source("Intro _x_\n\n* a", "Intro _x_\n* a"), "Intro _x_\n* a"
        )

    def test_unchanged_blocks_keep_their_source(self):
        old = "Intro with __old__ style\n* a\n* b\n\nEnd"
        new = "Intro with __old__ style\n\n* a\n* b\n\nEnding"
        self.assertEqual(
            keep_source(new, old), "Intro with __old__ style\n* a\n* b\n\nEnding"
        )

    def test_new_and_empty(self):
        self.assertEqual(keep_source("x", ""), "x")
        self.assertEqual(keep_source("", "x"), "")
        self.assertEqual(keep_source("all *new*", "old"), "all *new*")

    def test_a_kept_block_that_would_change_meaning(self):
        # The kept "* a" list next to a new "* b" list would merge
        old = "* a\n\ntext"
        new = "- a\n\n* b"
        self.assertEqual(keep_source(new, old), new)


class EdgesTest(SimpleTestCase):
    def test_the_end_of_an_unchanged_last_block(self):
        old = "Packing\n\n- [ ] tent\n- [ ] rope\n"
        doc = parse("Packing Trip\n\n- [ ] tent\n- [ ] rope")
        self.assertEqual(
            to_markdown(doc, old), "Packing Trip\n\n- [ ] tent\n- [ ] rope\n"
        )
        self.assertEqual(
            keep_source("Packing Trip\n\n- [ ] tent\n- [ ] rope", old),
            "Packing Trip\n\n- [ ] tent\n- [ ] rope\n",
        )

    def test_a_block_after_the_old_last_one(self):
        self.assertEqual(
            to_markdown(parse("Agenda\n\nMore"), "Agenda\n"), "Agenda\n\nMore\n"
        )
        self.assertEqual(
            to_markdown(parse("Before\n\nAgenda"), "\nAgenda"), "Before\n\nAgenda"
        )
