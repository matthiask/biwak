"""Pasting rich text: the converter on fixtures (made up, shaped like a
mail and a Google Docs fragment) and the endpoint (specs/editor.md)"""

from pathlib import Path

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from biwak.htmlmarkdown import from_clipboard
from biwak.test_utils import person


# Clipboard HTML as the browsers send it, one line (.txt: formatters leave
# it alone)
FIXTURES = Path(__file__).parent / "test_fixtures"

MAIL = """Hi team,

The **tent** is ordered, see [the shop](https://shop.example.org/tent?id=7). Still *open*:

- stove
- rope
  - 10 m

Ada wrote:

> Can we leave on Friday?

--
Bob Example"""

GOOGLE_DOCS = """# Camp plan

**Important:** bring *warm* clothes, see [the gear list](https://example.org/gear).

- Tent
- Stove

1. Pitch it
2. Eat

| **Item** | **Who** |
| --- | --- |
| Tent | Ada |

`npm start`"""


class ConverterTest(SimpleTestCase):
    def test_a_mail(self):
        self.assertEqual(
            from_clipboard((FIXTURES / "paste_mail.txt").read_text()), MAIL
        )

    def test_google_docs(self):
        self.assertEqual(
            from_clipboard((FIXTURES / "paste_google_docs.txt").read_text()),
            GOOGLE_DOCS,
        )

    def test_task_lists(self):
        self.assertEqual(
            from_clipboard(
                "<ul><li><input type=checkbox checked> done</li>"
                '<li class="task-list-item"><input type="checkbox" disabled> open'
                "<ul><li>nested</li></ul></li></ul>"
            ),
            "- [x] done\n- [ ] open\n  - nested",
        )

    def test_code(self):
        self.assertEqual(
            from_clipboard("<pre><code>a\n  b</code></pre><p>use <code>x</code></p>"),
            "```\na\n  b\n```\n\nuse `x`",
        )

    def test_nothing_unsafe_survives(self):
        text = from_clipboard(
            "<p>a <script>alert(1)</script><style>p{}</style>"
            '<a href="javascript:alert(1)">bad</a> '
            '<a href="attachment:abc123">file</a> '
            '<a href="/relative">rel</a> '
            '<img src="https://example.com/x.png" alt="pic"> '
            '<span style="color:red;font-family:Comic Sans">plain</span> '
            '<font color="red">font</font> <u>under</u></p>'
        )
        self.assertEqual(text, "a bad file rel  plain font under")

    def test_underscores_and_stars_are_text(self):
        self.assertEqual(from_clipboard("<p>a_b *c*</p>"), "a\\_b \\*c\\*")

    def test_whitespace(self):
        self.assertEqual(
            from_clipboard("<p>a&nbsp;b</p><p><br></p><p><br></p><p>c</p>"), "a b\n\nc"
        )

    def test_nothing(self):
        for html in ["", None, "  ", "<p></p>"]:
            self.assertEqual(from_clipboard(html), "")


class EndpointTest(TestCase):
    def post(self, html):
        return self.client.post(reverse("paste_markdown"), {"html": html})

    def test_staff_and_clients_convert(self):
        for user in [person("Ada"), person("Cleo", client=True)]:
            self.client.force_login(user)
            response = self.post("<p>Hello <b>you</b></p>")
            self.assertEqual(response.json(), {"markdown": "Hello **you**"})

    def test_needs_a_login(self):
        response = self.post("<p>x</p>")
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

    def test_post_only(self):
        self.client.force_login(person("Ada"))
        self.assertEqual(self.client.get(reverse("paste_markdown")).status_code, 405)

    def test_nothing_sent(self):
        self.client.force_login(person("Ada"))
        self.assertEqual(
            self.client.post(reverse("paste_markdown")).json(), {"markdown": ""}
        )
