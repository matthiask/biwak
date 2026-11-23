from django.test import SimpleTestCase

from biwak.richtext import checklists
from biwak.templatetags.biwak import mail_markdown, render_markdown


TEXT = """Plan

- [ ] first
- [x] second
  - [ ] nested
1. [X] numbered

```
- [ ] in code
```

- not a task
"""


class CountTest(SimpleTestCase):
    def test_counts(self):
        self.assertEqual(checklists.count(TEXT), (2, 4))

    def test_no_checklist(self):
        for text in ["", None, "- plain [ ] item", "[ ] not in a list", "- [] x"]:
            self.assertEqual(checklists.count(text), (0, 0), text)

    def test_quote(self):
        self.assertEqual(checklists.count("> - [x] a\n> - [ ] b"), (1, 2))


class TickTest(SimpleTestCase):
    def test_toggles_exactly_one_box(self):
        self.assertEqual(
            checklists.tick(TEXT, 0), TEXT.replace("- [ ] first", "- [x] first")
        )
        self.assertEqual(
            checklists.tick(TEXT, 1), TEXT.replace("- [x] second", "- [ ] second")
        )
        self.assertEqual(
            checklists.tick(TEXT, 3), TEXT.replace("1. [X] numbered", "1. [ ] numbered")
        )

    def test_set_explicitly(self):
        self.assertEqual(checklists.tick("- [x] a", 0, checked=True), "- [x] a")
        self.assertEqual(checklists.tick("- [ ] a", 0, checked=True), "- [x] a")

    def test_code_is_not_a_box(self):
        with self.assertRaises(checklists.NoCheckbox):
            checklists.tick(TEXT, 4)
        with self.assertRaises(checklists.NoCheckbox):
            checklists.tick("text", 0)

    def test_windows_line_endings_kept(self):
        text = "Intro\r\n\r\n- [ ] a\r\n- [ ] b\r\n"
        self.assertEqual(
            checklists.tick(text, 1), "Intro\r\n\r\n- [ ] a\r\n- [x] b\r\n"
        )

    def test_quote(self):
        self.assertEqual(checklists.tick("> - [ ] a", 0), "> - [x] a")


class HashTest(SimpleTestCase):
    def test_hash_follows_the_text(self):
        self.assertEqual(checklists.text_hash("a"), checklists.text_hash("a"))
        self.assertNotEqual(checklists.text_hash("a"), checklists.text_hash("b"))
        self.assertEqual(checklists.text_hash(None), checklists.text_hash(""))


class RenderTest(SimpleTestCase):
    def test_disabled_numbered_checkboxes(self):
        html = str(render_markdown("- [ ] a\n- [x] b"))
        self.assertIn('data-index="0" aria-label="a" disabled>', html)
        self.assertIn('data-index="1" aria-label="b" checked disabled>', html)
        self.assertIn("contains-task-list", html)

    def test_named_by_their_line(self):
        html = str(render_markdown('- [ ] Buy "pegs" & `rope`'))
        self.assertIn('aria-label="Buy &quot;pegs&quot; &amp; rope"', html)

    def test_tickable(self):
        html = str(render_markdown("- [ ] a", tickable=True))
        self.assertNotIn("disabled", html)

    def test_mail_glyphs(self):
        html = str(mail_markdown("- [ ] a\n- [x] b"))
        self.assertNotIn("<input", html)
        self.assertIn("☐", html)
        self.assertIn("☑", html)
