import datetime as dt
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from biwak.accounts.models import APIToken
from biwak.checkins import operations as checkin_ops
from biwak.checkins.support import MONDAY_9, at
from biwak.files import operations as file_ops
from biwak.items import operations as ops
from biwak.items.models import Item, Kind
from biwak.projects.operations import archive_project
from biwak.search import queries
from biwak.test_utils import check_in_answers, person, project


class SearchBase(TestCase):
    """Ada and Bob are staff, Cleo is a client. "Website" is all-access with
    Ada and Cleo as members, "Payroll" is limited to Ada. What mentions
    "zebra" is internal, what mentions "tent" is visible to Cleo."""

    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.project = project("Website", members=[self.ada, self.cleo])
        self.payroll = project("Payroll", members=[self.ada], all_access=False)
        self.visible = ops.create_list(
            project=self.project, title="Launch", creator=self.ada, visible=True
        )
        self.internal = ops.create_list(
            project=self.project,
            title="Internal",
            creator=self.ada,
            description="Zebra stripes",
        )
        self.todo = ops.create_todo(
            todolist=self.visible,
            title="Order the tent",
            creator=self.ada,
            notes="Bring pegs",
        )
        self.secret = ops.create_todo(
            todolist=self.internal,
            title="Raise the rate",
            creator=self.ada,
            notes="Zebra budget",
        )
        self.salaries = ops.create_list(
            project=self.payroll, title="Salaries", creator=self.ada
        )
        self.salary = ops.create_todo(
            todolist=self.salaries,
            title="Review the zebra salaries",
            creator=self.ada,
            notes="Confidential",
        )

    def api(self, user):
        _token, secret = APIToken.create_for(user=user, title="T", access="read")
        return {"authorization": f"Bearer {secret}"}

    def api_titles(self, user, q, **params):
        response = self.client.get(
            "/api/v1/search/", {"q": q} | params, headers=self.api(user)
        )
        self.assertEqual(response.status_code, 200, response.content)
        return sorted(result["title"] for result in response.json()["results"])

    def page_titles(self, user, q, **params):
        self.client.force_login(user)
        response = self.client.get("/search/", {"q": q} | params)
        self.assertEqual(response.status_code, 200)
        return sorted(result["item"].title for result in response.context["results"])

    def both(self, user, q, **params):
        """The titles found by the page and by the API, the same"""
        page, api = (
            self.page_titles(user, q, **params),
            self.api_titles(user, q, **params),
        )
        self.assertEqual(page, api)
        return api


class FindingTest(SearchBase):
    def test_titles_and_texts_of_every_kind(self):
        message = ops.create_message(
            project=self.project, title="Kickoff", creator=self.ada, content="Doormat"
        )
        doc = ops.create_doc(
            project=self.project, title="Plan", creator=self.ada, content="Lanterns"
        )
        upload = ops.create_upload(
            project=self.project,
            file=SimpleUploadedFile("photo.png", b"x"),
            creator=self.ada,
            description="Sunrise over the camp",
        )
        question = checkin_ops.create_question(
            project=self.project,
            title="How is the camp?",
            creator=self.ada,
            people=[self.ada],
            now=at("2027-03-19 12:00"),
            **MONDAY_9,
        )
        checkin_ops.run(now=at("2027-03-22 09:00"))
        answer = checkin_ops.answer(question, user=self.ada, content="Muddy boots")
        ops.add_comment(self.todo, author=self.ada, content="Ropes arrived")
        found = {
            "tent": ["Order the tent"],  # title
            "pegs": ["Order the tent"],  # to-do
            "doormat": ["Kickoff"],  # message
            "lanterns": ["Plan"],  # doc
            "sunrise": ["photo.png"],  # file
            "stripes": ["Internal"],  # list
            "muddy": [answer.title],  # answer
            "ropes": ["Order the tent"],  # comment
        }
        for word, titles in found.items():
            with self.subTest(word=word):
                self.assertEqual(self.both(self.ada, word), titles)
        self.assertEqual(
            Item.objects.get(title="photo.png").pk,
            upload.pk,
        )
        self.assertEqual((message.kind, doc.kind), (Kind.MESSAGE, Kind.DOC))

    def test_texts_are_current(self):
        """The indexes follow every change"""
        self.assertEqual(self.both(self.ada, "pegs"), ["Order the tent"])
        ops.update_todo(self.todo, actor=self.ada, notes="Bring hammers")
        self.assertEqual(self.both(self.ada, "pegs"), [])
        self.assertEqual(self.both(self.ada, "hammers"), ["Order the tent"])
        ops.update_todo(self.todo, actor=self.ada, title="Buy the tent")
        self.assertEqual(self.both(self.ada, "buy"), ["Buy the tent"])
        message = ops.create_message(
            project=self.project, title="Kickoff", creator=self.ada, content="Doormat"
        )
        file_ops.update_message(message, actor=self.ada, content="Wheelbarrow")
        self.assertEqual(self.both(self.ada, "doormat"), [])
        self.assertEqual(self.both(self.ada, "wheelbarrow"), ["Kickoff"])

    def test_prefixes_and_all_words(self):
        self.assertEqual(self.both(self.ada, "ten"), ["Order the tent"])
        self.assertEqual(self.both(self.ada, "ORD te"), ["Order the tent"])
        self.assertEqual(self.both(self.ada, "order pegs"), ["Order the tent"])
        self.assertEqual(self.both(self.ada, "order zebra"), [])
        # No stemming: the same for every language
        self.assertEqual(self.both(self.ada, "tents"), [])
        # Several languages, accents as typed
        ops.create_message(
            project=self.project,
            title="Zeltplatz reservieren",
            creator=self.ada,
            content="Wir brauchen Schlafsäcke",
        )
        self.assertEqual(self.both(self.ada, "schlafs"), ["Zeltplatz reservieren"])
        self.assertEqual(self.both(self.ada, "zeltpl"), ["Zeltplatz reservieren"])

    def test_found_once(self):
        ops.add_comment(self.todo, author=self.ada, content="Tent pegs, more tents")
        ops.add_comment(self.todo, author=self.ada, content="Tent poles")
        self.assertEqual(self.both(self.ada, "tent"), ["Order the tent"])

    def test_syntax_is_just_words(self):
        for q in [
            "'",
            "tent & !",
            "tent | pegs",
            "(tent",
            "tent:*",
            "\\",
            "tent'; DROP TABLE items_item; --",
            "<->",
            "a" * 500,
            "   ",
            "!!!",
        ]:
            with self.subTest(q=q):
                self.api_titles(self.ada, q)
                self.page_titles(self.ada, q)
        self.assertEqual(self.both(self.ada, "tent & !"), ["Order the tent"])
        self.assertEqual(self.both(self.ada, "!!!"), [])
        self.assertEqual(self.both(self.ada, "   "), [])
        self.assertTrue(Item.objects.exists())

    def test_the_words_as_the_database_reads_them(self):
        ops.update_todo(
            self.todo, actor=self.ada, notes="Version 1.5 for ada@example.org"
        )
        self.assertEqual(self.both(self.ada, "1.5"), ["Order the tent"])
        self.assertEqual(self.both(self.ada, "ada@example.org"), ["Order the tent"])

    def test_newest_first(self):
        old = ops.create_message(
            project=self.project, title="Pegs old", creator=self.ada
        )
        Item.objects.filter(pk=old.pk).update(
            updated_at=timezone.now() - dt.timedelta(days=3)
        )
        new = ops.create_message(
            project=self.project, title="Pegs new", creator=self.ada
        )
        self.client.force_login(self.ada)
        results = self.client.get("/search/", {"q": "pegs"}).context["results"]
        self.assertEqual(
            [r["item"].pk for r in results], [new.pk, self.todo.pk, old.pk]
        )


class FiltersTest(SearchBase):
    def setUp(self):
        super().setUp()
        self.doc = ops.create_doc(
            project=self.project, title="Tent plan", creator=self.bob, content="Pegs"
        )
        self.other = project("Camp", members=[self.ada])
        self.camp = ops.create_message(
            project=self.other, title="Camp tent", creator=self.ada
        )

    def test_project_filter(self):
        self.assertEqual(
            self.api_titles(self.ada, "tent", project_id=self.other.pk), ["Camp tent"]
        )
        self.assertEqual(
            self.page_titles(self.ada, "tent", project=self.other.pk), ["Camp tent"]
        )
        self.assertEqual(
            self.api_titles(self.ada, "tent", project_id=self.project.pk),
            ["Order the tent", "Tent plan"],
        )

    def test_kind(self):
        self.assertEqual(self.both(self.ada, "tent", kind="doc"), ["Tent plan"])
        self.assertEqual(self.both(self.ada, "tent", kind="todo"), ["Order the tent"])

    def test_mine(self):
        self.assertEqual(self.both(self.bob, "tent", mine="on"), ["Tent plan"])
        response = self.client.get(
            "/api/v1/search/",
            {"q": "tent", "mine": "true"},
            headers=self.api(self.bob),
        )
        self.assertEqual(
            [r["title"] for r in response.json()["results"]], ["Tent plan"]
        )

    def test_mine_includes_assigned_todos_within_visibility(self):
        ops.assign(self.todo, [self.bob], actor=self.ada)
        # Created and assigned: found once
        mine = ops.create_todo(
            todolist=self.visible, title="Tent pegs", creator=self.bob
        )
        ops.assign(mine, [self.bob], actor=self.bob)
        self.assertEqual(
            self.both(self.bob, "tent", mine="on"),
            ["Order the tent", "Tent pegs", "Tent plan"],
        )
        # Ada created these, nobody else is assigned
        self.assertEqual(self.both(self.bob, "zebra", mine="on"), [])
        self.assertEqual(
            self.both(self.ada, "tent", mine="on"), ["Camp tent", "Order the tent"]
        )
        # Assigned, but not visible to Cleo any more: stays out
        ops.assign(self.todo, [self.cleo], actor=self.ada)
        Item.objects.filter(pk=self.todo.pk).update(is_client_visible=False)
        self.assertEqual(self.both(self.cleo, "tent", mine="on"), [])

    def test_archived_projects_are_left_out_unless_included(self):
        archive_project(self.other, actor=self.ada)
        self.assertEqual(self.both(self.ada, "tent"), ["Order the tent", "Tent plan"])
        self.assertEqual(
            self.both(self.ada, "tent", archived="true"),
            ["Camp tent", "Order the tent", "Tent plan"],
        )
        self.assertEqual(self.both(self.ada, "camp"), [])

    def test_archived_projects_are_marked(self):
        archive_project(self.other, actor=self.ada)
        response = self.client.get(
            "/api/v1/search/",
            {"q": "camp", "archived": "true"},
            headers=self.api(self.ada),
        )
        (result,) = response.json()["results"]
        self.assertEqual(
            (result["project_name"], result["project_archived"], result["archived"]),
            ("Camp", True, True),
        )
        self.client.force_login(self.ada)
        page = self.client.get("/search/", {"q": "camp", "archived": "on"})
        self.assertEqual([r["archived"] for r in page.context["results"]], [True])
        self.assertContains(page, ">Archived</span>", count=1)
        page = self.client.get("/search/", {"q": "tent", "archived": "on"})
        self.assertContains(page, ">Archived</span>", count=1)

    def test_archived_lists_and_their_contents_are_left_out(self):
        ops.add_comment(self.todo, author=self.ada, content="Parrot colors")
        ops.archive(self.visible, actor=self.ada)
        self.assertEqual(self.both(self.ada, "tent"), ["Camp tent", "Tent plan"])
        self.assertEqual(self.both(self.ada, "parrot"), [])
        self.assertEqual(self.both(self.ada, "launch"), [])
        self.assertEqual(
            self.both(self.ada, "tent", archived="on"),
            ["Camp tent", "Order the tent", "Tent plan"],
        )
        self.assertEqual(
            self.both(self.ada, "parrot", archived="on"), ["Order the tent"]
        )
        self.assertEqual(self.both(self.ada, "launch", archived="on"), ["Launch"])
        # Marked: the list and its to-do, not the others
        self.client.force_login(self.ada)
        results = self.client.get("/search/", {"q": "tent", "archived": "on"}).context[
            "results"
        ]
        self.assertEqual(
            {r["item"].title: r["archived"] for r in results},
            {"Camp tent": False, "Order the tent": True, "Tent plan": False},
        )
        # Active lists and what is in them stay
        self.assertEqual(
            self.both(self.ada, "zebra"),
            ["Internal", "Raise the rate", "Review the zebra salaries"],
        )

    def test_a_client_sees_the_same_apart_from_archived(self):
        before = self.both(self.cleo, "tent")
        archive_project(self.other, actor=self.ada)
        self.assertEqual(self.both(self.cleo, "tent"), before)
        self.assertEqual(self.both(self.cleo, "tent", archived="true"), before)
        ops.archive(self.visible, actor=self.ada)
        self.assertEqual(self.both(self.cleo, "tent"), [])
        self.assertEqual(
            self.both(self.cleo, "tent", archived="true"), ["Order the tent"]
        )
        # Internal things stay hidden with the checkbox
        self.assertEqual(self.both(self.cleo, "zebra", archived="true"), [])

    def test_the_archived_filter_costs_a_fixed_number_of_queries(self):
        ops.archive(self.visible, actor=self.ada)
        self.client.force_login(self.ada)

        def count():
            with CaptureQueriesContext(connection) as queries_:
                response = self.client.get("/search/", {"q": "tent", "archived": "on"})
            return len(queries_), len(response.context["results"])

        one = count()
        # Archived lists take no new to-dos (specs/archiving.md)
        ops.unarchive(self.visible, actor=self.ada)
        for n in range(3):
            ops.create_todo(todolist=self.visible, title=f"Tent {n}", creator=self.ada)
        ops.archive(self.visible, actor=self.ada)
        many = count()
        self.assertEqual((one[1], many[1]), (3, 6))
        self.assertEqual(one[0], many[0])
        self.assertLess(many[0], 25)

    def test_a_bad_kind_or_project_is_an_error(self):
        self.client.force_login(self.ada)
        response = self.client.get("/search/", {"q": "tent", "kind": "nope"})
        self.assertEqual(response.context["results"], [])
        response = self.client.get(
            "/api/v1/search/", {"q": "tent", "kind": "nope"}, headers=self.api(self.ada)
        )
        self.assertEqual(response.status_code, 422)


class VisibilityTest(SearchBase):
    """Search shows content: what a person can't see isn't found, through the
    page and the API (specs/access.md)"""

    def test_staff_find_everything_in_their_projects(self):
        self.assertEqual(
            self.both(self.ada, "zebra"),
            ["Internal", "Raise the rate", "Review the zebra salaries"],
        )

    def test_a_client_finds_only_what_clients_see(self):
        self.assertEqual(self.both(self.cleo, "zebra"), [])
        self.assertEqual(self.both(self.cleo, "internal"), [])
        self.assertEqual(self.both(self.cleo, "rate"), [])
        self.assertEqual(self.both(self.cleo, "tent"), ["Order the tent"])
        self.assertEqual(self.both(self.cleo, "pegs"), ["Order the tent"])

    def test_comments_on_internal_items(self):
        ops.add_comment(self.secret, author=self.ada, content="Giraffe numbers")
        ops.add_comment(self.todo, author=self.ada, content="Parrot colors")
        self.assertEqual(self.both(self.ada, "giraffe"), ["Raise the rate"])
        self.assertEqual(self.both(self.cleo, "giraffe"), [])
        self.assertEqual(self.both(self.cleo, "parrot"), ["Order the tent"])
        self.client.force_login(self.cleo)
        self.assertNotContains(self.client.get("/search/", {"q": "giraffe"}), "Giraffe")

    def test_a_client_can_look_for_their_own_comment(self):
        ops.add_comment(self.todo, author=self.cleo, content="Parrot colors")
        self.assertEqual(self.both(self.cleo, "parrot"), ["Order the tent"])

    def test_staff_without_access_to_a_limited_project(self):
        self.assertEqual(self.both(self.bob, "zebra"), ["Internal", "Raise the rate"])
        self.assertEqual(self.both(self.bob, "salaries"), [])
        self.assertEqual(self.both(self.bob, "confidential"), [])
        ops.add_comment(self.salary, author=self.ada, content="Giraffe numbers")
        self.assertEqual(self.both(self.bob, "giraffe"), [])
        self.assertEqual(self.both(self.ada, "giraffe"), ["Review the zebra salaries"])

    def test_the_project_filter_doesnt_reveal_a_limited_project(self):
        response = self.client.get(
            "/api/v1/search/",
            {"q": "salaries", "project_id": self.payroll.pk},
            headers=self.api(self.bob),
        )
        self.assertEqual(response.status_code, 404)
        self.client.force_login(self.bob)
        response = self.client.get(
            "/search/", {"q": "salaries", "project": self.payroll.pk}
        )
        self.assertEqual(response.context["results"], [])
        self.assertContains(response, "Select a valid choice")
        self.assertNotContains(response, "Payroll")
        self.assertNotContains(response, "Salaries")

    def test_a_client_who_is_not_a_member(self):
        dan = person("Dan", client=True)
        self.assertEqual(self.both(dan, "tent"), [])
        self.assertEqual(self.both(self.cleo, "salaries"), [])

    def test_a_client_in_a_project_has_no_other_projects_content(self):
        other = project("Other", members=[self.ada])
        ops.create_message(
            project=other, title="Tent elsewhere", creator=self.ada, visible=True
        )
        self.assertEqual(self.both(self.cleo, "tent"), ["Order the tent"])

    def test_trashed_items_are_not_found(self):
        ops.add_comment(self.todo, author=self.ada, content="Parrot colors")
        ops.trash(self.todo, actor=self.ada)
        for user in [self.ada, self.cleo]:
            for word in ["tent", "pegs", "parrot"]:
                with self.subTest(user=user, word=word):
                    self.assertEqual(self.both(user, word), [])
        ops.restore(self.todo, actor=self.ada)
        self.assertEqual(self.both(self.cleo, "parrot"), ["Order the tent"])

    def test_the_items_of_a_trashed_list_are_not_found(self):
        ops.trash(self.visible, actor=self.ada)
        self.assertEqual(self.both(self.cleo, "tent"), [])
        self.assertEqual(self.both(self.ada, "pegs"), [])
        self.assertEqual(self.both(self.ada, "launch"), [])

    def test_made_internal_after_it_was_indexed(self):
        self.assertEqual(self.both(self.cleo, "tent"), ["Order the tent"])
        ops.add_comment(self.todo, author=self.ada, content="Parrot colors")
        ops.set_visibility(self.visible, visible=False, actor=self.ada)
        self.assertEqual(self.both(self.cleo, "tent"), [])
        self.assertEqual(self.both(self.cleo, "parrot"), [])
        self.assertEqual(self.both(self.cleo, "launch"), [])
        self.assertEqual(self.both(self.ada, "parrot"), ["Order the tent"])
        ops.set_visibility(self.visible, visible=True, actor=self.ada)
        self.assertEqual(self.both(self.cleo, "parrot"), ["Order the tent"])

    def test_moved_into_an_internal_list(self):
        ops.move_todo(self.todo, todolist=self.internal, actor=self.ada)
        self.assertEqual(self.both(self.cleo, "pegs"), [])
        self.assertEqual(self.both(self.ada, "pegs"), ["Order the tent"])

    def test_a_client_doesnt_find_internal_check_in_answers(self):
        question = checkin_ops.create_question(
            project=self.project,
            title="How is the camp?",
            creator=self.ada,
            people=[self.ada],
            now=at("2027-03-19 12:00"),
            **MONDAY_9,
        )
        checkin_ops.run(now=at("2027-03-22 09:00"))
        checkin_ops.answer(question, user=self.ada, content="Giraffes everywhere")
        self.assertEqual(self.both(self.cleo, "giraffes"), [])
        self.assertEqual(self.both(self.ada, "giraffes"), ["How is the camp?"])

    def test_nobody_logged_out(self):
        self.assertEqual(self.client.get("/search/", {"q": "tent"}).status_code, 302)
        self.assertEqual(
            self.client.get("/api/v1/search/", {"q": "tent"}).status_code, 401
        )

    def test_inactive_people_find_nothing(self):
        self.assertEqual(
            list(queries.search(self.cleo, "tent").values_list("title", flat=True)),
            ["Order the tent"],
        )
        self.cleo.is_active = False
        self.assertEqual(list(queries.search(self.cleo, "tent")), [])


class ExcerptTest(SearchBase):
    def search(self, q):
        self.client.force_login(self.ada)
        return self.client.get("/search/", {"q": q})

    def test_excerpts_mark_the_matches(self):
        response = self.search("pegs")
        self.assertContains(response, "Bring <mark>pegs</mark>")
        response = self.search("order")
        self.assertContains(response, "<mark>Order</mark> the tent")

    def test_excerpts_are_plain_text(self):
        """Like the excerpts elsewhere: no Markdown, mentions as written"""
        ops.update_todo(
            self.todo,
            actor=self.ada,
            notes=f"Ask [@Bob](person:{self.bob.pk}) for **more** [pegs](https://example.org/)",
        )
        response = self.search("pegs")
        self.assertContains(response, "Ask @Bob for more <mark>pegs</mark>")
        self.assertNotContains(response, "person:")
        self.assertNotContains(response, "**more**")

    def test_the_excerpt_is_escaped(self):
        ops.update_todo(
            self.todo,
            actor=self.ada,
            title="<b>Tent</b> & <i>poles</i>",
            notes='<script>alert("pegs")</script> & <img src=x onerror=alert(1)> pegs',
        )
        for response in [self.search("pegs"), self.search("poles")]:
            content = response.content.decode()
            self.assertNotIn("<script>alert", content)
            self.assertNotIn("<img src=x", content)
            self.assertNotIn("<b>Tent", content)
            self.assertNotIn("<i>poles", content)
        content = self.search("pegs").content.decode()
        self.assertIn("&lt;img src=x onerror=alert(1)&gt; <mark>pegs</mark>", content)
        self.assertIn(
            "&lt;b&gt;Tent&lt;/b&gt; &amp; &lt;i&gt;",
            self.search("poles").content.decode(),
        )
        # The API says the same, as data
        response = self.client.get(
            "/api/v1/search/", {"q": "pegs"}, headers=self.api(self.ada)
        )
        (result,) = response.json()["results"]
        self.assertNotIn("<img", result["excerpt_html"])
        self.assertIn("&lt;img src=x", result["excerpt_html"])
        self.assertIn("<mark>pegs</mark>", result["excerpt_html"])
        self.assertNotIn("<mark>", result["excerpt"])
        self.assertIn("<img src=x", result["excerpt"], "plain text, not HTML")

    def test_nothing_in_the_text_can_fake_a_highlight(self):
        ops.update_todo(self.todo, actor=self.ada, notes="fake and pegs")
        (result,) = self.client.get(
            "/api/v1/search/", {"q": "pegs"}, headers=self.api(self.ada)
        ).json()["results"]
        self.assertEqual(result["excerpt_html"], "fake and <mark>pegs</mark>")

    def test_at_most_200_characters(self):
        notes = " ".join(f"word{n}" for n in range(300)) + " pegs " + "tail " * 100
        ops.update_todo(self.todo, actor=self.ada, notes=notes)
        (result,) = self.client.get(
            "/api/v1/search/", {"q": "pegs"}, headers=self.api(self.ada)
        ).json()["results"]
        self.assertLessEqual(len(result["excerpt"]), 201)
        self.assertIn("pegs", result["excerpt"])

    def test_clip(self):
        start, stop = queries.START, queries.STOP
        self.assertEqual(queries.clip("a  b\nc"), "a b c")
        long = f"{start}abc{stop} " + "x" * 300
        clipped = queries.clip(long)
        self.assertEqual(len(queries.to_text(clipped)), 201)
        self.assertTrue(clipped.endswith("…"))
        # An open marker is closed
        clipped = queries.clip(f"abcde {start}fghij{stop}", 8)
        self.assertEqual(clipped, f"abcde {start}fg{stop}…")

    def test_the_excerpt_comes_from_a_comment_if_only_it_matches(self):
        ops.add_comment(self.todo, author=self.ada, content="The parrot colors")
        response = self.search("parrot")
        self.assertContains(response, "The <mark>parrot</mark> colors")
        self.assertContains(response, "Comment:")
        self.assertNotContains(self.search("pegs"), "Comment:")

    def test_no_excerpt_if_only_the_title_matches(self):
        (result,) = self.client.get(
            "/api/v1/search/", {"q": "tent"}, headers=self.api(self.ada)
        ).json()["results"]
        self.assertEqual(result["excerpt"], "")
        self.assertEqual(result["title_html"], "Order the <mark>tent</mark>")

    def test_the_result_shows_what_the_viewer_needs(self):
        response = self.search("tent")
        self.assertContains(response, "Order the <mark>tent</mark>")
        self.assertContains(response, "Clients")  # the badge
        self.assertContains(response, "Website")
        self.assertContains(response, "to-do")
        self.assertContains(response, f'href="{self.todo.get_absolute_url()}"')
        self.assertNotContains(self.search("zebra"), "wb-client-badge")

    def test_the_api_has_the_visibility(self):
        results = self.client.get(
            "/api/v1/search/", {"q": "tent zebra"}, headers=self.api(self.ada)
        ).json()["results"]
        self.assertEqual(results, [])
        results = self.client.get(
            "/api/v1/search/", {"q": "rate"}, headers=self.api(self.ada)
        ).json()["results"]
        self.assertFalse(results[0]["visible_to_clients"])
        results = self.client.get(
            "/api/v1/search/", {"q": "tent"}, headers=self.api(self.ada)
        ).json()["results"]
        self.assertTrue(results[0]["visible_to_clients"])


class PagingTest(SearchBase):
    def setUp(self):
        super().setUp()
        # With pages of 5 (patched, the API's page_size): 5, 5 and 3
        for n in range(12):
            ops.create_message(
                project=self.project, title=f"Pegs {n}", creator=self.ada
            )

    @patch.object(queries, "PAGE_SIZE", 5)
    def test_the_page(self):
        self.client.force_login(self.ada)
        seen, url = [], "/search/?q=pegs"
        pages = 0
        while url:
            response = self.client.get(url)
            pages += 1
            seen += [r["item"].pk for r in response.context["results"]]
            url = response.context["older"]
        self.assertEqual((pages, len(seen), len(set(seen))), (3, 13, 13))

    def test_the_api(self):
        seen, params = [], {"q": "pegs", "page_size": 5}
        pages = 0
        while True:
            data = self.client.get(
                "/api/v1/search/", params, headers=self.api(self.ada)
            ).json()
            pages += 1
            self.assertLessEqual(len(data["results"]), 5)
            seen += [r["id"] for r in data["results"]]
            if not data["next"]:
                break
            params["cursor"] = parse_qs(urlsplit(data["next"]).query)["cursor"][0]
        self.assertEqual((pages, len(seen), len(set(seen))), (3, 13, 13))

    def test_a_bad_cursor(self):
        self.client.force_login(self.ada)
        self.assertEqual(
            self.client.get("/search/", {"q": "pegs", "before": "x"}).status_code, 400
        )

    def test_answers_cost_no_query_each(self):
        self.client.force_login(self.ada)

        def count():
            with CaptureQueriesContext(connection) as queries_:
                response = self.client.get("/search/", {"q": "giraffes"})
            return len(queries_), len(response.context["results"])

        check_in_answers(self.project, [self.ada])
        one = count()
        check_in_answers(self.project, [self.ada, self.bob, person("Carl")])
        many = count()
        self.assertEqual((one[1], many[1]), (1, 4))
        self.assertEqual(one[0], many[0])

    def test_a_page_costs_a_fixed_number_of_queries(self):
        self.client.force_login(self.ada)
        with CaptureQueriesContext(connection) as queries_:
            self.client.get("/search/", {"q": "pegs"})
        self.assertLess(len(queries_), 25)


class NavigationTest(SearchBase):
    def test_the_field_in_the_navigation(self):
        self.client.force_login(self.ada)
        response = self.client.get("/search/", {"q": "tent"})
        # The navigation's button opens the palette, the page keeps its field
        self.assertNotContains(response, 'role="search"')
        self.assertContains(response, 'value="tent"')
        self.assertContains(self.client.get("/feed/"), "data-palette-open")

    def test_the_empty_page(self):
        self.client.force_login(self.ada)
        response = self.client.get("/search/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Nothing found")
        self.assertContains(self.client.get("/search/", {"q": "nope"}), "Nothing found")


class QueryTextTest(TestCase):
    def test_lexemes(self):
        # In the order typed
        self.assertEqual(queries.prefixes("Tent PEGS"), ["'tent':*", "'pegs':*"])
        self.assertEqual(queries.prefixes("&&"), [])
        self.assertEqual(queries.prefixes("it's"), ["'it':*", "'s':*"])
        self.assertEqual(queries.prefixes("it\\'s")[0], "'it':*")
        # The first ten words typed count, not the first alphabetically
        words = [f"w{n}" for n in range(30, 0, -1)]
        self.assertEqual(
            queries.prefixes(" ".join(words)), [f"'{w}':*" for w in words[:10]]
        )


class PlainTest(SimpleTestCase):
    def test_to_html(self):
        self.assertEqual(
            queries.to_html(f"<a> {queries.START}b&c{queries.STOP}"),
            "&lt;a&gt; <mark>b&amp;c</mark>",
        )
