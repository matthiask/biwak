"""Quiet hours and out of office (specs/quiet-hours.md): the settings, the
person's page, the marks, pickers, the @ list and teams, the API; as staff,
as an admin and as a client. Sending: biwak/activity/test_quiet_hours.py."""

import datetime as dt
import json
import zoneinfo

import time_machine
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse

from biwak.accounts import operations
from biwak.accounts.models import APIToken, User
from biwak.activity.operations import set_notification_settings
from biwak.items import operations as ops
from biwak.teams.operations import create_team
from biwak.test_utils import person, project


ZURICH = zoneinfo.ZoneInfo("Europe/Zurich")
# Monday 23 November 2026, 10:00 in Zurich
NOW = dt.datetime(2026, 11, 23, 10, 0, tzinfo=ZURICH)
NOTE = "back on the 4th, ask Ada meanwhile"
TITLE = f"Away until 3 Dec: {NOTE}"
NOTICE = f"Bob is away until 3 Dec: {NOTE}"


class QuietBase(TestCase):
    def setUp(self):
        traveller = time_machine.travel(NOW, tick=False)
        traveller.start()
        self.addCleanup(traveller.stop)
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        # A client of another project: may not know Bob
        self.eve = person("Eve", client=True)
        self.admin = person("Zoe", is_admin=True)
        self.project = project(members=[self.ada, self.bob, self.cleo])
        project("Other", members=[self.eve])
        self.shared = ops.create_list(
            project=self.project, title="Shared", creator=self.ada, visible=True
        )
        self.todo = ops.create_todo(
            todolist=self.shared,
            title="Order the tent",
            creator=self.ada,
            assignees=[self.bob],
        )
        operations.set_away(
            self.bob, until=dt.date(2026, 12, 3), note=NOTE, actor=self.bob
        )

    def refresh(self, user):
        user.refresh_from_db()
        return user


class OperationsTest(QuietBase):
    def test_away(self):
        self.assertTrue(self.bob.is_away)
        self.assertEqual(self.bob.away_text, TITLE)
        operations.end_away(self.bob, actor=self.bob)
        self.assertEqual((self.bob.away_until, self.bob.away_note), (None, ""))
        self.assertFalse(self.bob.is_away)

    def test_without_a_note(self):
        operations.set_away(self.ada, until=dt.date(2026, 11, 23), actor=self.ada)
        self.assertEqual(self.ada.away_text, "Away until 23 Nov")

    def test_another_year_says_it(self):
        operations.set_away(self.ada, until=dt.date(2027, 1, 4), actor=self.ada)
        self.assertEqual(self.ada.away_text, "Away until 4 Jan 2027")

    def test_ends_by_itself_the_day_after(self):
        with time_machine.travel(dt.datetime(2026, 12, 3, 23, 59, tzinfo=ZURICH)):
            self.assertTrue(self.refresh(self.bob).is_away)
        with time_machine.travel(dt.datetime(2026, 12, 4, 0, 0, tzinfo=ZURICH)):
            self.assertFalse(self.refresh(self.bob).is_away)
            self.assertEqual(self.bob.away_text, "")

    def test_one_line_and_at_most_200_characters(self):
        operations.set_away(
            self.ada, until=dt.date(2026, 12, 1), note=" a\nb  c ", actor=self.ada
        )
        self.assertEqual(self.ada.away_note, "a b c")
        with self.assertRaises(ValidationError):
            operations.set_away(
                self.ada, until=dt.date(2026, 12, 1), note="x" * 201, actor=self.ada
            )

    def test_not_in_the_past(self):
        with self.assertRaises(ValidationError):
            operations.set_away(self.ada, until=dt.date(2026, 11, 22), actor=self.ada)

    def test_admins_for_others(self):
        operations.set_away(self.ada, until=dt.date(2026, 12, 1), actor=self.admin)
        self.assertTrue(self.ada.is_away)
        operations.end_away(self.ada, actor=self.admin)
        self.assertFalse(self.ada.is_away)
        for actor in [self.bob, self.cleo]:
            with self.subTest(actor=actor), self.assertRaises(PermissionDenied):
                operations.set_away(self.ada, until=dt.date(2026, 12, 1), actor=actor)
            with self.subTest(actor=actor), self.assertRaises(PermissionDenied):
                operations.end_away(self.bob, actor=self.ada)

    def test_quiet_hours(self):
        set_notification_settings(
            self.ada,
            quiet_hours=True,
            working_days=[4, 0, 0],
            working_from=dt.time(7, 30),
            working_until=dt.time(16),
        )
        ada = self.refresh(self.ada)
        self.assertEqual(
            (ada.quiet_hours, ada.working_days, ada.working_from, ada.working_until),
            (True, [0, 4], dt.time(7, 30), dt.time(16)),
        )
        for kwargs in [
            {"working_from": dt.time(16)},
            {"working_until": dt.time(7)},
            {"working_days": []},
            {"working_days": [7]},
        ]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValidationError):
                set_notification_settings(self.refresh(self.ada), **kwargs)
        self.assertEqual(self.refresh(self.ada).working_days, [0, 4])


class SettingsPageTest(QuietBase):
    url = "/accounts/settings/"

    def notifications(self, **data):
        return self.client.post(
            "/accounts/settings/notifications/",
            {"notification_level": "everything", "mail_delivery": "each"} | data,
        )

    def test_the_page(self):
        for user in [self.ada, self.cleo]:
            with self.subTest(user=user):
                self.client.force_login(user)
                response = self.client.get(self.url)
                self.assertContains(response, "Quiet hours")
                self.assertContains(response, "Working days")
                self.assertContains(
                    response, "In the time zone Europe/Zurich, the same for everybody."
                )
                self.assertContains(response, 'value="08:00"')
                self.assertContains(response, "Out of office")
                self.assertNotContains(response, "/accounts/settings/back/")

    def test_quiet_hours(self):
        self.client.force_login(self.cleo)
        response = self.notifications(
            quiet_hours="on",
            working_days=["0", "2"],
            working_from="09:00",
            working_until="17:30",
        )
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        cleo = self.refresh(self.cleo)
        self.assertEqual(
            (
                cleo.quiet_hours,
                cleo.working_days,
                cleo.working_from,
                cleo.working_until,
            ),
            (True, [0, 2], dt.time(9), dt.time(17, 30)),
        )
        # Off: the days and hours stay for next time
        self.notifications()
        cleo = self.refresh(self.cleo)
        self.assertFalse(cleo.quiet_hours)
        self.assertEqual(cleo.working_days, [0, 2])
        self.assertEqual(cleo.working_from, dt.time(9))

    def test_errors(self):
        self.client.force_login(self.ada)
        response = self.notifications(
            quiet_hours="on", working_days=["0"], working_until="07:00"
        )
        self.assertContains(response, "The working hours end after they start.")
        response = self.notifications(quiet_hours="on")
        self.assertContains(response, "Choose at least one working day.")
        self.assertFalse(self.refresh(self.ada).quiet_hours)

    def test_away(self):
        for user in [self.ada, self.cleo]:
            with self.subTest(user=user):
                self.client.force_login(user)
                response = self.client.post(
                    "/accounts/settings/away/",
                    {"away_until": "2026-11-30", "away_note": "Hiking"},
                )
                self.assertRedirects(
                    response, self.url + "#away", fetch_redirect_response=False
                )
                self.refresh(user)
                self.assertEqual(user.away_until, dt.date(2026, 11, 30))
                response = self.client.get(self.url)
                self.assertContains(response, "Away until 30 Nov: Hiking")
                self.assertContains(response, "/accounts/settings/back/")
                self.assertContains(response, 'value="2026-11-30"')
                self.client.post("/accounts/settings/back/")
                self.assertFalse(self.refresh(user).is_away)

    def test_away_errors(self):
        self.client.force_login(self.ada)
        response = self.client.post(
            "/accounts/settings/away/", {"away_until": "2026-11-22"}
        )
        self.assertContains(response, "Choose today or a later day.")
        response = self.client.post(
            "/accounts/settings/away/",
            {"away_until": "2026-11-30", "away_note": "x" * 201},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.refresh(self.ada).is_away)


class PersonPageTest(QuietBase):
    def test_says_so(self):
        for user in [self.ada, self.cleo, self.bob]:
            with self.subTest(user=user):
                self.client.force_login(user)
                response = self.client.get(reverse("person", args=[self.bob.pk]))
                self.assertContains(response, TITLE)
                self.assertContains(response, "wb-away-sign")
                self.assertNotContains(response, "Set away…")

    def test_clients_who_may_not_know_them(self):
        self.client.force_login(self.eve)
        response = self.client.get(reverse("person", args=[self.bob.pk]))
        self.assertEqual(response.status_code, 404)

    def test_admins_set_others_away(self):
        self.client.force_login(self.admin)
        url = reverse("person_away", args=[self.ada.pk])
        page = self.client.get(reverse("person", args=[self.ada.pk]))
        self.assertContains(page, "Set away…")
        self.assertNotContains(page, "End away")
        response = self.client.get(url, headers={"HX-Modal": "1"})
        self.assertContains(response, "Set Ada Example away")
        response = self.client.post(
            url, {"away_until": "2026-11-27", "away_note": "Sick"}
        )
        self.assertRedirects(
            response,
            reverse("person", args=[self.ada.pk]),
            fetch_redirect_response=False,
        )
        self.assertEqual(self.refresh(self.ada).away_note, "Sick")
        page = self.client.get(reverse("person", args=[self.ada.pk]))
        self.assertContains(page, "End away")
        self.client.post(reverse("person_back", args=[self.ada.pk]))
        self.assertFalse(self.refresh(self.ada).is_away)
        # One's own in the settings
        response = self.client.get(reverse("person_away", args=[self.admin.pk]))
        self.assertRedirects(
            response, "/accounts/settings/#away", fetch_redirect_response=False
        )

    def test_others_dont(self):
        for user in [self.ada, self.cleo]:
            with self.subTest(user=user):
                self.client.force_login(user)
                url = reverse("person_away", args=[self.bob.pk])
                self.assertEqual(self.client.get(url).status_code, 404)
                self.assertEqual(
                    self.client.post(url, {"away_until": "2026-12-24"}).status_code,
                    404,
                )
                back = reverse("person_back", args=[self.bob.pk])
                self.assertEqual(self.client.post(back).status_code, 404)
                self.assertTrue(self.refresh(self.bob).is_away)


class ShownTest(QuietBase):
    def test_the_mark_on_the_to_do(self):
        for user in [self.ada, self.cleo]:
            with self.subTest(user=user):
                self.client.force_login(user)
                response = self.client.get(self.todo.get_absolute_url())
                self.assertContains(response, f'title="Bob Example\n{TITLE}"')
                self.assertContains(response, 'class="wb-away-sign"')

    def test_not_after_the_return(self):
        self.client.force_login(self.ada)
        with time_machine.travel(dt.datetime(2026, 12, 4, 8, tzinfo=ZURICH)):
            response = self.client.get(self.todo.get_absolute_url())
        self.assertNotContains(response, "wb-away-sign")
        self.assertNotContains(response, "Away until")

    def test_the_picker(self):
        for user in [self.ada, self.cleo]:
            with self.subTest(user=user):
                self.client.force_login(user)
                response = self.client.get(reverse("todo_edit", args=[self.todo.pk]))
                self.assertContains(response, 'data-away="away until 3 Dec"')
                self.assertContains(response, f'data-away-note="{NOTICE}"')
                self.assertContains(response, "&quot;away&quot;: &quot;Away until")

    def test_the_mention_list(self):
        for user in [self.ada, self.cleo]:
            with self.subTest(user=user):
                self.client.force_login(user)
                response = self.client.get(f"/items/{self.todo.pk}/mentionable/?q=bob")
                (bob,) = response.json()
                self.assertTrue(bob["available"])
                self.assertEqual(bob["away"], "away until 3 Dec")
                self.assertEqual(bob["away_note"], NOTICE)
                self.assertEqual(bob["avatar"]["away"], TITLE)
                response = self.client.get(f"/items/{self.todo.pk}/mentionable/?q=ada")
                (ada,) = response.json()
                self.assertEqual((ada["away"], ada["away_note"]), ("", ""))
                self.assertNotIn("away", ada["avatar"])

    def test_teams(self):
        team = create_team(name="Camp", members=[self.ada, self.bob], actor=self.ada)
        self.client.force_login(self.ada)
        response = self.client.get(reverse("team", args=[team.pk]))
        self.assertContains(
            response, '<span class="wb-away-detail">away until 3 Dec</span>'
        )
        response = self.client.get(reverse("people"))
        self.assertContains(
            response, '<span class="wb-away-detail">(away until 3 Dec)</span>'
        )
        response = self.client.get(f"/items/{self.todo.pk}/mentionable/?q=camp")
        (entry,) = [e for e in response.json() if e.get("team")]
        notes = {m["id"]: m["away_note"] for m in entry["members"]}
        self.assertEqual(notes, {self.ada.pk: "", self.bob.pk: NOTICE})

    def test_still_assignable(self):
        self.client.force_login(self.ada)
        other = ops.create_todo(todolist=self.shared, title="Pack", creator=self.ada)
        response = self.client.post(
            other.get_absolute_url(),
            {"form": "todo", "title": "Pack", "assignees": [self.bob.pk]},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(list(other.todo.assignees.all()), [self.bob])


class APITest(QuietBase):
    def call(self, method, user, path, data=None):
        _token, secret = APIToken.create_for(user=user, title="T", access="write")
        return getattr(self.client, method)(
            f"/api/v1/{path}",
            json.dumps(data) if data is not None else None,
            content_type="application/json",
            headers={"authorization": f"Bearer {secret}"},
        )

    def test_quiet_hours(self):
        for user in [self.ada, self.cleo]:
            with self.subTest(user=user):
                response = self.call(
                    "put",
                    user,
                    "me/notifications/",
                    {
                        "quiet_hours": True,
                        "working_days": [5, 6],
                        "working_from": "10:00",
                    },
                )
                data = response.json()
                self.assertEqual(
                    (
                        data["quiet_hours"],
                        data["working_days"],
                        data["working_from"],
                        data["working_until"],
                    ),
                    (True, [5, 6], "10:00:00", "18:00:00"),
                )
                response = self.call(
                    "put", user, "me/notifications/", {"working_until": "09:00"}
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(
                    response.json(),
                    {"detail": "The working hours end after they start."},
                )
                response = self.call(
                    "put", user, "me/notifications/", {"working_days": []}
                )
                self.assertEqual(response.status_code, 400)

    def test_away(self):
        for user in [self.ada, self.cleo]:
            with self.subTest(user=user):
                response = self.call(
                    "put", user, "me/away/", {"until": "2026-12-01", "note": "Off"}
                )
                self.assertEqual(response.status_code, 200)
                data = self.call("get", user, "me/").json()
                self.assertEqual(
                    (data["away_until"], data["away_note"]), ("2026-12-01", "Off")
                )
                data = self.call("delete", user, "me/away/").json()
                self.assertEqual((data["away_until"], data["away_note"]), (None, ""))
                response = self.call("put", user, "me/away/", {"until": "2026-11-01"})
                self.assertEqual(response.status_code, 400)
                response = self.call(
                    "put", user, "me/away/", {"until": "2026-12-01", "note": "x" * 201}
                )
                self.assertEqual(response.status_code, 422)

    def test_people_show_it(self):
        data = self.call("get", self.cleo, f"todos/{self.todo.pk}/").json()
        (bob,) = data["assignees"]
        self.assertEqual((bob["away_until"], bob["away_note"]), ("2026-12-03", NOTE))
        data = self.call(
            "get", self.ada, f"items/{self.todo.pk}/mentionable/?q=bob"
        ).json()
        self.assertEqual(data[0]["away_until"], "2026-12-03")

    def test_admins_for_others(self):
        path = f"people/{self.ada.pk}/away/"
        response = self.call("put", self.admin, path, {"until": "2026-11-24"})
        self.assertEqual(response.json()["away_until"], "2026-11-24")
        response = self.call("delete", self.admin, path)
        self.assertIsNone(response.json()["away_until"])
        self.assertEqual(
            self.call("put", self.bob, path, {"until": "2026-11-24"}).status_code,
            403,
        )
        self.assertEqual(
            self.call("put", self.cleo, path, {"until": "2026-11-24"}).status_code,
            403,
        )
        self.assertEqual(
            self.call(
                "put", self.eve, f"people/{self.bob.pk}/away/", {"until": "2026-11-24"}
            ).status_code,
            404,
        )
        self.assertFalse(User.objects.get(pk=self.ada.pk).is_away)
