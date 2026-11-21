from django.test import SimpleTestCase

from biwak.importer.convert import Resolver, to_markdown


class Known(Resolver):
    def mention(self, sgid, label):
        return f"[@{label} Example](person:5)" if sgid == "S" else None

    def attachment(self, element):
        if element.get("sgid") == "IMG":
            return "![a.png](attachment:abc)"
        if element.get("sgid") == "FILE":
            return "[b.pdf](attachment:def)"
        return None

    def link(self, href):
        return "/todos/9/" if href.endswith("/todos/1") else href


MENTION = (
    '<bc-attachment sgid="S" content-type="application/vnd.basecamp.mention">'
    '<figure><img class="avatar" src="x"><figcaption>Ada</figcaption></figure>'
    "</bc-attachment>"
)


class ConvertTest(SimpleTestCase):
    def test_basics(self):
        html = (
            "<div>Hello <strong>you</strong> and <em>all</em>,<br><br>"
            '<a href="https://example.org">link</a></div>'
            "<div><ul><li>one</li><li>two</li></ul></div>"
            "<div><ol><li>first</li></ol></div>"
            "<h1>Title</h1><blockquote>quoted</blockquote><pre>code</pre>"
        )
        self.assertEqual(
            to_markdown(html),
            "Hello **you** and *all*,\n\n[link](https://example.org)\n\n"
            "- one\n- two\n\n1. first\n\n# Title\n\n> quoted\n\n```\ncode\n```",
        )

    def test_empty(self):
        self.assertEqual(to_markdown(""), "")
        self.assertEqual(to_markdown(None), "")
        self.assertEqual(to_markdown("<div> </div>"), "")

    def test_mentions(self):
        self.assertEqual(
            to_markdown(f"<div>Hi {MENTION}!</div>", Known()),
            "Hi [@Ada Example](person:5)!",
        )

    def test_an_unknown_mention_stays_readable(self):
        self.assertEqual(to_markdown(f"<div>Hi {MENTION}!</div>"), "Hi @Ada!")

    def test_attachments(self):
        html = (
            '<bc-attachment sgid="IMG" content-type="image/png" filename="a.png">'
            "<figure><img src='x'><figcaption>a.png</figcaption></figure></bc-attachment>"
            '<bc-attachment sgid="FILE" content-type="application/pdf" filename="b.pdf">'
            "</bc-attachment>"
        )
        self.assertEqual(
            to_markdown(f"<div>{html}</div>", Known()),
            "![a.png](attachment:abc)[b.pdf](attachment:def)",
        )

    def test_an_attachment_we_couldnt_get_is_a_link_or_its_name(self):
        self.assertEqual(
            to_markdown(
                '<bc-attachment sgid="X" filename="c.png" href="https://example.org/c">'
                "</bc-attachment>"
            ),
            "[c.png](https://example.org/c)",
        )
        self.assertEqual(
            to_markdown('<bc-attachment sgid="X" filename="c.png"></bc-attachment>'),
            "c.png",
        )

    def test_links_are_rewritten(self):
        self.assertEqual(
            to_markdown(
                '<a href="https://3.basecamp.com/1/buckets/2/todos/1">task</a>',
                Known(),
            ),
            "[task](/todos/9/)",
        )

    def test_no_html_survives(self):
        self.assertEqual(to_markdown("<script>alert(1)</script><span>x</span>"), "x")
