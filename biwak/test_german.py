"""The main pages in German, as staff and as a client: no common English
words left (specs/languages.md, "Checks"). Made-up data in German, so
that every English word found is the interface's."""

import datetime as dt
import re
from html.parser import HTMLParser

from django.core import mail
from django.test import TestCase

from biwak.activity.operations import subscribe
from biwak.checkins import operations as checkin_ops
from biwak.checkins.support import MONDAY_9, at
from biwak.items import operations as ops
from biwak.test_utils import person, project


# Words that never appear in German texts; whole words, case-sensitive for
# the capitalized ones (labels, buttons), any case for the small ones
ENGLISH = [
    "the", "and", "your", "you", "with", "from", "this", "that", "for", "of",
    "to", "is", "are", "has", "not", "yet", "here", "nothing", "none",
    "Save", "Cancel", "Edit", "Delete", "Remove", "Settings", "Search",
    "Notifications", "Projects", "People", "Help", "Sign", "Add", "New",
    "Show", "Hide", "Move", "Trash", "Share", "Bookmark", "Subscribe",
    "Comment", "Comments", "Reply", "Upload", "Assign", "Assigned", "Today",
    "Yesterday", "Tomorrow", "ago", "Monday", "Tuesday", "January", "March",
    "Back", "More", "Close", "Copy", "Done",
    "Everything", "Only", "Every", "every", "Due", "due", "Overdue", "Who",
    "What", "When", "Where", "unread", "Unread", "Activity", "Messages",
    "Files", "Docs", "Lists", "Questions", "Answers", "Home",
]  # fmt: skip
_WORD = re.compile(
    r"(?<![\w-])(" + "|".join(re.escape(word) for word in ENGLISH) + r")(?![\w-])"
)
# Not ours: what the pages show from outside the catalog
ALLOWED = [
    "Biwak",
]
_ATTRIBUTES = {"title", "aria-label", "placeholder", "alt"}


class Texts(HTMLParser):
    """The visible texts and labelling attributes of a page, without
    scripts, styles and the data the scripts read"""

    def __init__(self):
        super().__init__()
        self.texts, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self._skip += 1
        for name, value in attrs:
            if value and (name in _ATTRIBUTES or name.endswith("-label")):
                self.texts.append(value)

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.texts.append(data.strip())


def english(html):
    parser = Texts()
    parser.feed(html)
    found = []
    for text in parser.texts:
        shown = text
        for word in ALLOWED:
            shown = shown.replace(word, "")
        found += [(match[1], text) for match in _WORD.finditer(shown)]
    return found


class GermanPagesTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ada = person("Ada", language="de")
        cls.cleo = person("Cleo", client=True, language="de")
        cls.website = project("Webseite", members=[cls.ada, cls.cleo])
        cls.todolist = ops.create_list(
            project=cls.website, title="Lager", creator=cls.ada, visible=True
        )
        cls.todo = ops.create_todo(
            todolist=cls.todolist,
            title="Zelt bestellen",
            creator=cls.ada,
            assignees=[cls.ada, cls.cleo],
            due_on=dt.date(2026, 12, 1),
            recurrence="FREQ=MONTHLY;BYDAY=MO;BYSETPOS=1",
        )
        ops.add_comment(cls.todo, author=cls.cleo, content="Gerne, mache ich.")
        cls.message = ops.create_message(
            project=cls.website,
            title="Start",
            creator=cls.ada,
            content="Wir beginnen am Montag.",
            visible=True,
        )
        cls.folder = ops.create_folder(
            project=cls.website, title="Pläne", creator=cls.ada, visible=True
        )
        cls.doc = ops.create_doc(
            project=cls.website,
            title="Packliste",
            creator=cls.ada,
            parent=cls.folder,
            content="Schlafsack, Kocher",
            visible=True,
        )
        cls.question = checkin_ops.create_question(
            project=cls.website,
            title="Wie geht es im Lager?",
            creator=cls.ada,
            people=[cls.ada, cls.cleo],
            now=at("2027-03-19 12:00"),
            visible=True,
            **MONDAY_9,
        )
        subscribe(cls.ada, cls.todo)

    def pages(self):
        return [
            "/",
            "/projects/",
            self.website.get_absolute_url(),
            f"/projects/{self.website.pk}/people/",
            f"/projects/{self.website.pk}/feed/",
            f"/projects/{self.website.pk}/files/",
            f"/projects/{self.website.pk}/todos/",
            self.todolist.get_absolute_url(),
            self.todo.get_absolute_url(),
            self.message.get_absolute_url(),
            self.folder.get_absolute_url(),
            self.doc.get_absolute_url(),
            self.question.get_absolute_url(),
            "/todos/",
            "/feed/",
            "/lantern/",
            "/bookmarks/",
            "/search/?q=Zelt",
            "/people/",
            f"/people/{self.ada.pk}/",
            "/accounts/settings/",
            "/accounts/api-tokens/",
            "/accounts/calendar/",
        ]

    def test_no_english_left(self):
        for user in [self.ada, self.cleo]:
            self.client.force_login(user)
            for url in self.pages():
                with self.subTest(user=user, url=url):
                    response = self.client.get(url, follow=True)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response["Content-Language"], "de")
                    self.assertEqual(english(response.content.decode()), [])

    def test_modals(self):
        self.client.force_login(self.ada)
        for url in [
            f"/projects/{self.website.pk}/lists/new/",
            f"/todos/{self.todo.pk}/edit/",
            f"/messages/{self.message.pk}/edit/",
            f"/projects/{self.website.pk}/checkins/new/",
            f"/items/{self.todo.pk}/trash/",
            f"/items/{self.todo.pk}/share/",
            "/people/invite/",
        ]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(english(response.content.decode()), [])

    def test_the_check_finds_english(self):
        self.assertEqual(
            english('<p title="Save it">Speichern</p><script>"the"</script>'),
            [("Save", "Save it")],
        )
        self.assertEqual(english("<p>To-dos von Ada, nur intern</p>"), [])


class MailsTest(TestCase):
    """One event, two recipients, each in their language"""

    def test_each_recipient_in_their_language(self):
        from biwak.activity.mails import send_mails

        ada = person("Ada")
        bea = person("Bea", language="de")
        eve = person("Eve", language="en")
        website = project("Webseite", members=[ada, bea, eve])
        todolist = ops.create_list(project=website, title="Lager", creator=ada)
        todo = ops.create_todo(todolist=todolist, title="Zelt bestellen", creator=ada)
        subscribe(bea, todo)
        subscribe(eve, todo)
        with self.captureOnCommitCallbacks(execute=True):
            ops.add_comment(todo, author=ada, content="Erledigt?")
        with self.captureOnCommitCallbacks(execute=True):
            send_mails(now=dt.datetime.now(dt.UTC) + dt.timedelta(hours=1))
        mails = {message.to[0]: message for message in mail.outbox}
        self.assertEqual(set(mails), {"bea@example.org", "eve@example.org"})
        german, english_ = mails["bea@example.org"], mails["eve@example.org"]
        self.assertIn("kommentiert", german.body)
        self.assertNotIn("commented", german.body)
        self.assertIn("commented", english_.body)
        self.assertNotIn("kommentiert", english_.body)
        # The footer too
        self.assertIn("Nicht mehr abonnieren", german.body)
        self.assertNotIn("Nicht mehr abonnieren", english_.body)
        self.assertIn("Unsubscribe", english_.body)

    def test_an_invitation_in_the_inviters_language(self):
        from django.utils import translation

        from biwak.projects import operations as project_ops

        ada = person("Ada")
        website = project("Webseite", members=[ada])
        with (
            translation.override("de"),
            self.captureOnCommitCallbacks(execute=True),
        ):
            project_ops.invite_people(
                [website], [{"email": "dora@example.net"}], actor=ada
            )
        [invitation] = mail.outbox
        self.assertEqual(
            invitation.subject, "Ada Example hat dich zu Webseite eingeladen"
        )


class WordingTest(TestCase):
    def test_told_follows_the_number_of_names(self):
        from django.utils import translation

        from biwak.activity.notify import told_line

        ada, bob, cleo = person("Ada"), person("Bob"), person("Cleo")
        website = project("Webseite", members=[ada, bob, cleo])
        with translation.override("de"):
            self.assertEqual(told_line([bob], website, ada), "Bob wird benachrichtigt.")
            self.assertEqual(
                told_line([bob, cleo], website, ada),
                "Bob und Cleo werden benachrichtigt.",
            )
        self.assertEqual(
            told_line([bob, cleo], website, ada),
            "Bob and Cleo will be told.",
        )


class DateFormatsTest(TestCase):
    """English "22 Nov 2026", German "22. Nov. 2026" (biwak/formats/)"""

    def test_each_language(self):
        from django.template import Context, Template
        from django.utils import translation

        from biwak.formats import format_date

        day = dt.datetime(2026, 11, 22, 14, 5)
        march = dt.date(2027, 3, 1)
        expected = {
            "en": {
                "SHORT_DATE_FORMAT": "22 Nov 2026",
                "DATE_FORMAT": "22 November 2026",
                "SHORT_DATETIME_FORMAT": "22 Nov 2026, 14:05",
                "MONTH_DAY_FORMAT": "22 Nov",
                "WEEKDAY_DATE_FORMAT": "Sunday, 22 November 2026",
                "SHORT_WEEKDAY_DATETIME_FORMAT": "Sun, 22 Nov 2026, 14:05",
                "MONTH_DAY_TIME_FORMAT": "22 Nov, 14:05",
            },
            "de": {
                "SHORT_DATE_FORMAT": "22. Nov. 2026",
                "DATE_FORMAT": "22. November 2026",
                "SHORT_DATETIME_FORMAT": "22. Nov. 2026, 14:05",
                "MONTH_DAY_FORMAT": "22. Nov.",
                "WEEKDAY_DATE_FORMAT": "Sonntag, 22. November 2026",
                "SHORT_WEEKDAY_DATETIME_FORMAT": "So, 22. Nov. 2026, 14:05",
                "MONTH_DAY_TIME_FORMAT": "22. Nov., 14:05",
            },
        }
        for language, formats in expected.items():
            with translation.override(language):
                for name, text in formats.items():
                    with self.subTest(language=language, name=name):
                        self.assertEqual(format_date(day, name), text)
                # Django's own names through its filter too
                self.assertEqual(
                    Template('{{ d|date:"SHORT_DATE_FORMAT" }}').render(
                        Context({"d": march})
                    ),
                    {"en": "1 Mar 2027", "de": "1. März 2027"}[language],
                )
                self.assertEqual(
                    Template(
                        '{% load biwak %}{{ d|dateformat:"SHORT_DATE_FORMAT" }}'
                    ).render(Context({"d": march})),
                    {"en": "1 Mar 2027", "de": "1. März 2027"}[language],
                )
