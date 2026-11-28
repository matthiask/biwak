"""The commands of checkins.md; the CLI test case is the one of test_cli.py"""

import datetime as dt
import json
import tempfile
from pathlib import Path

from biwak import test_cli
from biwak.checkins import operations as ops
from biwak.checkins.models import Mode, Occurrence, Question, QuestionMail
from biwak.checkins.support import at
from biwak.files.models import Attachment
from biwak.items import operations as item_ops
from biwak.items.models import Item
from biwak.organizations import activation
from biwak.projects.models import Membership
from biwak.test_utils import person


class CheckinCLITest(test_cli.CLITest):
    def setUp(self):
        super().setUp()
        self.bob = person("Bob")
        self.item = ops.create_question(
            project=self.project,
            title="How are you?",
            creator=self.ada,
            rule="FREQ=WEEKLY;BYDAY=MO",
            starts_on=dt.date(2027, 3, 15),
            time_of_day=dt.time(9, 0),
            people=[self.ada, self.bob],
            visible=True,
            now=at("2027-03-19 12:00"),
        )
        ops.ask_due(now=at("2027-03-22 09:00"))
        self.occurrence = Occurrence.objects.get()

    def test_checkins(self):
        output = self.biwak("checkins", "--project", self.project.pk).output
        for text in ["How are you?", "every Monday, 09:00", "[clients]"]:
            self.assertIn(text, output)
        data = json.loads(
            self.biwak("checkins", "--project", self.project.pk, "--json").stdout
        )
        self.assertEqual(data[0]["id"], self.item.pk)
        ops.pause(self.item, actor=self.ada)
        self.assertIn(
            "paused", self.biwak("checkins", "--project", self.project.pk).output
        )

    def test_answer_and_show(self):
        result = self.biwak(
            "checkins", "answer", self.item.pk, input="Busy with the **launch**\n"
        )
        self.assertIn("Clients can see this answer.", result.output)
        self.assertIn(f"occurrence #{self.occurrence.pk}", result.output)
        output = self.biwak("checkins", "show", self.item.pk).output
        for text in [
            "How are you?",
            "Asked: every Monday, 09:00",
            "Busy with the **launch**",
            "Ada Example:",
            "Hasn't answered yet: Bob",
            "Mails about answers: summary",
        ]:
            self.assertIn(text, output)
        data = json.loads(self.biwak("checkins", "show", self.item.pk, "--json").stdout)
        self.assertEqual(
            data["occurrences"][0]["answers"][0]["author"]["short_name"], "Ada"
        )
        # Changing it
        self.biwak("checkins", "answer", self.item.pk, "Better")
        self.assertEqual(Item.objects.get(kind="answer").answer.content, "Better")

    def test_answer_an_older_occurrence_with_attachments(self):
        ops.ask_due(now=at("2027-03-29 09:00"))
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        photo = Path(directory.name) / "photo.png"
        photo.write_bytes(b"\x89PNG\r\n")
        self.biwak(
            "checkins", "answer", self.item.pk, "Back then",
            "--occurrence", self.occurrence.pk, "--attach", photo,
        )  # fmt: skip
        answer = Item.objects.get(kind="answer")
        self.assertEqual(answer.answer.occurrence, self.occurrence)
        self.assertTrue(answer.answer.content.startswith("Back then\n\n![photo.png]("))
        self.assertEqual(Attachment.objects.get().item_id, answer.pk)

    def test_show_marks_who_isnt_asked(self):
        """Kept among the people asked, not asked (decided 2026-11-28)"""
        cleo = person("Cleo", client=True)
        Membership.objects.create(project=self.project, user=cleo)
        self.item.question.people.add(cleo)
        activation.deactivate([self.bob], actor=person("Root", is_admin=True))
        self.assertIn(
            "People: Ada, Bob (inactive), Cleo\n",
            self.biwak("checkins", "show", self.item.pk).output,
        )
        item_ops.set_visibility(
            Item.objects.get(pk=self.item.pk), visible=False, actor=self.ada
        )
        self.assertIn(
            "People: Ada, Bob (inactive), Cleo (not asked: can't see the check-in)\n",
            self.biwak("checkins", "show", self.item.pk).output,
        )

    def test_due(self):
        output = self.biwak("checkins", "due").output
        for text in ["How are you?", "Website", "2027-03-22", "[clients]"]:
            self.assertIn(text, output)
        data = json.loads(self.biwak("checkins", "due", "--json").stdout)
        self.assertEqual(data[0]["occurrence_id"], self.occurrence.pk)
        self.biwak("checkins", "answer", self.item.pk, "Fine")
        self.assertNotIn("How are you?", self.biwak("checkins", "due").output)
        self.assertEqual(
            json.loads(
                self.biwak(
                    "checkins", "due", "--json", "--project", self.project.pk
                ).stdout
            ),
            [],
        )

    def test_add_pause_resume_and_mail(self):
        result = self.biwak(
            "checkins", "create", self.project.pk, "What did you read?",
            "--schedule", "weekly", "--time", "08:30", "--from", "2027-03-26",
            "--people", self.ada.pk, "--json",
        )  # fmt: skip
        data = json.loads(result.stdout)
        question = Question.objects.get(item=data["id"])
        self.assertEqual(question.rule, "FREQ=WEEKLY;BYDAY=FR")
        self.assertEqual(question.time_of_day, dt.time(8, 30))
        self.assertFalse(data["visible_to_clients"])
        self.assertIn("Added #", self.biwak(
            "checkins", "create", self.project.pk, "Daily", "--schedule", "FREQ=DAILY",
            "--time", "09:00", "--clients",
        ).output)  # fmt: skip
        self.assertTrue(Question.objects.filter(item__title="Daily").exists())
        self.assertEqual(
            self.biwak(
                "checkins",
                "create",
                self.project.pk,
                "Bad",
                "--schedule",
                "sometimes",
                "--time",
                "09:00",
            ).exit_code,
            1,
        )

        self.assertIn("Paused", self.biwak("checkins", "pause", self.item.pk).output)
        self.assertTrue(Question.objects.get(item=self.item).is_paused)
        self.assertIn("Resumed", self.biwak("checkins", "resume", self.item.pk).output)
        self.assertFalse(Question.objects.get(item=self.item).is_paused)

        self.assertIn("summary", self.biwak("checkins", "mail", self.item.pk).output)
        self.biwak("checkins", "mail", self.item.pk, "each")
        self.assertEqual(QuestionMail.objects.get().mode, Mode.EACH)
        self.assertEqual(
            self.biwak("checkins", "mail", self.item.pk, "sometimes").exit_code, 2
        )

    def test_resume_all_of_a_project(self):
        ops.pause(self.item, actor=self.ada)
        result = self.biwak("checkins", "resume", "--project", self.project.pk)
        self.assertIn("Resumed 1 check-in", result.output)
        self.assertFalse(Question.objects.get(item=self.item).is_paused)
        ops.pause(self.item, actor=self.ada)
        data = json.loads(
            self.biwak(
                "checkins", "resume", "--project", self.project.pk, "--json"
            ).stdout
        )
        self.assertEqual([q["id"] for q in data], [self.item.pk])
        self.assertEqual(self.biwak("checkins", "resume").exit_code, 2)
        self.assertEqual(
            self.biwak("checkins", "resume", self.item.pk, "--project", 1).exit_code, 2
        )
        self.assertEqual(
            self.biwak(
                "checkins", "resume", "--project", self.project.pk, access="read"
            ).exit_code,
            1,
        )

    def test_read_only_and_errors(self):
        result = self.biwak("checkins", "answer", self.item.pk, "Hi", access="read")
        self.assertEqual(result.exit_code, 1)
        self.assertIn("only allows reading", result.output)
        result = self.biwak("checkins", "show", 999999)
        self.assertEqual(result.exit_code, 1)
        self.assertIn("404", result.output)
        # Not asked, but seeing it: answers (decided 2026-11-21)
        ops.set_people(self.item, [self.bob], actor=self.ada)
        result = self.biwak("checkins", "answer", self.item.pk, "Hi")
        self.assertEqual(result.exit_code, 0, result.output)
