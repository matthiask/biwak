"""The daily digest (specs/notifications.md, "Digest", decided 2026-11-23):
the to-dos needing the person today and those they wait on at the top,
mentions and assignments in full, one line per item for the rest, and a
digest on working days without notifications"""

import datetime as dt

import time_machine
from django.core import mail

from biwak.accounts.models import MailDelivery
from biwak.activity.models import Notification
from biwak.activity.test_quiet_hours import MONDAY, QuietBase, at
from biwak.items import operations as ops
from biwak.items.models import Assignment, Item
from biwak.test_utils import person


SATURDAY = "2026-11-28"


class DigestBase(QuietBase):
    """Bob gets a daily digest, without quiet hours; it's Monday 23
    November 2026"""

    def setUp(self):
        super().setUp()
        self.bob.quiet_hours = False
        self.bob.mail_delivery = MailDelivery.DIGEST
        self.bob.save()

    def make(self, title, *, todolist=None, by=None, to=(), when=None, **fields):
        """A to-do, made on Monday early in the morning unless ``when``"""
        with time_machine.travel(at(when or f"{MONDAY} 06:00"), tick=False):
            self.act(
                lambda: ops.create_todo(
                    todolist=todolist or self.shared,
                    title=title,
                    creator=by or self.ada,
                    assignees=to,
                    **fields,
                )
            )
        return Item.objects.get(title=title)

    def quiet_day(self):
        """No notifications: the digest is about the to-dos only"""
        Notification.objects.all().delete()


class TodoSectionsTest(DigestBase):
    def test_what_needs_you_today(self):
        self.make("Overdue", to=[self.bob], due_on=dt.date(2026, 11, 20))
        self.make("Due today", to=[self.bob], due_on=dt.date(2026, 11, 23))
        self.make(
            "Starts today",
            to=[self.bob],
            starts_on=dt.date(2026, 11, 23),
            due_on=dt.date(2026, 11, 27),
        )
        self.make("Due later", to=[self.bob], due_on=dt.date(2026, 11, 24))
        self.make(
            "Starts later",
            to=[self.bob],
            starts_on=dt.date(2026, 11, 24),
            due_on=dt.date(2026, 11, 27),
        )
        self.make("Not mine", to=[self.ada], due_on=dt.date(2026, 11, 20))
        done = self.make("Done", to=[self.bob], due_on=dt.date(2026, 11, 20))
        self.act(lambda: ops.complete(done, actor=self.bob))
        self.quiet_day()
        self.send(f"{MONDAY} 07:00")
        (message,) = self.to_bob()
        self.assertEqual(message.subject, "[Biwak] Your to-dos on 23 November 2026")
        overdue = Item.objects.get(title="Overdue")
        self.assertIn(
            "# Needs you today\n\n"
            "- Overdue (Website) [Visible to clients]\n"
            "  Overdue · 20 Nov\n"
            f"  https://biwak.example.org{overdue.get_absolute_url()}\n\n"
            "- Due today (Website) [Visible to clients]\n"
            "  Today\n",
            message.body,
        )
        self.assertIn("- Starts today (Website)", message.body)
        self.assertIn("  Starts today · 23–27 Nov\n", message.body)
        for title in ["Due later", "Starts later", "Not mine", "Done"]:
            self.assertNotIn(title, message.body)
        self.assertNotIn("Waiting on others", message.body)
        self.assertNotIn("What happened", message.body)
        html = message.alternatives[0][0]
        self.assertIn("Needs you today", html)
        self.assertIn(
            f'href="https://biwak.example.org{overdue.get_absolute_url()}"', html
        )

    def test_what_you_wait_on(self):
        self.ada.away_until = dt.date(2026, 12, 3)
        self.ada.save()
        dan = person("Dan")
        self.make("Late", by=self.bob, to=[self.ada, dan], due_on=dt.date(2026, 11, 20))
        self.make("Not yet", by=self.bob, to=[self.ada], due_on=dt.date(2026, 11, 23))
        self.make("Not by me", to=[self.cleo], due_on=dt.date(2026, 11, 20))
        # Also mine: needs me, not waiting on others (as on Home)
        self.make(
            "Together", by=self.bob, to=[self.bob, dan], due_on=dt.date(2026, 11, 20)
        )
        self.quiet_day()
        self.send(f"{MONDAY} 07:00")
        (message,) = self.to_bob()
        self.assertIn(
            "# Waiting on others\n\n"
            "- Late (Website) [Visible to clients]\n"
            "  Overdue · 20 Nov · Ada Example (away until 3 Dec), Dan Example\n",
            message.body,
        )
        waiting = message.body.split("# Waiting on others")[1]
        self.assertNotIn("Not yet", waiting)
        self.assertNotIn("Not by me", waiting)
        self.assertNotIn("Together", waiting)
        self.assertIn("Together", message.body.split("# Waiting on others")[0])
        self.assertIn("(away until 3 Dec)", message.alternatives[0][0])

    def test_client(self):
        """Clients see only to-dos visible to them, and only the names of
        people they may know"""
        self.cleo.mail_delivery = MailDelivery.DIGEST
        self.cleo.save()
        dan = person("Dan")
        self.make("For Cleo", to=[self.cleo], due_on=dt.date(2026, 11, 20))
        secret = self.make(
            "Secret", todolist=self.internal, due_on=dt.date(2026, 11, 20)
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
        self.quiet_day()
        self.send(f"{MONDAY} 07:00")
        (message,) = [m for m in mail.outbox if m.to == [self.cleo.email]]
        self.assertIn("- For Cleo (Website)", message.body)
        self.assertIn(
            "- Asked (Website) [Visible to clients]\n  Overdue · 20 Nov · Bob Example\n",
            message.body,
        )
        for text in ["Secret", "Hidden", "Dan"]:
            self.assertNotIn(text, message.body)
            self.assertNotIn(text, message.alternatives[0][0])

    def test_with_the_notifications(self):
        """On top of yesterday's notifications, which keep the subject"""
        self.make("Overdue", to=[self.bob], due_on=dt.date(2026, 11, 20))
        self.quiet_day()
        self.comment("2026-11-22 14:00")
        self.send(f"{MONDAY} 07:00")
        (message,) = self.to_bob()
        self.assertEqual(message.subject, "[Biwak] What happened on 22 November 2026")
        self.assertLess(
            message.body.index("# Needs you today"),
            message.body.index("# What happened on 22 November 2026"),
        )
        # One digest a day
        self.send(f"{MONDAY} 07:01")
        self.assertEqual(self.to_bob(), [])

    def test_german(self):
        self.bob.language = "de"
        self.bob.save()
        self.make(
            "Starts today",
            to=[self.bob],
            starts_on=dt.date(2026, 11, 23),
            due_on=dt.date(2026, 11, 27),
        )
        self.make("Late", by=self.bob, to=[self.ada], due_on=dt.date(2026, 11, 20))
        self.quiet_day()
        self.send(f"{MONDAY} 07:00")
        (message,) = self.to_bob()
        self.assertEqual(message.subject, "[Biwak] Deine To-dos am 23. November 2026")
        self.assertIn("# Braucht dich heute", message.body)
        self.assertIn("Beginnt heute · 23.–27. Nov.", message.body)
        self.assertIn("# Warten auf andere", message.body)
        self.assertIn("Überfällig · 20. Nov.", message.body)


class TodoDigestDaysTest(DigestBase):
    """A digest also on days without notifications: on working days, once,
    not while away, not without a digest"""

    def setUp(self):
        super().setUp()
        self.make("Overdue", to=[self.bob], due_on=dt.date(2026, 11, 20))
        self.quiet_day()

    def test_once_a_day_from_seven(self):
        self.send(f"{MONDAY} 06:59")
        self.assertEqual(self.to_bob(), [])
        self.send(f"{MONDAY} 07:00")
        self.assertEqual(len(self.to_bob()), 1)
        self.send(f"{MONDAY} 07:01")
        self.send(f"{MONDAY} 18:00")
        self.assertEqual(self.to_bob(), [])
        self.send("2026-11-24 07:00")
        self.assertEqual(len(self.to_bob()), 1)

    def test_monday_to_friday(self):
        self.send("2026-11-27 07:00")
        self.assertEqual(len(self.to_bob()), 1)
        self.send(SATURDAY + " 07:00")
        self.send("2026-11-29 07:00")
        self.assertEqual(self.to_bob(), [])

    def test_the_working_days_with_quiet_hours(self):
        """At the start of the working time on the working days"""
        self.bob.quiet_hours = True
        self.bob.working_days = [5]
        self.bob.working_from = dt.time(9, 30)
        self.bob.save()
        self.send(f"{MONDAY} 09:30")
        self.send(SATURDAY + " 07:00")
        self.send(SATURDAY + " 09:29")
        self.assertEqual(self.to_bob(), [])
        self.send(SATURDAY + " 09:30")
        self.assertEqual(len(self.to_bob()), 1)

    def test_not_while_away(self):
        self.bob.away_until = dt.date(2026, 11, 24)
        self.bob.save()
        self.send(f"{MONDAY} 07:00")
        self.send("2026-11-24 07:00")
        self.assertEqual(self.to_bob(), [])
        self.send("2026-11-25 07:00")
        self.assertEqual(len(self.to_bob()), 1)

    def test_only_with_the_daily_digest(self):
        for delivery in [MailDelivery.EACH, MailDelivery.NONE]:
            self.bob.mail_delivery = delivery
            self.bob.save()
            self.send(f"{MONDAY} 07:00")
            self.assertEqual(self.to_bob(), [], delivery)

    def test_nothing_to_say(self):
        """Nothing overdue, nothing waited on: no mail; something becoming
        due later that day waits for tomorrow's"""
        Item.objects.filter(title="Overdue").delete()
        self.send(f"{MONDAY} 07:00")
        self.assertEqual(self.to_bob(), [])
        self.make("Now", to=[self.bob], due_on=dt.date(2026, 11, 23))
        self.quiet_day()
        self.send(f"{MONDAY} 08:00")
        self.assertEqual(self.to_bob(), [])
        self.send("2026-11-24 07:00")
        (message,) = self.to_bob()
        self.assertIn("- Now (Website)", message.body)

    def test_not_to_bounced_addresses(self):
        self.bob.mail_undeliverable_at = at(f"{MONDAY} 06:00")
        self.bob.save()
        self.send(f"{MONDAY} 07:00")
        self.assertEqual(self.to_bob(), [])


class ShorterTest(DigestBase):
    """Mentions and to-dos assigned to the person first and in full; the
    rest one line per item"""

    def test_for_you_first_the_rest_in_a_line(self):
        self.comment("2026-11-22 10:00", content="First")
        with time_machine.travel(at("2026-11-22 11:00"), tick=False):
            self.act(
                lambda: ops.add_comment(self.todo, author=self.cleo, content="Second")
            )
            self.act(
                lambda: ops.add_comment(
                    self.other,
                    author=self.ada,
                    content=f"Look, [@Bob](person:{self.bob.pk})",
                )
            )
        self.make(
            "Assigned", to=[self.bob], notes="The **notes**", when="2026-11-22 12:00"
        )
        self.send(f"{MONDAY} 07:00")
        (message,) = self.to_bob()
        body = message.body
        self.assertLess(body.index("## For you"), body.index("## Website"))
        for_you, rest = body.split("## Website")
        self.assertIn("Look, @Bob", for_you)
        self.assertIn("To-do: Pack", for_you)
        self.assertIn("To-do: Assigned", for_you)
        self.assertIn("The **notes**", for_you)
        self.assertIn(
            "- Order the tent [Visible to clients]\n"
            "  2 comments by Ada Example and Cleo Example.\n",
            rest,
        )
        self.assertNotIn("First", body)
        self.assertNotIn("Second", body)
        html = message.alternatives[0][0]
        self.assertIn("<strong>notes</strong>", html)
        self.assertIn("2 comments by Ada Example and Cleo Example.", html)
        self.assertNotIn("Second", html)

    def test_changes_in_one_line(self):
        self.comment("2026-11-22 10:00")
        with time_machine.travel(at("2026-11-22 11:00"), tick=False):
            self.act(lambda: ops.complete(self.todo, actor=self.ada))
        self.send(f"{MONDAY} 07:00")
        (message,) = self.to_bob()
        self.assertIn(
            "  Ada Example completed it. 1 comment by Ada Example.\n", message.body
        )

    def test_mails_per_change_after_quiet_hours_stay_in_full(self):
        """Who gets a mail per change gets what waited in full"""
        self.bob.mail_delivery = MailDelivery.EACH
        self.bob.quiet_hours = True
        self.bob.save()
        self.comment("2026-11-20 18:30", content="One")
        self.comment("2026-11-20 18:30", self.other, content="Two")
        self.send("2026-11-20 18:31")
        self.send(f"{MONDAY} 08:00")
        (message,) = self.to_bob()
        self.assertIn("One", message.body)
        self.assertIn("Two", message.body)
        self.assertNotIn("Needs you today", message.body)
