"""The palette's jumps as staff, as a client and as staff without access to
a limited project (specs/keyboard.md, specs/access.md)"""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from biwak.checkins import operations as checkin_ops
from biwak.checkins.support import MONDAY_9, at
from biwak.items import operations as ops
from biwak.palette import queries
from biwak.projects.operations import archive_project
from biwak.test_utils import person, project


class PaletteBase(TestCase):
    """Ada is staff in "Camp" (all-access) and in "Payroll" (limited); Bob is
    staff and not in Payroll; Cleo is a client of Camp; Eve a client of
    another project. What is called "tent" is internal unless it says
    visible."""

    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.eve = person("Eve", client=True)
        self.camp = project("Camp", members=[self.ada, self.cleo])
        self.payroll = project("Tent payroll", members=[self.ada], all_access=False)
        self.other = project("Tent office", members=[self.eve])
        self.visible = ops.create_list(
            project=self.camp, title="Tent visible", creator=self.ada, visible=True
        )
        self.internal = ops.create_list(
            project=self.camp, title="Tent internal", creator=self.ada
        )
        self.secret = ops.create_list(
            project=self.payroll, title="Tent salaries", creator=self.ada
        )
        self.message = ops.create_message(
            project=self.camp, title="Tent message", creator=self.ada, visible=True
        )
        self.doc = ops.create_doc(project=self.camp, title="Tent doc", creator=self.ada)
        self.file = ops.create_upload(
            project=self.camp,
            file=SimpleUploadedFile("tent.png", b"x"),
            creator=self.ada,
            visible=True,
        )
        self.folder = ops.create_folder(
            project=self.camp, title="Tent folder", creator=self.ada, visible=True
        )
        self.question = checkin_ops.create_question(
            project=self.camp,
            title="Tent weather?",
            creator=self.ada,
            people=[self.ada],
            now=at("2027-03-19 12:00"),
            visible=True,
            **MONDAY_9,
        )
        # To-dos are not jumps
        ops.create_todo(todolist=self.visible, title="Tent pegs", creator=self.ada)

    def jump(self, user, q):
        self.client.force_login(user)
        response = self.client.get("/palette/", {"q": q})
        self.assertEqual(response.status_code, 200)
        return response.json()["results"]

    def titles(self, user, q):
        return [result["title"] for result in self.jump(user, q)]


class JumpsTest(PaletteBase):
    def test_staff_find_every_kind_grouped_by_kind(self):
        results = self.jump(self.ada, "tent")
        self.assertEqual(
            [(r["kind"], r["title"]) for r in results],
            [
                ("project", "Tent office"),
                ("project", "Tent payroll"),
                ("list", "Tent internal"),
                ("list", "Tent salaries"),
                ("list", "Tent visible"),
                ("message", "Tent message"),
                ("doc", "Tent doc"),
                ("file", "tent.png"),
                ("folder", "Tent folder"),
                ("question", "Tent weather?"),
            ],
        )
        # With their place and the page to open
        found = {r["title"]: r for r in results}
        self.assertEqual(found["Tent doc"]["url"], self.doc.get_absolute_url())
        self.assertEqual(found["Tent doc"]["context"], "Camp")
        self.assertEqual(found["Tent payroll"]["url"], self.payroll.get_absolute_url())
        self.assertFalse(found["Tent doc"]["visible_to_clients"])
        self.assertTrue(found["Tent message"]["visible_to_clients"])

    def test_words_and_prefixes(self):
        self.assertEqual(self.titles(self.ada, "te vis"), ["Tent visible"])
        self.assertEqual(self.titles(self.ada, "VISIBLE tent"), ["Tent visible"])
        self.assertEqual(self.titles(self.ada, "visible zebra"), [])
        self.assertEqual(self.titles(self.ada, ""), [])
        self.assertEqual(self.titles(self.ada, "  "), [])
        # Query syntax is just text
        self.assertEqual(self.titles(self.ada, "tent & !pegs | ("), [])

    def test_a_client_finds_what_they_can_open(self):
        self.assertEqual(
            self.titles(self.cleo, "tent"),
            [
                "Tent visible",
                "Tent message",
                "tent.png",
                "Tent folder",
                "Tent weather?",
            ],
        )

    def test_a_client_of_another_project_finds_that_project_only(self):
        self.assertEqual(self.titles(self.eve, "tent"), ["Tent office"])

    def test_staff_without_access_to_a_limited_project(self):
        titles = self.titles(self.bob, "tent")
        self.assertIn("Tent office", titles)
        self.assertIn("Tent internal", titles)
        self.assertNotIn("Tent payroll", titles)
        self.assertNotIn("Tent salaries", titles)
        # Not in the limited project's items either
        self.assertEqual(self.titles(self.bob, "salaries"), [])

    def test_trashed_items_are_not_found(self):
        ops.trash(self.doc, actor=self.ada)
        self.assertNotIn("Tent doc", self.titles(self.ada, "tent"))

    def test_internal_items_moved_into_visible_ones_follow_their_container(self):
        ops.set_visibility(self.internal, visible=True, actor=self.ada)
        self.assertIn("Tent internal", self.titles(self.cleo, "tent"))
        ops.set_visibility(self.internal, visible=False, actor=self.ada)
        self.assertNotIn("Tent internal", self.titles(self.cleo, "tent"))

    def test_archived_projects_and_their_contents_come_last_marked(self):
        archive_project(self.camp, actor=self.ada)
        results = self.jump(self.ada, "tent")
        marks = [r["archived"] for r in results]
        self.assertEqual(marks, sorted(marks))
        self.assertTrue(results[-1]["archived"])
        self.assertEqual(
            {r["title"] for r in results if r["archived"]} & {"Tent doc", "Camp"},
            {"Tent doc"},
        )
        self.assertFalse(
            next(r for r in results if r["title"] == "Tent office")["archived"]
        )

    def test_archived_lists_come_last_marked(self):
        ops.archive(self.visible, actor=self.ada)
        results = {r["title"]: r["archived"] for r in self.jump(self.ada, "tent")}
        self.assertTrue(results["Tent visible"])
        self.assertFalse(results["Tent internal"])
        marks = [r["archived"] for r in self.jump(self.ada, "tent")]
        self.assertEqual(marks, sorted(marks))
        self.assertTrue(marks[-1])

    def test_at_most_twenty(self):
        for index in range(30):
            ops.create_list(
                project=self.camp, title=f"Bulk {index:02}", creator=self.ada
            )
        self.assertEqual(len(self.jump(self.ada, "bulk")), queries.LIMIT)

    def test_titles_show_mentions_as_written(self):
        ops.create_list(
            project=self.camp,
            title=f"Ask [@Ada Example](person:{self.ada.pk}) about hats",
            creator=self.ada,
        )
        self.assertEqual(self.titles(self.cleo, "hats"), [])
        self.assertEqual(self.titles(self.ada, "hats"), ["Ask @Ada Example about hats"])

    def test_a_fixed_number_of_queries(self):
        for user in [self.ada, self.cleo, self.bob]:
            self.client.force_login(user)
            counts = []
            for q in ["tent", "tent vis", "zzz"]:
                with CaptureQueriesContext(connection) as context:
                    self.client.get("/palette/", {"q": q})
                counts.append(len(context))
            self.assertEqual(len(set(counts)), 1, (user, counts))


class PeopleTest(PaletteBase):
    def test_staff_find_people_they_share_a_project_with(self):
        self.assertEqual(
            self.titles(self.ada, "cleo"), ["Cleo Example, Example Client Ltd"]
        )
        self.assertEqual(self.titles(self.ada, "bo"), [])  # Bob is in no project
        result = self.jump(self.ada, "cle")[0]
        self.assertEqual(result["kind"], "person")
        self.assertEqual(result["url"], f"/people/{self.cleo.pk}/")

    def test_a_client_finds_members_only(self):
        # Ada is a member of Camp; Bob is staff who sees Camp (all-access)
        # without being a member, and Eve is a member elsewhere
        self.assertEqual(self.titles(self.cleo, "ada"), ["Ada Example"])
        self.assertEqual(self.titles(self.cleo, "bob"), [])
        self.assertEqual(self.titles(self.cleo, "eve"), [])

    def test_staff_without_access_do_not_find_the_people_of_a_limited_project(self):
        secret = person("Zora")
        self.payroll.memberships.create(user=secret)
        self.assertEqual(self.titles(self.bob, "zora"), [])
        self.assertEqual(self.titles(self.ada, "zora"), ["Zora Example"])

    def test_inactive_people_are_not_found(self):
        self.cleo.is_active = False
        self.cleo.save()
        self.assertEqual(self.titles(self.ada, "cleo"), [])

    def test_emails_are_not_searched(self):
        self.assertEqual(self.titles(self.ada, "example.org"), [])
