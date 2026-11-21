import datetime as dt

from biwak.accounts.models import APIToken
from biwak.activity.models import Mention
from biwak.checkins import operations as ops
from biwak.checkins.models import Mode, Occurrence, QuestionMail
from biwak.checkins.support import CheckinTestCase
from biwak.items import operations as item_ops
from biwak.items.models import Item
from biwak.test_utils import person, project


class APITestCase(CheckinTestCase):
    def setUp(self):
        super().setUp()
        self.shared = self.question(
            "Shared question", visible=True, people=[self.ada, self.cleo]
        )
        self.run_at("2027-03-22 09:00")
        self.first = Occurrence.objects.filter(question__item=self.item).get()
        self.sent()

    def api(self, user, access="write"):
        _token, secret = APIToken.create_for(user=user, title="Test", access=access)
        return {"authorization": f"Bearer {secret}"}

    def get(self, user, path, **params):
        return self.client.get(f"/api/v1/{path}", params, headers=self.api(user))

    def send(self, method, user, path, data=None, access="write"):
        return getattr(self.client, method)(
            f"/api/v1/{path}",
            data or {},
            content_type="application/json",
            headers=self.api(user, access),
        )

    def post(self, user, path, data=None, **kwargs):
        return self.send("post", user, path, data, **kwargs)

    def patch(self, user, path, data=None):
        return self.send("patch", user, path, data)


class QuestionsAPITest(APITestCase):
    def test_list(self):
        data = self.get(self.ada, f"projects/{self.project.pk}/checkins/").json()
        self.assertEqual(
            [q["title"] for q in data], ["How are you?", "Shared question"]
        )
        question = data[0]
        self.assertEqual(question["rule"], "FREQ=WEEKLY;BYDAY=MO")
        self.assertEqual(question["schedule_description"], "every Monday")
        self.assertEqual(question["time_of_day"], "09:00:00")
        self.assertEqual(question["time_zone"], "Europe/Zurich")
        self.assertNotIn("remind_after", question, "no reminders")
        self.assertEqual(
            sorted(p["short_name"] for p in question["people"]), ["Ada", "Bob"]
        )
        self.assertFalse(question["paused"])
        self.assertFalse(question["visible_to_clients"])
        self.assertTrue(data[1]["visible_to_clients"])
        self.assertEqual(question["latest_occurrence_id"], self.first.pk)
        self.assertEqual(question["mail"], "summary")
        self.assertEqual(question["next_at"], "2027-03-29T07:00:00Z")
        self.assertEqual(question["kind"], "question")
        self.assertEqual(
            question["url"], f"https://biwak.example.org/questions/{question['id']}/"
        )

    def test_a_client_gets_visible_questions_only(self):
        data = self.get(self.cleo, f"projects/{self.project.pk}/checkins/").json()
        self.assertEqual([q["title"] for q in data], ["Shared question"])
        self.assertEqual(
            self.get(self.cleo, f"checkins/{self.item.pk}/").status_code, 404
        )
        self.assertEqual(
            self.get(self.cleo, f"checkins/{self.shared.pk}/").status_code, 200
        )

    def test_somebody_elses_project_is_404(self):
        other = project("Secret", all_access=False)
        self.assertEqual(
            self.get(self.ada, f"projects/{other.pk}/checkins/").status_code, 404
        )
        self.assertEqual(
            self.post(
                self.ada,
                f"projects/{other.pk}/checkins/",
                {"title": "x", "schedule": "weekly", "time_of_day": "09:00"},
            ).status_code,
            404,
        )

    def test_create(self):
        response = self.post(
            self.ada,
            f"projects/{self.project.pk}/checkins/",
            {
                "title": "What did you read?",
                "schedule": "weekly",
                "starts_on": "2027-03-26",
                "time_of_day": "08:30",
                "time_zone": "Europe/Zurich",
                "people": [self.ada.pk, self.bob.pk],
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()
        self.assertEqual(data["rule"], "FREQ=WEEKLY;BYDAY=FR")
        self.assertEqual(len(data["people"]), 2)
        self.assertEqual(data["creator"]["short_name"], "Ada")
        self.assertIsNotNone(data["next_at"])

    def test_create_defaults(self):
        data = self.post(
            self.ada,
            f"projects/{self.project.pk}/checkins/",
            {"title": "Defaults", "schedule": "FREQ=DAILY", "time_of_day": "09:00"},
        ).json()
        self.assertEqual(data["time_zone"], "Europe/Zurich")
        self.assertEqual(data["starts_on"], dt.date.today().isoformat())
        data = self.post(
            self.ada,
            f"projects/{self.project.pk}/checkins/",
            {
                "title": "Weekdays",
                "schedule": "weekdays",
                "time_of_day": "09:00",
            },
        ).json()
        self.assertEqual(data["rule"], "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR")

    def test_create_mistakes(self):
        base = {"title": "Bad", "schedule": "weekly", "time_of_day": "09:00"}
        for changes in [
            {"schedule": "sometimes"},
            {"schedule": "FREQ=HOURLY"},
            {"time_zone": "Mars/Olympus"},
            {"people": [999999]},
            {"people": [self.cleo.pk]},  # internal
            {"time_of_day": "late"},
            # Looped forever (INTERVAL=0) or never asked (a huge interval)
            {"schedule": "FREQ=DAILY;INTERVAL=0"},
            {"schedule": "FREQ=DAILY;INTERVAL=99999999999"},
            {"schedule": "FREQ=MONTHLY;BYMONTHDAY=0"},
            # A 500 (DataError) or an empty title
            {"title": "x" * 501},
            {"title": "   "},
        ]:
            response = self.post(
                self.ada, f"projects/{self.project.pk}/checkins/", base | changes
            )
            self.assertIn(response.status_code, {400, 422}, changes)
        self.assertFalse(Item.objects.filter(title="Bad").exists())

    def test_create_for_clients_on_visible_questions(self):
        data = self.post(
            self.ada,
            f"projects/{self.project.pk}/checkins/",
            {
                "title": "With a client", "schedule": "weekly", "time_of_day": "09:00",
                "people": [self.cleo.pk], "visible_to_clients": True,
            },
        ).json()  # fmt: skip
        self.assertTrue(data["visible_to_clients"])
        self.assertEqual(data["people"][0]["short_name"], "Cleo")

    def test_clients_and_read_only_tokens_cant_write(self):
        path = f"projects/{self.project.pk}/checkins/"
        body = {"title": "Mine", "schedule": "weekly", "time_of_day": "09:00"}
        self.assertEqual(self.post(self.cleo, path, body).status_code, 403)
        self.assertEqual(
            self.patch(
                self.cleo, f"checkins/{self.shared.pk}/", {"title": "x"}
            ).status_code,
            403,
        )
        self.assertEqual(
            self.post(self.ada, path, body, access="read").status_code, 403
        )
        self.assertFalse(Item.objects.filter(title="Mine").exists())

    def test_update(self):
        response = self.patch(
            self.ada,
            f"checkins/{self.item.pk}/",
            {
                "title": "How is it going?", "schedule": "biweekly",
                "starts_on": "2027-03-22", "time_of_day": "10:00",
                "time_zone": "Asia/Tokyo", "people": [self.bob.pk],
            },
        )  # fmt: skip
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(data["title"], "How is it going?")
        self.assertEqual(data["rule"], "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO")
        self.assertEqual(data["time_of_day"], "10:00:00")
        self.assertEqual(data["time_zone"], "Asia/Tokyo")
        self.assertEqual([p["short_name"] for p in data["people"]], ["Bob"])

    def test_update_checks_the_title(self):
        for title in ["", "   ", "x" * 501]:
            response = self.patch(
                self.ada, f"checkins/{self.item.pk}/", {"title": title}
            )
            self.assertIn(response.status_code, {400, 422}, title)
        self.item.refresh_from_db()
        self.assertEqual(self.item.title, "How are you?")

    def test_update_refuses_a_schedule_which_hangs(self):
        for schedule in ["FREQ=DAILY;INTERVAL=0", "FREQ=DAILY;INTERVAL=-1"]:
            response = self.patch(
                self.ada, f"checkins/{self.item.pk}/", {"schedule": schedule}
            )
            self.assertEqual(response.status_code, 400, schedule)

    def test_update_leaves_out_what_doesnt_change(self):
        data = self.patch(
            self.ada, f"checkins/{self.item.pk}/", {"title": "New"}
        ).json()
        self.assertEqual(data["rule"], "FREQ=WEEKLY;BYDAY=MO")
        self.assertEqual(len(data["people"]), 2)
        for body in [
            {"title": None},
            {"title": ""},
            {"schedule": None},
            {"time_of_day": None},
        ]:
            self.assertIn(
                self.patch(self.ada, f"checkins/{self.item.pk}/", body).status_code,
                {400, 422},
            )
        for body in [
            {"schedule": "FREQ=SECONDLY"},
            {"time_zone": "x/y"},
        ]:
            self.assertEqual(
                self.patch(self.ada, f"checkins/{self.item.pk}/", body).status_code,
                400,
                body,
            )

    def test_people_null_is_refused(self):
        response = self.patch(self.ada, f"checkins/{self.item.pk}/", {"people": None})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.item.question.people.count(), 2)

    def test_clients_get_404_before_403(self):
        """A client can't learn that a project or question exists"""
        other = project("Secret", members=[self.ada])
        body = {"title": "x", "schedule": "weekly", "time_of_day": "09:00"}
        self.assertEqual(
            self.post(self.cleo, f"projects/{other.pk}/checkins/", body).status_code,
            404,
        )
        self.assertEqual(
            self.patch(
                self.cleo, f"checkins/{self.item.pk}/", {"title": "x"}
            ).status_code,
            404,
        )

    def test_pause_and_resume(self):
        data = self.patch(
            self.ada, f"checkins/{self.item.pk}/", {"paused": True}
        ).json()
        self.assertTrue(data["paused"])
        self.assertIsNone(data["next_at"])
        self.assertEqual(
            self.run_at("2027-03-29 09:00")["asked"], 1, "only the other one"
        )
        data = self.patch(
            self.ada, f"checkins/{self.item.pk}/", {"paused": False}
        ).json()
        self.assertFalse(data["paused"])
        self.assertIsNotNone(data["next_at"])

    def test_trashing_through_the_items_endpoint(self):
        response = self.client.delete(
            f"/api/v1/items/{self.item.pk}/", headers=self.api(self.ada)
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.get(self.ada, f"checkins/{self.item.pk}/").status_code, 404
        )

    def test_the_visibility_switch(self):
        self.send(
            "put",
            self.ada,
            f"items/{self.item.pk}/visibility/",
            {"visible_to_clients": True},
        )
        self.assertEqual(
            self.get(self.cleo, f"checkins/{self.item.pk}/").status_code, 200
        )


class AnswersAPITest(APITestCase):
    def test_answer_and_change_it(self):
        response = self.post(
            self.ada, f"checkins/{self.item.pk}/answer/", {"content": "Fine **really**"}
        )
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(data["content"], "Fine **really**")
        self.assertIn("<strong>really</strong>", data["content_html"])
        self.assertEqual(data["author"]["short_name"], "Ada")
        self.assertEqual(data["occurrence_id"], self.first.pk)
        self.assertEqual(data["kind"], "answer")
        self.assertEqual(data["parent_id"], self.item.pk)
        again = self.post(
            self.ada, f"checkins/{self.item.pk}/answer/", {"content": "Better"}
        ).json()
        self.assertEqual(again["id"], data["id"])
        self.assertEqual(Item.objects.filter(kind="answer").count(), 1)

    def test_answer_an_older_occurrence_and_mentions(self):
        self.run_at("2027-03-29 09:00")
        data = self.post(
            self.ada,
            f"checkins/{self.item.pk}/answer/",
            {
                "content": "Back then, thanks @bob@example.org",
                "occurrence_id": self.first.pk,
            },
        ).json()
        self.assertEqual(data["occurrence_id"], self.first.pk)
        self.assertIn(f"(person:{self.bob.pk})", data["content"])

    def test_clients_mention_members_only(self):
        """Not staff who see the project because it's all-access
        (specs/access.md)"""
        dora = person("Dora")
        data = self.post(
            self.cleo,
            f"checkins/{self.shared.pk}/answer/",
            {"content": f"@Dora, [@x](person:{dora.pk}) and @Ada"},
        ).json()
        self.assertTrue(data["content"].startswith("@Dora, "), data["content"])
        self.assertIn(f"(person:{self.ada.pk})", data["content"])
        self.assertNotIn("Dora Example", data["content_html"])
        answer = Item.objects.get(pk=data["id"])
        self.assertFalse(Mention.objects.filter(item=answer, user=dora).exists())
        self.assertTrue(Mention.objects.filter(item=answer, user=self.ada).exists())

    def test_mistakes(self):
        path = f"checkins/{self.item.pk}/answer/"
        self.assertEqual(self.post(self.ada, path, {"content": "  "}).status_code, 400)
        self.assertEqual(
            self.post(
                self.ada, path, {"content": "x", "occurrence_id": 999999}
            ).status_code,
            404,
        )
        other = Occurrence.objects.filter(question__item=self.shared).get()
        self.assertEqual(
            self.post(
                self.ada, path, {"content": "x", "occurrence_id": other.pk}
            ).status_code,
            404,
        )
        new = self.question("New", people=[self.ada])
        self.assertEqual(
            self.post(
                self.ada, f"checkins/{new.pk}/answer/", {"content": "Too early"}
            ).status_code,
            400,
        )

    def test_only_people_asked_and_who_can_see(self):
        dora = person("Dora")
        self.assertEqual(
            self.post(
                dora, f"checkins/{self.item.pk}/answer/", {"content": "Hi"}
            ).status_code,
            403,
        )
        # A client: the internal question doesn't exist for them
        self.assertEqual(
            self.post(
                self.cleo, f"checkins/{self.item.pk}/answer/", {"content": "Hi"}
            ).status_code,
            404,
        )
        data = self.post(
            self.cleo, f"checkins/{self.shared.pk}/answer/", {"content": "Hi"}
        ).json()
        self.assertTrue(data["visible_to_clients"])

    def test_read_only_tokens_cant_answer(self):
        response = self.post(
            self.ada,
            f"checkins/{self.item.pk}/answer/",
            {"content": "Hi"},
            access="read",
        )
        self.assertEqual(response.status_code, 403)

    def test_occurrences_with_answers(self):
        ops.answer(self.item, user=self.ada, content="One")
        self.run_at("2027-03-29 09:00")
        ops.answer(self.item, user=self.bob, content="Two")
        data = self.get(self.ada, f"checkins/{self.item.pk}/occurrences/").json()
        self.assertEqual(
            [o["date"] for o in data["results"]], ["2027-03-29", "2027-03-22"]
        )
        latest, older = data["results"]
        self.assertEqual([a["content"] for a in latest["answers"]], ["Two"])
        self.assertEqual([a["content"] for a in older["answers"]], ["One"])
        self.assertEqual([p["short_name"] for p in latest["missing"]], ["Ada"])
        self.assertIsNone(older["missing"])
        self.assertIsNone(data["next"])

    def test_occurrences_paginate(self):
        for n in range(4):
            self.run_at(f"2027-04-{5 + 7 * n:02d} 09:00")
        data = self.get(
            self.ada, f"checkins/{self.item.pk}/occurrences/", page_size=2
        ).json()
        self.assertEqual(len(data["results"]), 2)
        self.assertIsNotNone(data["next"])
        seen = [o["id"] for o in data["results"]]
        cursor = data["next"].split("cursor=")[1].split("&")[0]
        from urllib.parse import unquote

        data = self.get(
            self.ada,
            f"checkins/{self.item.pk}/occurrences/",
            page_size=2,
            cursor=unquote(cursor),
        ).json()
        seen += [o["id"] for o in data["results"]]
        self.assertEqual(len(set(seen)), 4)
        self.assertEqual(seen, sorted(seen, reverse=True))

    def test_occurrences_of_one_person(self):
        ops.answer(self.item, user=self.ada, content="Ada's")
        ops.answer(self.item, user=self.bob, content="Bob's")
        self.run_at("2027-03-29 09:00")
        data = self.get(
            self.ada, f"checkins/{self.item.pk}/occurrences/", person_id=self.bob.pk
        ).json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(
            [a["content"] for a in data["results"][0]["answers"]], ["Bob's"]
        )

    def test_clients_dont_see_internal_answers(self):
        ops.answer(self.shared, user=self.cleo, content="Client answer")
        ops.answer(self.item, user=self.ada, content="Internal answer")
        data = self.get(self.cleo, f"checkins/{self.shared.pk}/occurrences/").json()
        self.assertEqual(data["results"][0]["answers"][0]["content"], "Client answer")
        self.assertEqual(
            self.get(self.cleo, f"checkins/{self.item.pk}/occurrences/").status_code,
            404,
        )

    def test_clients_dont_see_staff_who_arent_members(self):
        outsider = person("Dora")  # all-access projects: staff need no membership
        ops.set_people(self.shared, [self.ada, self.cleo, outsider], actor=self.ada)
        self.run_at("2027-03-29 09:00")

        def names(user):
            question = self.get(user, f"checkins/{self.shared.pk}/").json()
            occurrences = self.get(user, f"checkins/{self.shared.pk}/occurrences/")
            latest = occurrences.json()["results"][0]
            return (
                {p["short_name"] for p in question["people"]},
                {p["short_name"] for p in latest["missing"]},
            )

        self.assertEqual(names(self.cleo), ({"Ada", "Cleo"}, {"Ada", "Cleo"}))
        self.assertEqual(
            names(self.ada), ({"Ada", "Cleo", "Dora"}, {"Ada", "Cleo", "Dora"})
        )
        listed = self.get(self.cleo, f"projects/{self.project.pk}/checkins/").json()
        self.assertNotIn("Dora", str(listed))

    def test_comments_on_answers_use_the_comment_endpoints(self):
        answer = self.post(
            self.ada, f"checkins/{self.item.pk}/answer/", {"content": "Fine"}
        ).json()
        response = self.post(
            self.bob, f"items/{answer['id']}/comments/", {"content": "Glad"}
        )
        self.assertEqual(response.status_code, 201)
        comments = self.get(self.ada, f"items/{answer['id']}/comments/").json()
        self.assertEqual(comments["results"][0]["content"], "Glad")
        self.assertEqual(
            self.post(
                self.bob, f"items/{self.item.pk}/comments/", {"content": "x"}
            ).status_code,
            400,
        )

    def test_mail_mode(self):
        path = f"checkins/{self.item.pk}/mail/"
        self.assertEqual(self.get(self.bob, path).json()["mode"], "summary")
        response = self.send("put", self.bob, path, {"mode": "each"})
        self.assertEqual(response.json(), {"question_id": self.item.pk, "mode": "each"})
        self.assertEqual(QuestionMail.objects.get().mode, Mode.EACH)
        self.assertEqual(
            self.get(self.bob, f"checkins/{self.item.pk}/").json()["mail"], "each"
        )
        self.assertEqual(self.get(self.ada, path).json()["mode"], "summary")
        self.assertEqual(
            self.send("put", self.bob, path, {"mode": "sometimes"}).status_code, 422
        )
        self.assertEqual(
            self.send("put", self.cleo, path, {"mode": "each"}).status_code, 404
        )

    def test_due(self):
        data = self.get(self.ada, "me/checkins/due/").json()
        self.assertEqual(
            sorted(d["title"] for d in data), ["How are you?", "Shared question"]
        )
        item = next(d for d in data if d["title"] == "How are you?")
        self.assertEqual(item["occurrence_id"], self.first.pk)
        self.assertEqual(item["date"], "2027-03-22")
        self.assertEqual(item["project_name"], "Website")
        self.assertEqual(
            item["url"],
            f"https://biwak.example.org/questions/{self.item.pk}/answer/?occurrence={self.first.pk}",
        )
        self.post(self.ada, f"checkins/{self.item.pk}/answer/", {"content": "x"})
        data = self.get(self.ada, "me/checkins/due/").json()
        self.assertEqual([d["title"] for d in data], ["Shared question"])
        data = self.get(self.ada, "me/checkins/due/", project_id=self.project.pk).json()
        self.assertEqual(len(data), 1)
        # A client's: only what they see
        data = self.get(self.cleo, "me/checkins/due/").json()
        self.assertEqual([d["title"] for d in data], ["Shared question"])
        item_ops.set_visibility(
            Item.objects.get(pk=self.shared.pk), visible=False, actor=self.ada
        )
        self.assertEqual(self.get(self.cleo, "me/checkins/due/").json(), [])
