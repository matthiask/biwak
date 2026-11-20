import datetime as dt

from django.urls import reverse

from biwak.activity.models import Event
from biwak.checkins import operations as ops
from biwak.checkins.models import Mode, Occurrence, Question, QuestionMail
from biwak.checkins.support import CheckinTestCase
from biwak.items import operations as item_ops
from biwak.items.models import Item
from biwak.projects.models import Membership
from biwak.test_utils import person, project


class ViewsTestCase(CheckinTestCase):
    def setUp(self):
        super().setUp()
        self.shared = self.question(
            "Shared question", visible=True, people=[self.ada, self.cleo]
        )
        self.run_at("2027-03-22 09:00")
        self.first = Occurrence.objects.filter(question__item=self.item).get()
        self.occurrence = Occurrence.objects.filter(question__item=self.shared).get()
        self.sent()

    def get(self, user, url, **kwargs):
        self.client.force_login(user)
        return self.client.get(url, **kwargs)

    def post(self, user, url, data=None, **kwargs):
        self.client.force_login(user)
        return self.client.post(url, data or {}, **kwargs)

    def url(self, name, item=None, *args):
        return reverse(name, args=[item.pk if item else self.item.pk, *args])


class PagesTest(ViewsTestCase):
    def test_the_projects_check_ins(self):
        response = self.get(
            self.ada, reverse("project_checkins", args=[self.project.pk])
        )
        self.assertContains(response, "How are you?")
        self.assertContains(response, "Shared question")
        self.assertContains(response, "Every Monday")
        self.assertContains(response, "09:00 Europe/Zurich")
        self.assertContains(response, "next: Mon 29. Mar 2027, 09:00")
        self.assertContains(response, "Waiting for your answer")
        self.assertContains(response, "New check-in")

    def test_paused_questions_say_so(self):
        ops.pause(self.item, actor=self.ada)
        ops.pause(self.shared, actor=self.ada)
        response = self.get(
            self.ada, reverse("project_checkins", args=[self.project.pk])
        )
        self.assertContains(response, "paused")
        self.assertNotContains(response, "next: Mon 29. Mar 2027")

    def test_a_client_sees_only_visible_questions(self):
        response = self.get(
            self.cleo, reverse("project_checkins", args=[self.project.pk])
        )
        self.assertContains(response, "Shared question")
        self.assertNotContains(response, "How are you?")
        self.assertNotContains(response, "New check-in")
        self.assertContains(response, "wb-client-badge")

    def test_nobody_outside_the_project(self):
        other = project("Secret", all_access=False)
        self.assertEqual(
            self.get(
                self.ada, reverse("project_checkins", args=[other.pk])
            ).status_code,
            404,
        )

    def test_the_question_page(self):
        self.run_at("2027-03-29 09:00")
        ops.answer(self.item, user=self.ada, content="Busy with the **launch**")
        ops.answer(self.item, user=self.bob, content="Reading", occurrence=self.first)
        response = self.get(self.ada, self.item.get_absolute_url())
        self.assertContains(response, "<strong>launch</strong>")
        self.assertContains(response, "Monday, 29. March 2027")
        self.assertContains(response, "Monday, 22. March 2027")
        self.assertContains(response, "Hasn't answered yet:")
        self.assertContains(response, "Bob")
        self.assertContains(response, "Every Monday,\n    09:00 Europe/Zurich")
        self.assertContains(response, "Show to clients")
        self.assertNotContains(response, "Clients can see this")
        self.assertNotContains(response, "reminder")

    def test_the_page_lists_those_who_didnt_answer(self):
        ops.answer(self.item, user=self.ada, content="Fine")
        ops.answer(self.item, user=self.bob, content="Fine too")
        response = self.get(self.ada, self.item.get_absolute_url())
        self.assertNotContains(response, "Hasn't answered yet:")

    def test_older_occurrences_are_paginated_by_date(self):
        # Eight more Mondays
        for n in range(8):
            self.run_at(f"2027-04-{5 + 7 * n:02d} 09:00") if n < 4 else self.run_at(
                f"2027-05-{(5 + 7 * n) - 30:02d} 09:00"
            )
        total = Occurrence.objects.filter(question__item=self.item).count()
        self.assertGreater(total, 5)
        response = self.get(self.ada, self.item.get_absolute_url())
        self.assertEqual(len(response.context["rows"]), 5)
        more = response.context["more"]
        self.assertEqual(more, response.context["rows"][-1][0].date.isoformat())
        older = self.get(self.ada, self.item.get_absolute_url() + f"?before={more}")
        self.assertEqual(len(older.context["rows"]), total - 5)
        self.assertTrue(
            all(o.date < dt.date.fromisoformat(more) for o, _a in older.context["rows"])
        )
        self.assertEqual(
            self.get(
                self.ada, self.item.get_absolute_url() + "?before=garbage"
            ).status_code,
            404,
        )

    def test_an_occurrence_by_id_starts_the_list_there(self):
        self.run_at("2027-03-29 09:00")
        response = self.get(
            self.ada, self.item.get_absolute_url() + f"?occurrence={self.first.pk}"
        )
        self.assertEqual([o for o, _a in response.context["rows"]], [self.first])
        for bad in ["garbage", "999999"]:
            self.assertEqual(
                self.get(
                    self.ada, self.item.get_absolute_url() + f"?occurrence={bad}"
                ).status_code,
                404,
            )

    def test_the_urls_of_answers(self):
        answer = ops.answer(self.item, user=self.ada, content="Fine")
        self.assertEqual(
            answer.get_absolute_url(),
            f"/questions/{self.item.pk}/?occurrence={self.first.pk}#answer-{answer.pk}",
        )
        response = self.get(self.ada, answer.get_absolute_url())
        self.assertContains(response, f'id="answer-{answer.pk}"')

    def test_a_clients_page(self):
        ops.answer(self.shared, user=self.cleo, content="Hello from the client")
        ops.answer(self.item, user=self.ada, content="Internal answer")
        response = self.get(self.cleo, self.shared.get_absolute_url())
        self.assertContains(response, "Hello from the client")
        self.assertContains(response, "Clients can see this.")
        self.assertNotContains(response, "Show to clients")
        self.assertNotContains(response, self.url("question_edit", self.shared))
        self.assertNotContains(response, "Pause")
        self.assertNotContains(response, "History")
        self.assertEqual(
            self.get(self.cleo, self.item.get_absolute_url()).status_code, 404
        )

    def test_clients_dont_see_staff_who_arent_members(self):
        outsider = person("Dora")  # all-access projects: staff need no membership
        ops.set_people(self.item, [self.ada, self.bob, outsider], actor=self.ada)
        ops.set_people(self.shared, [self.ada, self.cleo, outsider], actor=self.ada)
        response = self.get(self.cleo, self.shared.get_absolute_url())
        self.assertNotContains(response, "Dora")
        self.assertContains(self.get(self.ada, self.shared.get_absolute_url()), "Dora")

    def test_clients_dont_see_staff_who_arent_members_as_missing(self):
        outsider = person("Dora")
        ops.set_people(self.shared, [self.ada, self.cleo, outsider], actor=self.ada)
        self.run_at("2027-03-29 09:00")
        response = self.get(self.cleo, self.shared.get_absolute_url())
        self.assertNotContains(response, "Dora")
        self.assertIn(self.ada, response.context["missing"])
        response = self.get(self.ada, self.shared.get_absolute_url())
        self.assertIn(outsider, response.context["missing"])

    def test_a_client_cant_open_the_persons_page_of_a_non_member(self):
        outsider = person("Dora")
        ops.set_people(self.shared, [self.ada, self.cleo, outsider], actor=self.ada)
        url = self.url("question_person", self.shared, outsider.pk)
        self.assertEqual(self.get(self.cleo, url).status_code, 404)
        self.assertEqual(self.get(self.ada, url).status_code, 200)
        url = self.url("question_person", self.shared, self.ada.pk)
        self.assertEqual(self.get(self.cleo, url).status_code, 200)

    def test_a_person_answers_over_time(self):
        ops.answer(self.item, user=self.ada, content="Now")
        self.run_at("2027-03-29 09:00")
        ops.answer(self.item, user=self.ada, content="Later")
        ops.answer(self.item, user=self.bob, content="Bob's")
        response = self.get(
            self.ada, self.url("question_person", self.item, self.ada.pk)
        )
        self.assertContains(response, "Later")
        self.assertContains(response, "Now")
        self.assertNotContains(response, "Bob&#x27;s")
        self.assertContains(response, "Ada Example")
        self.assertEqual(
            [a.content for a in response.context["answers"]], ["Later", "Now"]
        )

    def test_a_persons_page_paginates(self):
        for n in range(7):
            self.run_at(f"2027-04-{5 + 7 * n:02d} 09:00") if n < 4 else self.run_at(
                f"2027-05-{(5 + 7 * n) - 30:02d} 09:00"
            )
            ops.answer(self.item, user=self.ada, content=f"Answer {n}")
        url = self.url("question_person", self.item, self.ada.pk)
        response = self.get(self.ada, url)
        self.assertEqual(len(response.context["answers"]), 5)
        older = self.get(self.ada, url + f"?before={response.context['more']}")
        self.assertEqual(len(older.context["answers"]), 2)
        self.assertEqual(self.get(self.ada, url + "?before=x").status_code, 404)

    def test_a_persons_page_without_answers_or_not_asked_is_404(self):
        dora = person("Dora")
        self.assertEqual(
            self.get(
                self.ada, self.url("question_person", self.item, dora.pk)
            ).status_code,
            404,
        )
        self.assertEqual(
            self.get(
                self.ada, self.url("question_person", self.item, 99999)
            ).status_code,
            404,
        )
        # Asked, no answers yet
        self.assertEqual(
            self.get(
                self.ada, self.url("question_person", self.item, self.bob.pk)
            ).status_code,
            200,
        )

    def test_a_client_cant_open_the_persons_page_of_an_internal_question(self):
        self.assertEqual(
            self.get(
                self.cleo, self.url("question_person", self.item, self.ada.pk)
            ).status_code,
            404,
        )

    def test_the_project_page_shows_what_is_due(self):
        response = self.get(self.ada, self.project.get_absolute_url())
        self.assertContains(response, "Waiting for your answer")
        self.assertContains(
            response, f"/questions/{self.item.pk}/answer/?occurrence={self.first.pk}"
        )
        self.assertContains(response, "Check-ins")
        ops.answer(self.item, user=self.ada, content="Fine")
        ops.answer(self.shared, user=self.ada, content="Fine")
        response = self.get(self.ada, self.project.get_absolute_url())
        self.assertNotContains(response, "Waiting for your answer")

    def test_the_project_page_of_a_client_shows_only_visible_questions_due(self):
        response = self.get(self.cleo, self.project.get_absolute_url())
        self.assertContains(response, "Shared question")
        self.assertNotContains(response, "How are you?")

    def test_the_feed_and_the_history(self):
        ops.answer(self.item, user=self.ada, content="Fine")
        response = self.get(self.ada, reverse("feed"))
        self.assertContains(response, "answered")
        self.assertContains(response, "How are you?")
        self.assertContains(
            self.get(self.ada, reverse("item_history", args=[self.item.pk])),
            "How are you?",
        )
        # A client's feed doesn't know the internal answer
        response = self.get(self.cleo, reverse("feed"))
        self.assertNotContains(response, "How are you?")


class FormsTest(ViewsTestCase):
    def data(self, **kwargs):
        return {
            "title": "What did you read?",
            "repeat": "weekly",
            "custom_rule": "",
            "starts_on": "2027-03-26",
            "time_of_day": "08:30",
            "time_zone": "Europe/Zurich",
            "people": [self.ada.pk, self.bob.pk],
        } | kwargs

    def test_creating_a_question(self):
        url = reverse("question_new", args=[self.project.pk])
        self.assertContains(self.get(self.ada, url), "New check-in")
        response = self.post(self.ada, url, self.data())
        item = Item.objects.get(title="What did you read?")
        self.assertRedirects(response, item.get_absolute_url())
        question = item.question
        self.assertEqual(question.rule, "FREQ=WEEKLY;BYDAY=FR", "from the first date")
        self.assertEqual(question.time_of_day, dt.time(8, 30))
        self.assertEqual(set(question.people.all()), {self.ada, self.bob})
        self.assertFalse(item.is_client_visible)
        self.assertEqual(item.creator, self.ada)
        self.assertIsNotNone(question.next_at)

    def test_creating_one_visible_to_clients_with_a_client(self):
        url = reverse("question_new", args=[self.project.pk])
        self.post(
            self.ada,
            url,
            self.data(
                title="Shared too",
                visible="on",
                people=[self.ada.pk, self.cleo.pk],
            ),
        )
        item = Item.objects.get(title="Shared too")
        self.assertTrue(item.is_client_visible)
        self.assertIn(self.cleo, item.question.people.all())

    def test_a_client_cant_be_asked_on_an_internal_question(self):
        url = reverse("question_new", args=[self.project.pk])
        response = self.post(self.ada, url, self.data(people=[self.cleo.pk]))
        self.assertContains(
            response, "Clients can only be asked about check-ins they can see."
        )
        self.assertFalse(Item.objects.filter(title="What did you read?").exists())

    def test_an_internal_question_keeps_its_clients_when_edited(self):
        item_ops.set_visibility(self.shared, visible=False, actor=self.ada)
        url = self.url("question_edit", self.shared)
        initial = self.get(self.ada, url).context["form"].initial
        data = {k: v for k, v in initial.items() if v is not None}
        data["people"] = [u.pk for u in data["people"]]
        response = self.post(self.ada, url, data | {"title": "Renamed"})
        self.assertEqual(response.status_code, 302)
        self.shared.refresh_from_db()
        self.assertEqual(self.shared.title, "Renamed")
        self.assertIn(self.cleo, self.shared.question.people.all())
        # Adding another client is still refused
        other = person("Dora", client=True)
        Membership.objects.create(project=self.project, user=other)
        response = self.post(
            self.ada, url, data | {"people": [*data["people"], other.pk]}
        )
        self.assertContains(
            response, "Clients can only be asked about check-ins they can see."
        )

    def test_a_custom_schedule_and_mistakes(self):
        url = reverse("question_new", args=[self.project.pk])
        self.post(
            self.ada, url,
            self.data(repeat="custom", custom_rule="FREQ=WEEKLY;BYDAY=MO,TH"),
        )  # fmt: skip
        self.assertEqual(
            Item.objects.get(title="What did you read?").question.rule,
            "FREQ=WEEKLY;BYDAY=MO,TH",
        )
        for data in [
            {"repeat": "custom", "custom_rule": ""},
            {"repeat": "custom", "custom_rule": "FREQ=HOURLY"},
            {"time_zone": "Mars/Olympus"},
            {"time_of_day": ""},
            {"starts_on": ""},
            {"title": ""},
        ]:
            response = self.post(self.ada, url, self.data(title="Bad") | data)
            self.assertEqual(response.status_code, 200, data)
            self.assertFalse(Item.objects.filter(title="Bad").exists(), data)

    def test_clients_cant_create_or_edit(self):
        url = reverse("question_new", args=[self.project.pk])
        self.assertEqual(self.get(self.cleo, url).status_code, 403)
        self.assertEqual(
            self.post(self.cleo, url, self.data(title="Mine")).status_code, 403
        )
        self.assertFalse(Item.objects.filter(title="Mine").exists())
        for method in [self.get, self.post]:
            self.assertEqual(
                method(self.cleo, self.url("question_edit", self.shared)).status_code,
                403,
            )
        self.assertEqual(
            self.post(self.cleo, self.url("question_pause", self.shared)).status_code,
            403,
        )
        self.assertFalse(Question.objects.get(item=self.shared).is_paused)

    def test_editing(self):
        url = self.url("question_edit", self.item)
        response = self.get(self.ada, url)
        form = response.context["form"]
        self.assertEqual(form.initial["repeat"], "weekly")
        self.assertEqual(form.initial["time_of_day"], dt.time(9, 0))
        self.assertContains(response, "Edit the check-in")
        response = self.post(
            self.ada,
            url,
            self.data(
                title="How is it going?", repeat="biweekly", starts_on="2027-03-22",
                time_of_day="10:00", people=[self.bob.pk],
            ),
        )  # fmt: skip
        self.assertRedirects(response, self.item.get_absolute_url())
        item = Item.objects.get(pk=self.item.pk)
        self.assertEqual(item.title, "How is it going?")
        self.assertEqual(item.question.rule, "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO")
        self.assertEqual(item.question.time_of_day, dt.time(10, 0))
        self.assertEqual(set(item.question.people.all()), {self.bob})

    def test_editing_a_custom_schedule_shows_it(self):
        ops.update_question(self.item, actor=self.ada, rule="FREQ=WEEKLY;BYDAY=MO,TH")
        form = self.get(self.ada, self.url("question_edit", self.item)).context["form"]
        self.assertEqual(form.initial["repeat"], "custom")
        self.assertEqual(form.initial["custom_rule"], "FREQ=WEEKLY;BYDAY=MO,TH")

    def test_saving_keeps_a_rule_for_another_weekday_or_day(self):
        """Rules from the API or the CLI (first date a Friday): saving the
        form with a new title keeps them"""
        for rule in [
            "FREQ=WEEKLY;BYDAY=MO",
            "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO",
            "FREQ=MONTHLY;BYMONTHDAY=1",
            "FREQ=MONTHLY;BYDAY=MO;BYSETPOS=1",
            "FREQ=MONTHLY;BYDAY=MO;BYSETPOS=-1",
            "FREQ=YEARLY;BYMONTH=1;BYMONTHDAY=1",
        ]:
            item = self.question(rule, rule=rule, starts_on=dt.date(2027, 3, 19))
            url = self.url("question_edit", item)
            initial = self.get(self.ada, url).context["form"].initial
            data = {k: v for k, v in initial.items() if v is not None}
            data["people"] = [u.pk for u in data["people"]]
            response = self.post(self.ada, url, data | {"title": "Renamed"})
            self.assertEqual(response.status_code, 302, rule)
            self.assertEqual(Question.objects.get(item=item).rule, rule)

    def test_editing_a_visible_question_keeps_the_clients(self):
        response = self.post(
            self.ada,
            self.url("question_edit", self.shared),
            self.data(people=[self.ada.pk, self.cleo.pk]),
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn(
            self.cleo, Item.objects.get(pk=self.shared.pk).question.people.all()
        )

    def test_pausing_and_resuming(self):
        self.post(self.ada, self.url("question_pause", self.item))
        self.assertTrue(Question.objects.get(item=self.item).is_paused)
        self.assertContains(self.get(self.ada, self.item.get_absolute_url()), "Resume")
        self.post(self.ada, self.url("question_pause", self.item), {"resume": "1"})
        self.assertFalse(Question.objects.get(item=self.item).is_paused)
        self.assertContains(self.get(self.ada, self.item.get_absolute_url()), "Pause")
        self.assertEqual(
            self.client.get(self.url("question_pause", self.item)).status_code, 405
        )

    def test_trashing_a_question(self):
        response = self.post(self.ada, reverse("item_trash", args=[self.item.pk]))
        self.assertRedirects(
            response, self.project.get_absolute_url(), fetch_redirect_response=False
        )
        self.assertEqual(self.client.get(self.item.get_absolute_url()).status_code, 404)
        self.assertEqual(self.run_at("2027-03-29 09:00")["asked"], 1, "the other one")

    def test_the_switch(self):
        self.post(self.ada, reverse("switch", args=[self.item.pk]), {"visible": "1"})
        self.assertTrue(Item.objects.get(pk=self.item.pk).is_client_visible)
        self.assertContains(
            self.get(self.cleo, self.item.get_absolute_url()), "Clients can see this."
        )


class AnsweringPagesTest(ViewsTestCase):
    def test_the_form(self):
        response = self.get(self.ada, self.url("question_answer", self.item))
        self.assertContains(response, "How are you?")
        self.assertNotContains(response, "Skip")
        self.assertContains(response, "data-attachments")
        self.assertContains(response, "Monday, 22. March 2027")
        self.assertEqual(response.context["occurrence"], self.first)

    def test_answering(self):
        url = self.url("question_answer", self.item)
        self.client.force_login(self.ada)
        response = self.client.post(
            url, {"content": "Fine", "occurrence": self.first.pk}
        )
        answer = Item.objects.get(kind="answer")
        self.assertRedirects(response, answer.get_absolute_url())
        self.assertEqual(answer.answer.content, "Fine")
        self.assertEqual(answer.answer.occurrence, self.first)
        # The form now shows it, to change
        response = self.client.get(url)
        self.assertContains(response, "Fine")
        self.assertContains(response, "Save the answer")
        self.client.post(url, {"content": "Better"})
        self.assertEqual(Item.objects.get(pk=answer.pk).answer.content, "Better")
        self.assertEqual(Item.objects.filter(kind="answer").count(), 1)

    def test_an_empty_answer_is_refused(self):
        response = self.post(
            self.ada, self.url("question_answer", self.item), {"content": " "}
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Item.objects.filter(kind="answer").exists())

    def test_answering_an_older_occurrence_by_id(self):
        self.run_at("2027-03-29 09:00")
        url = self.url("question_answer", self.item)
        self.post(
            self.ada, f"{url}?occurrence={self.first.pk}", {"content": "Back then"}
        )
        self.assertEqual(Item.objects.get(kind="answer").answer.occurrence, self.first)
        response = self.get(self.ada, url)
        self.assertEqual(response.context["occurrence"].date, dt.date(2027, 3, 29))

    def test_another_questions_occurrence_is_404(self):
        for bad in [f"?occurrence={self.occurrence.pk}", "?occurrence=x"]:
            url = self.url("question_answer", self.item)
            self.assertEqual(self.get(self.ada, url + bad).status_code, 404, bad)

    def test_not_asked_yet_is_404(self):
        item = self.question("New", people=[self.ada])
        self.assertEqual(
            self.get(self.ada, self.url("question_answer", item)).status_code, 404
        )

    def test_only_people_asked(self):
        # Bob sees it, but Cleo isn't asked the internal question: 404 (can't see)
        dora = person("Dora")
        for user in [dora]:
            self.assertEqual(
                self.get(user, self.url("question_answer", self.item)).status_code, 403
            )
            self.assertEqual(
                self.post(
                    user, self.url("question_answer", self.item), {"content": "Hi"}
                ).status_code,
                403,
            )
        self.assertEqual(
            self.get(self.cleo, self.url("question_answer", self.item)).status_code, 404
        )
        self.assertFalse(Item.objects.filter(kind="answer").exists())

    def test_a_client_answers_a_visible_question(self):
        url = self.url("question_answer", self.shared)
        self.assertContains(self.get(self.cleo, url), "Clients can see this.")
        self.post(self.cleo, url, {"content": "From the client"})
        self.assertTrue(Item.objects.get(kind="answer").is_client_visible)

    def test_the_mail_mode(self):
        self.post(self.bob, self.url("question_mail", self.item), {"mode": "each"})
        self.assertEqual(QuestionMail.objects.get().mode, Mode.EACH)
        self.assertContains(self.get(self.bob, self.item.get_absolute_url()), "checked")
        self.assertEqual(
            self.post(
                self.bob, self.url("question_mail", self.item), {"mode": "x"}
            ).status_code,
            404,
        )
        # A client can't choose for what they can't see
        self.assertEqual(
            self.post(
                self.cleo, self.url("question_mail", self.item), {"mode": "each"}
            ).status_code,
            404,
        )

    def test_commenting_on_an_answer(self):
        answer = ops.answer(self.item, user=self.ada, content="Fine")
        response = self.post(
            self.bob,
            reverse("answer_comment", args=[answer.pk]),
            {"content": "Glad to hear"},
        )
        self.assertRedirects(response, answer.get_absolute_url())
        self.assertContains(
            self.get(self.ada, self.item.get_absolute_url()), "Glad to hear"
        )
        # Nothing on a question, nothing on an answer a client can't see
        self.assertEqual(
            self.post(
                self.bob,
                reverse("answer_comment", args=[self.item.pk]),
                {"content": "x"},
            ).status_code,
            404,
        )
        self.assertEqual(
            self.post(
                self.cleo, reverse("answer_comment", args=[answer.pk]), {"content": "x"}
            ).status_code,
            404,
        )

    def test_a_client_comments_on_a_visible_answer(self):
        answer = ops.answer(self.shared, user=self.ada, content="Fine")
        self.post(
            self.cleo, reverse("answer_comment", args=[answer.pk]), {"content": "Hello"}
        )
        self.assertEqual(answer.comments.get().author, self.cleo)

    def test_trashing_an_answer(self):
        answer = ops.answer(self.item, user=self.ada, content="Oops")
        self.post(self.ada, reverse("item_trash", args=[answer.pk]))
        self.assertNotContains(self.get(self.ada, self.item.get_absolute_url()), "Oops")
        self.assertEqual(Event.objects.filter(item=answer, action="trashed").count(), 1)

    def test_login_required(self):
        self.client.logout()
        for url in [
            self.item.get_absolute_url(),
            self.url("question_answer", self.item),
            reverse("project_checkins", args=[self.project.pk]),
        ]:
            self.assertEqual(self.client.get(url).status_code, 302)
