from django.template import Context, Template
from django.test import TestCase

from biwak.templatetags.biwak import excerpt


class ExcerptTest(TestCase):
    def test_markdown_becomes_plain_text(self):
        self.assertEqual(
            excerpt("# Title\n\nSome **bold** and a [link](https://example.org)."),
            "Title Some bold and a link.",
        )

    def test_images_and_attachments(self):
        self.assertEqual(
            excerpt("Before ![alt](https://example.org/a.png) after"), "Before after"
        )
        self.assertEqual(excerpt("See [the file](attachment:abc123)"), "See the file")

    def test_whitespace_collapsed(self):
        self.assertEqual(excerpt("a\n\n\n  b\tc"), "a b c")

    def test_short_text_untouched(self):
        self.assertEqual(excerpt("Short", 200), "Short")
        self.assertEqual(excerpt("", 200), "")
        self.assertEqual(excerpt(None, 200), "")

    def test_cut_at_word_boundary(self):
        self.assertEqual(excerpt("one two three four", 10), "one two…")
        self.assertEqual(excerpt("one two three four", 9), "one two…")
        # Exactly at a boundary
        self.assertEqual(excerpt("one two three", 7), "one two…")

    def test_long_word_is_cut_hard(self):
        self.assertEqual(excerpt("x" * 50, 10), "x" * 10 + "…")

    def test_html_is_escaped(self):
        self.assertEqual(
            excerpt("<script>alert(1)</script> hi & bye"),
            "<script>alert(1)</script> hi & bye",
        )
        html = Template("{% load biwak %}{{ text|excerpt:100 }}").render(
            Context({"text": "<b>x</b> <script>alert(1)</script> &"})
        )
        self.assertNotIn("<script>", html)
        self.assertNotIn("<b>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_filter_in_template(self):
        html = Template("{% load biwak %}{{ text|excerpt:6 }}").render(
            Context({"text": "alpha beta gamma"})
        )
        self.assertEqual(html, "alpha…")
