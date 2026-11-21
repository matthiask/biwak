from django.test import SimpleTestCase

from biwak.files.titles import doc_title, with_heading


class DocTitleTest(SimpleTestCase):
    def test_a_heading_of_any_level(self):
        self.assertEqual(doc_title("# Minutes\n\ntext"), "Minutes")
        self.assertEqual(doc_title("### Minutes ##\n"), "Minutes")

    def test_else_the_first_line_as_plain_text(self):
        self.assertEqual(
            doc_title("Some **bold** [link](/x) words\nmore"), "Some bold link words"
        )
        self.assertEqual(doc_title("#tag is no heading"), "#tag is no heading")

    def test_leading_empty_lines_are_skipped(self):
        self.assertEqual(doc_title("\n  \n# Late"), "Late")

    def test_empty_is_untitled(self):
        for text in ["", "  \n\n", "# ", None]:
            self.assertEqual(doc_title(text), "Untitled")

    def test_a_long_line_is_cut_at_a_word(self):
        title = doc_title("# " + "word " * 200)
        self.assertLessEqual(len(title), 500)
        self.assertTrue(title.endswith("word…"))
        self.assertEqual(len(doc_title("x" * 700)), 500)

    def test_with_heading(self):
        self.assertEqual(with_heading("A  title", "Body"), "# A title\n\nBody")
        self.assertEqual(with_heading("T"), "# T\n\n")
