import datetime as dt
import json
import re

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from biwak.accounts.models import APIToken
from biwak.activity.models import Event
from biwak.checkins import operations as ops
from biwak.checkins.models import Mode, Occurrence, Question, QuestionMail
from biwak.checkins.support import CheckinTestCase
from biwak.items import operations as item_ops
from biwak.items.models import Item
from biwak.organizations import activation
from biwak.projects.models import Membership
from biwak.teams import operations as team_ops
from biwak.test_utils import person, project, rule_post, tags


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
    def test_subscribers_a_list_of_their_own(self):
        """The question's subscribers hear about the answers, the people
        asked are only who's asked (decided 2026-11-21): the subscribers
        card, Subscribe/Unsubscribe and adding others, through the page and
        the API"""
        dora = person("Dora")
        Membership.objects.create(project=self.project, user=dora)
        url = self.url("question", self.shared)
        response = self.get(dora, url)
        self.assertContains(response, reverse("subscription", args=[self.shared.pk]))
        self.assertContains(
            response, reverse("item_subscribers", args=[self.shared.pk])
        )
        self.assertContains(response, ">Subscribe<")
        self.post(
            dora, reverse("subscription", args=[self.shared.pk]), {"subscribe": "1"}
        )
        self.assertContains(self.get(dora, url), ">Unsubscribe<")
        self.assertFalse(self.shared.question.people.filter(pk=dora.pk).exists())
        # Clients see the subscribers (members), not those of internal
        # questions
        self.assertContains(self.get(self.cleo, url), "Dora Example")
        self.assertEqual(
            self.get(
                self.cleo, reverse("item_subscribers", args=[self.item.pk])
            ).status_code,
            404,
        )
        # The API's subscribers work for questions like for any item
        _token, secret = APIToken.create_for(user=self.ada, title="T", access="write")
        headers = {"authorization": f"Bearer {secret}"}
        response = self.client.post(
            f"/api/v1/items/{self.shared.pk}/subscribers/",
            {"people": [self.bob.pk]},
            content_type="application/json",
            headers=headers,
        )
        self.assertEqual(response.status_code, 200, response.content)
        names = {s["person"]["name"] for s in response.json()["subscribers"]}
        self.assertEqual(
            names, {"Ada Example", "Cleo Example", "Dora Example", "Bob Example"}
        )

    def test_the_projects_check_ins(self):
        response = self.get(
            self.ada, reverse("project_checkins", args=[self.project.pk])
        )
        self.assertContains(response, "How are you?")
        self.assertContains(response, "Shared question")
        self.assertContains(response, "Every Monday")
        self.assertContains(response, "09:00")
        self.assertContains(response, "next: Mon, 29 Mar 2027, 09:00")
        self.assertContains(response, "Waiting for your answer")
        self.assertContains(response, "New check-in")

    def test_paused_questions_say_so(self):
        ops.pause(self.item, actor=self.ada)
        ops.pause(self.shared, actor=self.ada)
        response = self.get(
            self.ada, reverse("project_checkins", args=[self.project.pk])
        )
        self.assertContains(response, "paused")
        self.assertNotContains(response, "next: Mon, 29 Mar 2027")

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
        self.assertContains(response, "Monday, 29 March 2027")
        self.assertContains(response, "Monday, 22 March 2027")
        self.assertContains(response, "Hasn't answered yet:")
        self.assertContains(response, "Bob")
        self.assertContains(response, "Every Monday,\n    09:00\n")
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
            "rule_frequency": "weekly",
            "rule_interval": "1",
            "rule_weekdays": ["FR"],
            "starts_on": "2027-03-26",
            "time_of_day": "08:30",
            "people": [self.ada.pk, self.bob.pk],
        } | kwargs

    def test_creating_a_question(self):
        url = reverse("question_new", args=[self.project.pk])
        response = self.get(self.ada, url)
        self.assertContains(response, "New check-in")
        # The installation's time zone is the only one (decided 2026-11-22)
        self.assertNotContains(response, 'name="time_zone"')
        response = self.post(self.ada, url, self.data())
        item = Item.objects.get(title="What did you read?")
        self.assertRedirects(response, item.get_absolute_url())
        question = item.question
        self.assertEqual(question.rule, "FREQ=WEEKLY;BYDAY=FR")
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

    def test_people_asked_with_the_picker_and_teams(self):
        # The people picker with teams, clients following "Visible to
        # clients" (decided 2026-11-22)
        team_ops.create_team(
            name="Readers", members=[self.bob, self.cleo], actor=self.ada
        )

        def picker(response):
            html = response.content.decode()
            (select,) = tags(html, cls="form-select", name="people")
            option = re.search(rf'<option value="{self.cleo.pk}"[^>]*>', html)
            return html, select, option[0] if option else None

        url = reverse("question_new", args=[self.project.pk])
        html, select, cleo = picker(self.get(self.ada, url))
        self.assertIn("data-people-picker", select)
        self.assertEqual(select["data-clients-follow"], "#id_visible")
        (team,) = json.loads(select["data-teams"])
        self.assertEqual(team["name"], "Readers")
        self.assertEqual(
            {m["id"] for m in team["members"]}, {self.bob.pk, self.cleo.pk}
        )
        # Clients are there, offered only once the box is ticked
        self.assertIn("data-client", cleo)
        self.assertIn("disabled", cleo)
        self.assertLess(html.index('name="visible"'), html.index('name="people"'))
        _html, _select, cleo = picker(
            self.post(self.ada, url, self.data(visible="on", title=""))
        )
        self.assertNotIn("disabled", cleo)
        # Editing a visible question offers its clients, the switch is
        # elsewhere
        _html, select, cleo = picker(
            self.get(self.ada, self.url("question_edit", self.shared))
        )
        self.assertNotIn("data-clients-follow", select)
        self.assertNotIn("disabled", cleo)
        self.assertIn("Readers", select["data-teams"])
        # An internal one offers none
        _html, select, cleo = picker(self.get(self.ada, self.url("question_edit")))
        self.assertIsNone(cleo)
        (team,) = json.loads(select["data-teams"])
        (left_out,) = [m for m in team["members"] if m["id"] == self.cleo.pk]
        self.assertEqual(left_out["reason"], "can't see internal items")

    def test_editing_keeps_people_asked_who_were_deactivated(self):
        # Kept, not added (decided 2026-11-28), like a to-do's assignees
        activation.deactivate([self.bob], actor=person("Root", is_admin=True))
        url = self.url("question_edit")
        response = self.get(self.ada, url)
        self.assertContains(response, f'value="{self.bob.pk}" selected')
        response = self.post(self.ada, url, self.data(title="How are you?"))
        self.assertRedirects(response, self.item.get_absolute_url())
        self.assertEqual(set(self.item.question.people.all()), {self.ada, self.bob})
        url = reverse("question_new", args=[self.project.pk])
        response = self.post(self.ada, url, self.data(title="New"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Item.objects.filter(title="New").exists())

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
        data = {k: v for k, v in initial.items() if v is not None and k != "rule"}
        data["people"] = [u.pk for u in data["people"]]
        data |= rule_post(initial["rule"], "rule")
        response = self.post(self.ada, url, data | {"title": "Renamed"})
        self.assertEqual(response.status_code, 302)
        self.shared.refresh_from_db()
        self.assertEqual(self.shared.title, "Renamed")
        self.assertIn(self.cleo, self.shared.question.people.all())
        # Adding another client is still refused: not offered at all
        other = person("Dora", client=True)
        Membership.objects.create(project=self.project, user=other)
        response = self.get(self.ada, url)
        self.assertContains(response, f'<option value="{self.cleo.pk}"')
        self.assertNotContains(response, f'<option value="{other.pk}"')
        response = self.post(
            self.ada, url, data | {"people": [*data["people"], other.pk]}
        )
        self.assertContains(response, "Select a valid choice.")
        self.assertNotIn(other, self.shared.question.people.all())

    def test_another_schedule_and_mistakes(self):
        url = reverse("question_new", args=[self.project.pk])
        self.post(self.ada, url, self.data(rule_weekdays=["MO", "TH"]))
        self.assertEqual(
            Item.objects.get(title="What did you read?").question.rule,
            "FREQ=WEEKLY;BYDAY=MO,TH",
        )
        for data in [
            {"rule_frequency": ""},
            {"rule_weekdays": []},
            {"rule_interval": "100"},
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
        self.assertEqual(form.initial["rule"], "FREQ=WEEKLY;BYDAY=MO")
        self.assertEqual(form.initial["time_of_day"], dt.time(9, 0))
        self.assertContains(response, "Edit the check-in")
        response = self.post(
            self.ada,
            url,
            self.data(
                title="How is it going?", rule_interval="2", rule_weekdays=["MO"],
                starts_on="2027-03-22",
                time_of_day="10:00", people=[self.bob.pk],
            ),
        )  # fmt: skip
        self.assertRedirects(response, self.item.get_absolute_url())
        item = Item.objects.get(pk=self.item.pk)
        self.assertEqual(item.title, "How is it going?")
        self.assertEqual(item.question.rule, "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO")
        self.assertEqual(item.question.time_of_day, dt.time(10, 0))
        self.assertEqual(set(item.question.people.all()), {self.bob})

    def test_a_schedule_the_widget_cant_show_stays_unless_replaced(self):
        rule = "FREQ=WEEKLY;BYDAY=MO,TH;BYSETPOS=1"
        ops.update_question(self.item, actor=self.ada, rule=rule)
        url = self.url("question_edit", self.item)
        response = self.get(self.ada, url)
        self.assertEqual(response.context["form"].initial["rule"], rule)
        self.assertContains(response, "can't be edited here")
        response = self.post(self.ada, url, self.data(title="Same", rule_keep="1"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Question.objects.get(item=self.item).rule, rule)
        response = self.post(
            self.ada, url, self.data(title="Same", rule_keep="1", rule_replace="1")
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            Question.objects.get(item=self.item).rule, "FREQ=WEEKLY;BYDAY=FR"
        )

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
            "FREQ=MONTHLY;BYMONTHDAY=1,15",
            "FREQ=WEEKLY",
        ]:
            item = self.question(rule, rule=rule, starts_on=dt.date(2027, 3, 19))
            url = self.url("question_edit", item)
            data = self.data(title="Renamed", people=[self.ada.pk])
            data = {k: v for k, v in data.items() if not k.startswith("rule_")}
            data |= rule_post(rule, "rule")
            response = self.post(self.ada, url, data)
            self.assertEqual(response.status_code, 302, rule)
            self.assertEqual(Question.objects.get(item=item).rule, rule)

    def test_keep_without_a_stored_rule_is_a_form_error(self):
        url = reverse("question_new", args=[self.project.pk])
        data = self.data(rule_keep="1")
        data = {k: v for k, v in data.items() if k != "rule_frequency"}
        response = self.post(self.ada, url, data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Item.objects.filter(title="What did you read?").exists())

    def test_saving_an_unchanged_form_changes_nothing(self):
        """Rules are stored in their canonical form, which the widget shows
        (decided 2026-11-21)"""
        for written, rule in [
            ("FREQ=WEEKLY;BYDAY=TH,MO", "FREQ=WEEKLY;BYDAY=MO,TH"),
            ("FREQ=WEEKLY;INTERVAL=1;BYDAY=MO", "FREQ=WEEKLY;BYDAY=MO"),
            ("FREQ=WEEKLY;BYDAY=MO;WKST=MO", "FREQ=WEEKLY;BYDAY=MO"),
        ]:
            item = self.question(written, rule=written, starts_on=dt.date(2027, 3, 22))
            before = Question.objects.get(item=item)
            self.assertEqual(before.rule, rule)
            page = self.get(self.ada, self.url("question_edit", item))
            self.assertNotContains(page, "can't be edited here")
            events = item.events.count()
            data = self.data(
                title=item.title,
                starts_on="2027-03-22",
                time_of_day=before.time_of_day.strftime("%H:%M"),
            )
            data = {k: v for k, v in data.items() if not k.startswith("rule_")}
            data |= rule_post(rule, "rule")
            data["people"] = [self.ada.pk]
            response = self.post(self.ada, self.url("question_edit", item), data)
            self.assertEqual(response.status_code, 302, rule)
            after = Question.objects.get(item=item)
            self.assertEqual(after.rule, rule)
            self.assertEqual(after.next_at, before.next_at)
            self.assertEqual(item.events.count(), events, rule)

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

    def test_resuming_all_of_the_projects_check_ins(self):
        url = reverse("project_checkins_resume", args=[self.project.pk])
        page = reverse("project_checkins", args=[self.project.pk])
        self.assertNotContains(self.get(self.ada, page), url)
        ops.pause(self.item, actor=self.ada)
        ops.pause(self.shared, actor=self.ada)
        self.assertContains(self.get(self.ada, page), url)
        # A client sees neither the button nor can use it
        self.assertNotContains(self.get(self.cleo, page), url)
        self.assertEqual(self.post(self.cleo, url).status_code, 403)
        self.assertTrue(Question.objects.get(item=self.item).is_paused)
        self.assertEqual(self.client.get(url).status_code, 405)
        response = self.post(self.ada, url)
        self.assertRedirects(response, page)
        for item in (self.item, self.shared):
            self.assertFalse(Question.objects.get(item=item).is_paused)
        self.assertNotContains(self.get(self.ada, page), url)

    def test_resuming_all_in_a_project_nobody_sees_is_a_404(self):
        other = project("Secret", members=[self.ada])
        url = reverse("project_checkins_resume", args=[other.pk])
        self.assertEqual(self.post(self.cleo, url).status_code, 404)

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
        self.assertNotContains(response, ">Skip<")
        self.assertContains(response, "data-attachments")
        self.assertContains(response, "Monday, 22 March 2027")
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

    def test_anybody_who_sees_it(self):
        """Asked or not (decided 2026-11-21): Dora isn't asked but sees it
        and answers; Cleo can't see the internal question: 404"""
        dora = person("Dora")
        url = self.url("question_answer", self.item)
        self.assertEqual(self.get(dora, url).status_code, 200)
        self.assertContains(self.get(dora, self.url("question", self.item)), url)
        self.post(dora, url, {"content": "Hi"})
        self.assertEqual(Item.objects.get(kind="answer").creator, dora)
        self.assertEqual(self.get(self.cleo, url).status_code, 404)
        self.assertEqual(self.post(self.cleo, url, {"content": "Hi"}).status_code, 404)

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

    def test_every_answer_has_its_own_comment_form(self):
        """Own field IDs, mentions and attachments like other comment forms"""
        first = ops.answer(self.item, user=self.ada, content="Fine")
        second = ops.answer(self.item, user=self.bob, content="Also fine")
        html = self.get(self.ada, self.item.get_absolute_url()).content.decode()
        self.assertNotIn('id="id_content"', html)
        for answer in (first, second):
            self.assertEqual(html.count(f'id="id_answer_{answer.pk}_content"'), 1)
            self.assertIn(
                f'data-mentions="{reverse("mentionable", args=[answer.pk])}"', html
            )
        self.assertEqual(html.count("data-attachments="), 2)
        self.assertEqual(html.count("data-attach-template"), 2)

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


class QueryCountTest(ViewsTestCase):
    def test_reactions_are_loaded_in_one_query(self):
        """More answers and comments don't mean more queries"""
        from biwak.reactions.operations import add_reaction

        self.run_at("2027-03-29 09:00")

        def add_answer(user, occurrence=None):
            answer = ops.answer(
                self.item, user=user, content=f"By {user}", occurrence=occurrence
            )
            add_reaction(self.ada, "🎉", item=answer)
            comment = item_ops.add_comment(answer, author=self.ada, content="Nice")
            add_reaction(self.bob, "👍", comment=comment)

        url = self.item.get_absolute_url()
        self.client.force_login(self.ada)

        add_answer(self.ada)
        self.client.get(url)  # warm up caches
        with CaptureQueriesContext(connection) as queries:
            self.client.get(url)
        add_answer(self.bob)
        add_answer(self.ada, self.first)
        add_answer(self.bob, self.first)
        with self.assertNumQueries(len(queries)):
            self.assertEqual(self.client.get(url).status_code, 200)

    def test_links_to_answers_in_feeds(self):
        """An answer's link needs its occurrence: loaded for all events at
        once, on the pages and in the API"""
        pages = [
            reverse("feed"),
            reverse("project_feed", args=[self.project.pk]),
            reverse("project", args=[self.project.pk]),
            "/api/v1/feed/",
        ]
        _token, secret = APIToken.create_for(user=self.ada, title="T", access="read")
        headers = {"authorization": f"Bearer {secret}"}
        self.client.force_login(self.ada)
        ops.answer(self.item, user=self.ada, content="One")

        def counts():
            result = []
            for url in pages:
                with CaptureQueriesContext(connection) as queries:
                    self.assertEqual(
                        self.client.get(url, headers=headers).status_code, 200
                    )
                result.append(len(queries))
            return result

        counts()  # warm up caches
        few = counts()
        ops.answer(self.item, user=self.bob, content="Two")
        ops.answer(self.item, user=self.ada, content="Three", occurrence=self.first)
        self.assertEqual(counts(), few)
