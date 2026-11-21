"""Django's {# #} comments end on their line: one spanning lines shows on
the page. Longer comments are {% comment %} blocks."""

from pathlib import Path

from django.test import SimpleTestCase


TEMPLATES = Path(__file__).parent / "templates"


class TemplateCommentTest(SimpleTestCase):
    def test_no_comment_spans_lines(self):
        broken = [
            f"{path.relative_to(TEMPLATES)}:{number}"
            for path in sorted(TEMPLATES.rglob("*.html"))
            for number, line in enumerate(path.read_text().splitlines(), 1)
            if line.count("{#") > line.count("#}")
        ]
        self.assertEqual(broken, [])
