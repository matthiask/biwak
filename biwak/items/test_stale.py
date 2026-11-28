"""Stale to-dos: warned, then marked obsolete (specs/stale-todos.md)"""

import datetime as dt
import json
import zoneinfo

import time_machine
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from biwak.accounts.models import APIToken, MailDelivery
from biwak.activity.mails import send_mails
from biwak.activity.models import Action, Event, Notification
from biwak.activity.operations import subscribe
from biwak.items import operations as ops, stale
from biwak.items.models import Item, StaleWarning, Todo
from biwak.palette.test_actions import palette_data
from biwak.projects import operations as project_ops
from biwak.reactions.operations import add_reaction
from biwak.test_utils import external, person, project


ZURICH = zoneinfo.ZoneInfo("Europe/Zurich")
# A Monday, the day of the run
NOW = dt.datetime(2026, 12, 7, 3, 0, tzinfo=ZURICH)


def days_ago(days, hour=10):
    return (NOW - dt.timedelta(days=days)).replace(hour=hour)


@override_settings(
    STALE_TODOS=True,
    BASE_URL="https://biwak.example.org",
    DEFAULT_FROM_EMAIL="biwak@example.org",
)
class StaleBase(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.pia = external("Pia")
        self.project = project(members=[self.ada, self.bob, self.cleo, self.pia])
        with time_machine.travel(days_ago(400), tick=False):
            self.list = ops.create_list(
                project=self.project, title="Shared", creator=self.ada, visible=True
            )

    def make(self, title="Old", *, age=100, todolist=None, **fields):
        """A to-do created ``age`` days ago, by Ada"""
        with time_machine.travel(days_ago(age), tick=False):
            return ops.create_todo(
                todolist=todolist or self.list, title=title, creator=self.ada, **fields
            )

    def stale(self, now=NOW):
        return set(stale.stale_todos(now).values_list("title", flat=True))

    def at(self, when, run):
        with time_machine.travel(when, tick=False):
            return run()

    def todo(self, item):
        return Todo.objects.get(item=item)


class BeingStaleTest(StaleBase):
    def test_no_activity(self):
        self.make("Old", age=91)
        self.make("Recent", age=89)
        self.assertEqual(self.stale(), {"Old"})

    def test_overdue_counts_from_the_due_date(self):
        self.make("Long overdue", age=200, due_on=days_ago(95).date())
        self.make("Overdue", age=200, due_on=days_ago(30).date())
        self.assertEqual(self.stale(), {"Long overdue"})

    def test_starting_later(self):
        self.make(
            "Later",
            age=200,
            starts_on=(NOW + dt.timedelta(days=30)).date(),
            due_on=(NOW + dt.timedelta(days=40)).date(),
        )
        self.assertEqual(self.stale(), set())

    def test_reactions_dont_count(self):
        item = self.make("Old", age=100)
        self.at(days_ago(5), lambda: add_reaction(self.bob, "👍", item=item))
        self.assertEqual(self.stale(), {"Old"})

    def test_activity_counts(self):
        edited = self.make("Edited", age=100)
        commented = self.make("Commented", age=100)
        moved = self.make("Moved", age=100)
        other = ops.create_list(project=self.project, title="Other", creator=self.ada)
        self.at(
            days_ago(5),
            lambda: ops.update_todo(edited, actor=self.bob, title="Edited"),
        )
        self.at(days_ago(5), lambda: ops.update_todo(edited, actor=self.bob, notes="x"))
        self.at(
            days_ago(5),
            lambda: ops.add_comment(commented, author=self.cleo, content="Still?"),
        )
        self.at(
            days_ago(5),
            lambda: ops.move_todo(moved, todolist=other, actor=self.bob),
        )
        self.assertEqual(self.stale(), set())

    def test_added_from_text(self):
        self.at(
            days_ago(100),
            lambda: ops.add_from_text(self.list, "- From a text", actor=self.ada),
        )
        self.assertEqual(self.stale(), {"From a text"})

    def test_a_group_kept_for_a_year(self):
        backlog = ops.create_group(
            todolist=self.list.todolist, title="Backlog", stale_after=365
        )
        self.make("Idea", age=200, group=backlog)
        self.make("Old idea", age=400, group=backlog)
        self.assertEqual(self.stale(), {"Old idea"})

    def test_left_out(self):
        archived = ops.create_list(
            project=self.project, title="Archived", creator=self.ada
        )
        self.make("In an archived list", todolist=archived)
        ops.archive(archived, actor=self.ada)
        trashed = self.make("Trashed")
        ops.trash(trashed, actor=self.ada)
        done = self.make("Done")
        ops.complete(done, actor=self.ada)
        old_project = project("Old project", members=[self.ada])
        old_list = ops.create_list(project=old_project, title="L", creator=self.ada)
        self.make("In an archived project", todolist=old_list)
        project_ops.archive_project(old_project, actor=self.ada)
        template = project_ops.create_template(name="Template", actor=self.ada)
        template_list = ops.create_list(project=template, title="T", creator=self.ada)
        self.make("In a template", todolist=template_list)
        # The run happens now; these were changed today, so move "now"
        later = timezone.now() + dt.timedelta(days=200)
        self.assertEqual(self.stale(later), set())


class DailyRunTest(StaleBase):
    def setUp(self):
        super().setUp()
        self.item = self.make("Old", age=100)
        subscribe(self.bob, self.item)
        subscribe(self.cleo, self.item)
        subscribe(self.pia, self.item)

    def run_at(self, when):
        with self.captureOnCommitCallbacks(execute=True):
            return self.at(when, lambda: stale.run(when))

    def test_warning_once(self):
        self.assertEqual(self.run_at(NOW), (0, 0, 1))
        self.assertEqual(self.todo(self.item).stale_warned_at, NOW)
        # Staff and externals following it, never clients
        self.assertEqual(
            set(StaleWarning.objects.values_list("user", flat=True)),
            {self.ada.pk, self.bob.pk, self.pia.pk},
        )
        self.assertEqual(self.run_at(NOW + dt.timedelta(days=1)), (0, 0, 0))
        self.assertEqual(StaleWarning.objects.count(), 3)

    def test_at_most_20_per_project_the_oldest_first(self):
        for n in range(25):
            self.make(f"Todo {n:02}", age=200 - n)
        self.run_at(NOW)
        warned = Item.objects.filter(todo__stale_warned_at__isnull=False)
        self.assertEqual(warned.count(), 20)
        titles = set(warned.values_list("title", flat=True))
        self.assertIn("Todo 00", titles)
        self.assertNotIn("Old", titles)
        self.assertNotIn("Todo 24", titles)
        # The next day the rest
        self.run_at(NOW + dt.timedelta(days=1))
        self.assertEqual(warned.count(), 26)

    def test_activity_after_the_warning_clears_it(self):
        self.run_at(NOW)
        self.at(
            NOW + dt.timedelta(days=3),
            lambda: ops.add_comment(self.item, author=self.cleo, content="Wait!"),
        )
        self.assertEqual(self.run_at(NOW + dt.timedelta(days=4)), (1, 0, 0))
        self.assertIsNone(self.todo(self.item).stale_warned_at)
        self.run_at(NOW + dt.timedelta(days=20))
        self.assertFalse(self.todo(self.item).obsolete)

    def test_marked_obsolete_after_14_days(self):
        self.run_at(NOW)
        self.assertEqual(self.run_at(NOW + dt.timedelta(days=13)), (0, 0, 0))
        self.assertFalse(self.todo(self.item).obsolete)
        self.assertEqual(self.run_at(NOW + dt.timedelta(days=14)), (0, 1, 0))
        todo = self.todo(self.item)
        self.assertTrue(todo.obsolete)
        self.assertIsNone(todo.completed_by)
        self.assertIsNone(todo.stale_warned_at)
        event = Event.objects.filter(item=self.item).first()
        self.assertEqual(event.action, Action.MARKED_OBSOLETE)
        self.assertIsNone(event.actor)
        self.assertFalse(event.is_client_visible)
        # Staff following it are told, clients aren't
        told = set(
            Notification.objects.filter(event=event).values_list("user", flat=True)
        )
        self.assertEqual(told, {self.ada.pk, self.bob.pk, self.pia.pk})

    def test_marked_on_the_promised_day(self):
        # A run a few seconds earlier than the warning's, two weeks later
        self.run_at(NOW + dt.timedelta(seconds=30))
        todo = self.todo(self.item)
        self.assertEqual(stale.obsolete_on(todo), dt.date(2026, 12, 21))
        late = dt.datetime(2026, 12, 20, 23, 59, tzinfo=ZURICH)
        self.assertEqual(self.run_at(late), (0, 0, 0))
        run = NOW + dt.timedelta(days=14, seconds=5)
        self.assertEqual(self.run_at(run), (0, 1, 0))

    def test_marked_on_the_promised_day_across_the_dst_change(self):
        self.run_at(dt.datetime(2027, 3, 20, 3, 0, tzinfo=ZURICH))
        todo = self.todo(self.item)
        self.assertEqual(stale.obsolete_on(todo), dt.date(2027, 4, 3))
        # In UTC, as ``timezone.now()`` is: 13 days and 23 hours later
        run = dt.datetime(2027, 4, 3, 3, 0, tzinfo=ZURICH).astimezone(dt.UTC)
        self.assertEqual(self.run_at(run), (0, 1, 0))

    def test_without_staff_subscribers(self):
        item = self.make("Nobody's", age=100)
        item.subscriptions.all().delete()
        self.run_at(NOW)
        self.assertFalse(StaleWarning.objects.filter(item=item).exists())
        self.run_at(NOW + dt.timedelta(days=14))
        self.assertTrue(self.todo(item).obsolete)

    def test_off(self):
        with self.settings(STALE_TODOS=False):
            self.assertEqual(self.run_at(NOW + dt.timedelta(days=30)), (0, 0, 0))
        self.assertIsNone(self.todo(self.item).stale_warned_at)

    def test_report_changes_nothing(self):
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        with time_machine.travel(NOW, tick=False):
            call_command("stale_todos", stdout=out)
        self.assertIn("Website (#", out.getvalue())
        self.assertIn("1 stale, 0 warned, 1 to warn", out.getvalue())
        self.assertIsNone(self.todo(self.item).stale_warned_at)

    def test_report_lists_the_todos(self):
        """Each stale to-do with why and what happens to it (warned, warned
        at the next run, or later: over the day's limit)"""
        from io import StringIO

        from django.core.management import call_command

        backlog = ops.create_group(todolist=self.list.todolist, title="Backlog")
        overdue = self.make(
            "Book the bus", age=200, due_on=days_ago(120).date(), group=backlog
        )
        self.run_at(NOW)
        for n in range(21):
            self.make(f"Later {n:02}", age=100)
        self.make("Recent", age=10)

        def report(*args):
            out = StringIO()
            with time_machine.travel(NOW + dt.timedelta(days=1), tick=False):
                call_command("stale_todos", *args, stdout=out)
            return out.getvalue()

        output = report()
        self.assertIn("23 stale, 2 warned, 20 to warn", output)
        self.assertIn(
            f"#{overdue.pk} Book the bus (Shared / Backlog): Due 9 August 2026;"
            " warned, marked obsolete on 21 December 2026",
            output,
        )
        self.assertIn(
            f"#{self.item.pk} Old (Shared): Nothing since 29 August 2026; warned,",
            output,
        )
        self.assertIn("Later 00 (Shared): Nothing since", output)
        self.assertIn("; to warn", output)
        self.assertEqual(output.count("; later (over 20 a day)"), 1)
        self.assertNotIn("Recent", output)
        # Only the counts
        output = report("--summary")
        self.assertIn("23 stale, 2 warned, 20 to warn", output)
        self.assertNotIn("Book the bus", output)
        # One project
        other = project("Other", members=[self.ada])
        self.assertNotIn("Website", report("--project", other.pk))
        self.assertIn("Book the bus", report("--project", self.project.pk))


class WarningMailTest(StaleBase):
    def setUp(self):
        super().setUp()
        self.first = self.make("Order the tent", age=100)
        self.second = self.make("Book the bus", age=200, due_on=days_ago(120).date())
        for item in [self.first, self.second]:
            subscribe(self.bob, item)
            subscribe(self.cleo, item)
        self.at(NOW, lambda: stale.run(NOW))
        mail.outbox = []

    def send(self, when):
        with (
            self.captureOnCommitCallbacks(execute=True),
            time_machine.travel(when, tick=False),
        ):
            return send_mails(now=when)

    def mails_to(self, user):
        return [m for m in mail.outbox if m.to == [user.email]]

    def test_one_mail_per_person(self):
        # Not before 07:00
        self.send(NOW.replace(hour=6))
        self.assertEqual(self.mails_to(self.bob), [])
        self.send(NOW.replace(hour=7))
        [message] = self.mails_to(self.bob)
        self.assertEqual(message.subject, "[Biwak] 2 to-dos will be marked as obsolete")
        self.assertIn(
            "2 to-dos will be marked as obsolete on 21 December 2026", message.body
        )
        self.assertIn("Website / Shared", message.body)
        self.assertIn("Order the tent (Nothing since 29 August 2026)", message.body)
        self.assertIn("Book the bus (Due 9 August 2026)", message.body)
        self.assertIn("https://biwak.example.org/keep/", message.body)
        self.assertIn("Comment on one or change it to keep it too.", message.body)
        self.assertIn("List-Unsubscribe", message.extra_headers)
        self.assertEqual(self.mails_to(self.cleo), [])
        self.assertEqual(len(self.mails_to(self.ada)), 1)
        # Once
        self.send(NOW.replace(hour=8))
        self.assertEqual(len(self.mails_to(self.bob)), 1)

    def test_who_gets_none(self):
        self.bob.mail_delivery = MailDelivery.NONE
        self.bob.save()
        self.ada.mail_undeliverable_at = timezone.now()
        self.ada.save()
        self.send(NOW.replace(hour=8))
        self.assertEqual(mail.outbox, [])
        # Dropped, not waiting
        self.assertFalse(StaleWarning.objects.filter(sent_at__isnull=True).exists())

    def test_away(self):
        self.bob.away_until = NOW.date() + dt.timedelta(days=3)
        self.bob.save()
        self.send(NOW.replace(hour=8))
        self.assertEqual(self.mails_to(self.bob), [])
        self.assertEqual(len(self.mails_to(self.ada)), 1)

    def test_inactive(self):
        self.bob.is_active = False
        self.bob.save()
        self.send(NOW.replace(hour=8))
        self.assertEqual(self.mails_to(self.bob), [])

    def test_quiet_hours(self):
        self.bob.quiet_hours = True
        self.bob.working_from = dt.time(9)
        self.bob.save()
        self.send(NOW.replace(hour=8))
        self.assertEqual(self.mails_to(self.bob), [])
        self.send(NOW.replace(hour=9))
        self.assertEqual(len(self.mails_to(self.bob)), 1)

    def test_kept_meanwhile(self):
        stale.keep(self.first, actor=self.ada)
        self.send(NOW.replace(hour=8))
        [message] = self.mails_to(self.bob)
        self.assertEqual(message.subject, "[Biwak] 1 to-do will be marked as obsolete")
        self.assertNotIn("Order the tent", message.body)

    def test_german(self):
        self.bob.language = "de"
        self.bob.save()
        self.send(NOW.replace(hour=8))
        [message] = self.mails_to(self.bob)
        self.assertEqual(
            message.subject, "[Biwak] 2 To-dos werden als hinfällig markiert"
        )
        self.assertIn("Kommentiere eines oder ändere es", message.body)

    def test_keep_link(self):
        url = stale.keep_url(self.bob, self.first).removeprefix(
            "https://biwak.example.org"
        )
        response = self.client.get(url)
        self.assertContains(response, "Keep open?")
        self.assertIsNotNone(self.todo(self.first).stale_warned_at)
        response = self.client.post(url)
        self.assertContains(response, "Kept open")
        self.assertIsNone(self.todo(self.first).stale_warned_at)
        event = Event.objects.filter(item=self.first).first()
        self.assertEqual((event.action, event.actor), (Action.KEPT, self.bob))
        self.assertFalse(event.is_client_visible)
        # Telling nobody
        self.assertFalse(Notification.objects.filter(event=event).exists())

    def test_bad_and_foreign_tokens(self):
        self.assertEqual(self.client.get("/keep/nonsense/").status_code, 404)
        internal = ops.create_list(
            project=self.project, title="Internal", creator=self.ada
        )
        secret = self.make("Secret", todolist=internal)
        url = stale.keep_url(self.cleo, secret).removeprefix(
            "https://biwak.example.org"
        )
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url).status_code, 404)


class KeepingTest(StaleBase):
    def setUp(self):
        super().setUp()
        self.item = self.make("Old", age=100)
        self.at(NOW, lambda: stale.run(NOW))

    def test_banner_and_palette(self):
        with time_machine.travel(NOW + dt.timedelta(days=1), tick=False):
            self.client.force_login(self.ada)
            response = self.client.get(self.item.get_absolute_url())
            self.assertContains(response, "Nothing happened since 29 August 2026.")
            self.assertContains(
                response, "It will be marked as obsolete on 21 December 2026."
            )
            actions = {a["label"]: a for a in palette_data(response)["actions"]}
            self.assertEqual(
                actions["Keep open"]["url"], f"/todos/{self.item.pk}/keep/"
            )
            # Not for clients
            self.client.force_login(self.cleo)
            response = self.client.get(self.item.get_absolute_url())
            self.assertNotContains(response, "It will be marked as obsolete")
            self.assertNotIn(
                "Keep open",
                {a["label"] for a in palette_data(response)["actions"]},
            )
            # Keeping from the page
            self.client.force_login(self.ada)
            self.client.post(f"/todos/{self.item.pk}/keep/")
            self.assertIsNone(self.todo(self.item).stale_warned_at)
            response = self.client.get(self.item.get_absolute_url())
            self.assertNotContains(response, "It will be marked as obsolete")
            self.assertContains(response, "kept this open")
        # Kept restarts the clock
        self.assertEqual(self.stale(NOW + dt.timedelta(days=80)), set())

    def call(self, user, path):
        _token, secret = APIToken.create_for(user=user, title="T", access="write")
        return self.client.post(
            f"/api/v1/{path}", headers={"authorization": f"Bearer {secret}"}
        )

    def test_api(self):
        response = self.client.get(
            f"/api/v1/todos/{self.item.pk}/",
            headers={
                "authorization": "Bearer "
                + APIToken.create_for(user=self.ada, title="T", access="read")[1]
            },
        )
        self.assertIsNotNone(response.json()["stale_warned_at"])
        response = self.call(self.ada, f"todos/{self.item.pk}/keep/")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["stale_warned_at"])
        internal = ops.create_list(
            project=self.project, title="Internal", creator=self.ada
        )
        secret = self.make("Secret", todolist=internal)
        response = self.call(self.cleo, f"todos/{secret.pk}/keep/")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(json.loads(response.content).get("stale_warned_at"), None)
