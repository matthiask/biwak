"""The weekly mail of one's open to-dos (specs/notifications.md, "The weekly
to-dos", decided 2026-11-23): opted in, on Monday morning, once a week,
by due date with what's waiting on others; with frozen time in Zurich"""

import datetime as dt

from django.core import mail
from django.utils import timezone

from biwak.accounts.models import APIToken, MailDelivery
from biwak.activity.models import Notification
from biwak.activity.test_digest import DigestBase
from biwak.activity.test_quiet_hours import MONDAY
from biwak.audit.models import LoggedAction
from biwak.items import operations as ops
from biwak.items.models import Assignment
from biwak.outbox.models import Kind as MailKind, OutgoingMail
from biwak.test_utils import person


SUBJECT = "[Biwak] Your open to-dos, week of 23 November 2026"


class WeeklyBase(DigestBase):
    """Bob wants the weekly mail and a mail per change, without quiet hours;
    it's Monday 23 November 2026"""

    def setUp(self):
        super().setUp()
        self.bob.mail_delivery = MailDelivery.EACH
        self.bob.weekly_todos = True
        self.bob.save()

    def weekly(self, when, user=None):
        """The mails to ``user`` (Bob) sent at ``when``, without the
        notifications of making the to-dos: the weekly ones"""
        Notification.objects.all().delete()
        self.send(when)
        email = (user or self.bob).email
        messages = [m for m in mail.outbox if m.to == [email]]
        mail.outbox.clear()
        return messages


class WeeklyMailTest(WeeklyBase):
    def test_sections(self):
        late = self.make("Late", to=[self.bob], due_on=dt.date(2026, 11, 20))
        self.make("Due today", to=[self.bob], due_on=dt.date(2026, 11, 23))
        self.make(
            "Later this week",
            to=[self.bob],
            starts_on=dt.date(2026, 11, 25),
            due_on=dt.date(2026, 11, 27),
        )
        self.make(
            "Next Tuesday",
            todolist=self.internal,
            to=[self.bob],
            due_on=dt.date(2026, 12, 1),
        )
        self.make("In January", to=[self.bob], due_on=dt.date(2027, 1, 15))
        self.make("Some day", to=[self.bob])
        self.make("Another day", to=[self.bob])
        self.make("Not mine", to=[self.ada], due_on=dt.date(2026, 11, 20))
        done = self.make("Done", to=[self.bob], due_on=dt.date(2026, 11, 20))
        self.act(lambda: ops.complete(done, actor=self.bob))
        self.make("Asked", by=self.bob, to=[self.ada], due_on=dt.date(2026, 11, 19))
        self.make("Not late", by=self.bob, to=[self.ada], due_on=dt.date(2026, 11, 30))

        (message,) = self.weekly(f"{MONDAY} 07:00")
        self.assertEqual(message.subject, SUBJECT)
        body = message.body
        self.assertIn(
            "# Your open to-dos, week of 23 November 2026\n\n"
            "## Overdue\n\n"
            "- Late (Website / Shared) [Visible to clients]\n"
            "  Overdue · 20 Nov\n"
            f"  https://biwak.example.org{late.get_absolute_url()}\n\n"
            "## This week\n\n"
            "- Due today (Website / Shared) [Visible to clients]\n"
            "  Today\n",
            body,
        )
        self.assertIn(
            "- Later this week (Website / Shared) [Visible to clients]\n  25–27 Nov\n",
            body,
        )
        self.assertIn(
            "## Next week\n\n- Next Tuesday (Website / Internal)\n  1 Dec\n", body
        )
        self.assertIn("## Later\n\n- In January (Website / Shared)", body)
        self.assertIn(
            "And 2 to-dos without a date:"
            " https://biwak.example.org/todos/?grouping=due#due-none\n",
            body,
        )
        self.assertIn(
            "## Waiting on others\n\n"
            "- Asked (Website / Shared) [Visible to clients]\n"
            "  Overdue · 19 Nov · Ada Example\n",
            body,
        )
        # In this order
        positions = [
            body.index(text)
            for text in [
                "## Overdue",
                "## This week",
                "## Next week",
                "## Later",
                "And 2 to-dos",
                "## Waiting on others",
            ]
        ]
        self.assertEqual(positions, sorted(positions))
        for title in ["Some day", "Not mine", "Done", "Not late"]:
            self.assertNotIn(title, body)
        html = message.alternatives[0][0]
        self.assertIn(
            f'href="https://biwak.example.org{late.get_absolute_url()}"', html
        )
        self.assertIn(
            '<a href="https://biwak.example.org/todos/?grouping=due#due-none">'
            "And 2 to-dos without a date</a>",
            html,
        )
        self.assertIn("/ Internal", html)
        # Through the outbox, as a kind of its own
        self.assertTrue(OutgoingMail.objects.filter(kind=MailKind.WEEKLY).exists())

    def test_only_undated(self):
        self.make("Some day", to=[self.bob])
        (message,) = self.weekly(f"{MONDAY} 07:00")
        self.assertIn("1 to-do without a date:", message.body)
        self.assertNotIn("And 1", message.body)
        self.assertNotIn("## ", message.body)

    def test_only_waiting(self):
        self.make("Asked", by=self.bob, to=[self.ada], due_on=dt.date(2026, 11, 19))
        (message,) = self.weekly(f"{MONDAY} 07:00")
        self.assertIn("## Waiting on others", message.body)
        self.assertNotIn("without a date", message.body)

    def test_nothing_to_say(self):
        """No open to-dos and nothing waiting: no mail"""
        self.make("Not late", by=self.bob, to=[self.ada], due_on=dt.date(2026, 11, 30))
        self.assertEqual(self.weekly(f"{MONDAY} 07:00"), [])

    def test_german(self):
        self.bob.language = "de"
        self.bob.save()
        self.make("Late", to=[self.bob], due_on=dt.date(2026, 11, 20))
        self.make("Soon", to=[self.bob], due_on=dt.date(2026, 12, 1))
        self.make("Some day", to=[self.bob])
        self.make("Asked", by=self.bob, to=[self.ada], due_on=dt.date(2026, 11, 19))
        (message,) = self.weekly(f"{MONDAY} 07:00")
        self.assertEqual(
            message.subject,
            "[Biwak] Deine offenen To-dos, Woche vom 23. November 2026",
        )
        self.assertIn("## Überfällig", message.body)
        self.assertIn("Überfällig · 20. Nov.", message.body)
        self.assertIn("## Nächste Woche", message.body)
        self.assertIn("Und 1 To-do ohne Datum:", message.body)
        self.assertIn("## Warten auf andere", message.body)
        self.assertIn("Deine Benachrichtigungseinstellungen", message.body)


class WhenTest(WeeklyBase):
    def setUp(self):
        super().setUp()
        self.make("Late", to=[self.bob], due_on=dt.date(2026, 11, 20))

    def test_monday_at_seven_once_a_week(self):
        self.assertEqual(self.weekly(f"{MONDAY} 06:59"), [])
        self.assertEqual(len(self.weekly(f"{MONDAY} 07:00")), 1)
        self.bob.refresh_from_db()
        self.assertEqual(self.bob.weekly_todos_on, dt.date(2026, 11, 23))
        for when in [f"{MONDAY} 07:01", f"{MONDAY} 15:00", "2026-11-24 07:00"]:
            self.assertEqual(self.weekly(when), [], when)
        (message,) = self.weekly("2026-11-30 07:00")
        self.assertEqual(
            message.subject, "[Biwak] Your open to-dos, week of 30 November 2026"
        )

    def test_the_week_mailed_is_not_in_the_audit_log(self):
        """Like ``last_login``; the setting is"""
        LoggedAction.objects.all().delete()
        self.weekly(f"{MONDAY} 07:00")
        users = LoggedAction.objects.filter(table_name="accounts_user")
        self.assertFalse(users.exists())
        self.bob.weekly_todos = False
        self.bob.save()
        (change,) = users
        self.assertEqual(change.changed_fields, {"weekly_todos": "f"})

    def test_opting_in_during_the_week(self):
        """The first mail on the next Monday, not at once"""
        self.bob.weekly_todos = False
        self.bob.save()
        self.assertEqual(self.weekly(f"{MONDAY} 07:00"), [])
        self.bob.weekly_todos = True
        self.bob.save()
        self.assertEqual(self.weekly("2026-11-25 10:00"), [])
        self.assertEqual(len(self.weekly("2026-11-30 07:00")), 1)

    def test_quiet_hours_at_the_start_of_the_working_time(self):
        self.bob.quiet_hours = True
        self.bob.save()
        self.assertEqual(self.weekly(f"{MONDAY} 07:00"), [])
        self.assertEqual(self.weekly(f"{MONDAY} 07:59"), [])
        self.assertEqual(len(self.weekly(f"{MONDAY} 08:00")), 1)

    def test_quiet_hours_on_the_first_working_day(self):
        """Not working on Mondays: on their first working day of the week,
        the week still Monday's"""
        self.bob.quiet_hours = True
        self.bob.working_days = [1, 2, 3]
        self.bob.working_from = dt.time(9)
        self.bob.save()
        self.assertEqual(self.weekly(f"{MONDAY} 09:00"), [])
        self.assertEqual(self.weekly("2026-11-24 08:59"), [])
        (message,) = self.weekly("2026-11-24 09:00")
        self.assertEqual(message.subject, SUBJECT)
        self.assertEqual(self.weekly("2026-11-25 09:00"), [])

    def test_away_skips_the_week(self):
        """Away on Monday morning: no mail that week, none later that week"""
        self.bob.away_until = dt.date(2026, 11, 23)
        self.bob.save()
        for when in [f"{MONDAY} 07:00", "2026-11-24 07:00", "2026-11-27 07:00"]:
            self.assertEqual(self.weekly(when), [], when)
        self.assertEqual(len(self.weekly("2026-11-30 07:00")), 1)

    def test_who_gets_none(self):
        """Not with no mails, inactive or with an address which bounced"""
        people = [
            person("Dan", weekly_todos=True, mail_delivery=MailDelivery.NONE),
            # Deactivated once assigned below
            person("Eve", weekly_todos=True),
            person("Finn", weekly_todos=True, mail_undeliverable_at=timezone.now()),
            person("Gus"),
        ]
        for someone in people:
            self.make(f"For {someone}", to=[someone], due_on=dt.date(2026, 11, 20))
        people[1].is_active = False
        people[1].save()
        Notification.objects.all().delete()
        self.send(f"{MONDAY} 07:00")
        self.assertEqual(
            {to for m in mail.outbox for to in m.to if m.subject == SUBJECT},
            {self.bob.email},
        )

    def test_with_the_digest(self):
        """Independent of the delivery: on Mondays digest people get both"""
        self.bob.mail_delivery = MailDelivery.DIGEST
        self.bob.save()
        Notification.objects.all().delete()
        self.news()
        self.send(f"{MONDAY} 07:00")
        subjects = sorted(m.subject for m in self.to_bob())
        self.assertEqual(
            subjects, ["[Biwak] What happened on 22 November 2026", SUBJECT]
        )


class ClientTest(WeeklyBase):
    def test_only_what_clients_see(self):
        self.cleo.weekly_todos = True
        self.cleo.save()
        dan = person("Dan")
        self.make("For Cleo", to=[self.cleo], due_on=dt.date(2026, 11, 20))
        secret = self.make(
            "Secret", todolist=self.internal, due_on=dt.date(2026, 11, 24)
        )
        # Assigned while it was visible, and since then hidden
        Assignment.objects.create(todo=secret.todo, user=self.cleo)
        asked = self.make(
            "Asked", by=self.cleo, to=[self.bob], due_on=dt.date(2026, 11, 20)
        )
        # Somebody Cleo doesn't know
        Assignment.objects.create(todo=asked.todo, user=dan, assigned_by=self.cleo)
        hidden = self.make(
            "Hidden", todolist=self.internal, due_on=dt.date(2026, 11, 20)
        )
        Assignment.objects.create(
            todo=hidden.todo, user=self.bob, assigned_by=self.cleo
        )
        (message,) = self.weekly(f"{MONDAY} 07:00", self.cleo)
        self.assertIn("- For Cleo (Website / Shared)", message.body)
        self.assertIn(
            "- Asked (Website / Shared) [Visible to clients]\n"
            "  Overdue · 20 Nov · Bob Example\n",
            message.body,
        )
        for text in ["Secret", "Hidden", "Internal", "Dan"]:
            self.assertNotIn(text, message.body)
            self.assertNotIn(text, message.alternatives[0][0])


class SettingTest(WeeklyBase):
    def test_off_by_default(self):
        self.assertFalse(person("Dan").weekly_todos)

    def test_page(self):
        for user in [self.ada, self.cleo]:
            with self.subTest(user=user):
                self.client.force_login(user)
                response = self.client.get("/accounts/settings/")
                self.assertContains(response, "A weekly mail with my open to-dos")
                data = {"notification_level": "concerns_me", "mail_delivery": "each"}
                self.client.post(
                    "/accounts/settings/notifications/", data | {"weekly_todos": "on"}
                )
                user.refresh_from_db()
                self.assertTrue(user.weekly_todos)
                self.client.post("/accounts/settings/notifications/", data)
                user.refresh_from_db()
                self.assertFalse(user.weekly_todos)

    def test_api(self):
        for user in [self.ada, self.cleo]:
            with self.subTest(user=user):
                _token, secret = APIToken.create_for(
                    user=user, title="T", access="write"
                )
                headers = {"authorization": f"Bearer {secret}"}
                response = self.client.get("/api/v1/me/notifications/", headers=headers)
                self.assertFalse(response.json()["weekly_todos"])
                response = self.client.put(
                    "/api/v1/me/notifications/",
                    {"weekly_todos": True},
                    content_type="application/json",
                    headers=headers,
                )
                self.assertTrue(response.json()["weekly_todos"])
                user.refresh_from_db()
                self.assertTrue(user.weekly_todos)
