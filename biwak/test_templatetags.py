import datetime as dt

import time_machine
from django.template import Context, Template
from django.test import TestCase
from django.utils import timezone, translation
from django.utils.html import strip_tags

from biwak.items import operations as ops
from biwak.templatetags.biwak import excerpt
from biwak.test_utils import person, project


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


class MomentTest(TestCase):
    """One rule for moments (decided 2026-11-22, specs/ui.md): relative
    within seven days, then the date, the exact time on hover"""

    def moment(self, delta, arg=""):
        return Template("{% load biwak %}{{ when|moment" + arg + " }}").render(
            Context({"when": timezone.now() - delta})
        )

    def text(self, delta, arg=""):
        return strip_tags(self.moment(delta, arg))

    def test_under_a_minute_is_just_now_never_0_minutes(self):
        self.assertEqual(self.text(dt.timedelta(0)), "just now")
        self.assertEqual(self.text(dt.timedelta(seconds=59)), "just now")

    def test_longer_ago(self):
        self.assertEqual(self.text(dt.timedelta(minutes=5)), "5\xa0minutes ago")
        self.assertEqual(self.text(dt.timedelta(hours=3)), "3\xa0hours ago")
        self.assertEqual(self.text(dt.timedelta(days=6, hours=23)), "6\xa0days ago")

    def test_one_unit_only(self):
        # Decided 2026-11-22: "13 hours ago", not "13 hours, 37 minutes ago"
        self.assertEqual(
            self.text(dt.timedelta(hours=13, minutes=37)), "13\xa0hours ago"
        )

    @time_machine.travel(dt.datetime(2026, 11, 22, 12, tzinfo=dt.UTC), tick=False)
    def test_the_date_from_seven_days_on(self):
        self.assertEqual(self.text(dt.timedelta(days=7)), "15 Nov 2026")
        self.assertEqual(self.text(dt.timedelta(days=400)), "18 Oct 2025")

    @time_machine.travel(dt.datetime(2026, 11, 22, 12, tzinfo=dt.UTC), tick=False)
    def test_on_for_sentences(self):
        self.assertEqual(self.text(dt.timedelta(days=9), ':"on"'), "on 13 Nov 2026")
        self.assertEqual(self.text(dt.timedelta(days=2), ':"on"'), "2\xa0days ago")

    @time_machine.travel(dt.datetime(2026, 11, 22, 12, tzinfo=dt.UTC), tick=False)
    def test_the_exact_time_on_hover(self):
        html = self.moment(dt.timedelta(hours=3))
        self.assertIn('datetime="2026-11-22T09:00:00+00:00"', html)
        self.assertIn('title="Sun, 22 Nov 2026, 10:00"', html)  # Zurich
        self.assertTrue(html.startswith("<time "))

    @time_machine.travel(dt.datetime(2026, 11, 22, 12, tzinfo=dt.UTC), tick=False)
    def test_german(self):
        with translation.override("de"):
            self.assertEqual(self.text(dt.timedelta(days=2)), "vor 2\xa0Tagen")
            self.assertEqual(
                self.text(dt.timedelta(days=9), ':"on"'), "am 13. Nov. 2026"
            )

    def test_nothing_for_none(self):
        html = Template("{% load biwak %}{{ when|moment }}").render(
            Context({"when": None})
        )
        self.assertEqual(html, "")

    def test_a_project_pages_activity(self):
        ada = person("Ada")
        self.client.force_login(ada)
        shared = project(members=[ada])
        ops.create_list(project=shared, title="Launch", creator=ada)
        with time_machine.travel(timezone.now(), tick=False) as traveller:
            html = self.client.get(shared.get_absolute_url()).content.decode()
            self.assertIn("just now", html)
            self.assertNotIn("0\xa0minutes", html)
            traveller.shift(dt.timedelta(minutes=5))
            html = self.client.get(shared.get_absolute_url()).content.decode()
            self.assertIn("5\xa0minutes ago", html)


class ExternalLinksTest(TestCase):
    def test_links_to_other_sites_open_in_a_new_tab(self):
        from biwak.templatetags.biwak import render_markdown

        html = render_markdown("[x](https://example.com) and [y](/projects/)")
        self.assertIn(
            '<a href="https://example.com" target="_blank" rel="noopener noreferrer">x',
            html,
        )
        self.assertIn('<a href="/projects/">y', html)
