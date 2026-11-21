"""Asking on schedule: the risky part (specs/checkins.md)"""

import datetime as dt
import threading
from unittest.mock import patch

from django.core.management import call_command
from django.db import close_old_connections, connection
from django.test import TransactionTestCase, override_settings

from biwak.checkins import operations as ops, schedule
from biwak.checkins.models import Occurrence, Question
from biwak.checkins.support import MONDAY_9, CheckinTestCase, at, local
from biwak.items import operations as item_ops
from biwak.items.models import Item
from biwak.projects import operations as project_ops
from biwak.test_utils import person, project


def next_at(item):
    return local(Question.objects.get(item=item).next_at)


def dates(item):
    return sorted(
        Occurrence.objects.filter(question__item=item).values_list("date", flat=True)
    )


class AskingTest(CheckinTestCase):
    def test_created_between_occurrences_asks_next_monday(self):
        self.assertEqual(next_at(self.item), "2027-03-22 09:00")
        self.assertEqual(self.run_at("2027-03-22 08:59"), {
            "asked": 0, "summarized": 0,
        })  # fmt: skip
        self.assertFalse(Occurrence.objects.exists())
        self.assertEqual(self.run_at("2027-03-22 09:00")["asked"], 1)
        occurrence = Occurrence.objects.get()
        self.assertEqual(occurrence.date, dt.date(2027, 3, 22))
        self.assertEqual(occurrence.asked_at, at("2027-03-22 09:00"))
        self.assertEqual(
            set(occurrence.asked.all()), {self.ada, self.bob}, "Cleo isn't asked"
        )
        self.assertEqual(self.recipients(), [self.ada.email, self.bob.email])
        self.assertEqual(next_at(self.item), "2027-03-29 09:00")

    def test_created_on_the_day_before_the_time_asks_that_day(self):
        item = self.question("Today", now=at("2027-03-22 08:00"))
        self.assertEqual(next_at(item), "2027-03-22 09:00")
        # Exactly at the time: the next date
        item = self.question("Later", now=at("2027-03-22 09:00"))
        self.assertEqual(next_at(item), "2027-03-29 09:00")

    def test_running_again_doesnt_ask_again(self):
        self.run_at("2027-03-22 09:00")
        self.sent()
        for minute in ["09:00", "09:01", "09:30", "23:59"]:
            self.assertEqual(self.run_at(f"2027-03-22 {minute}")["asked"], 0)
        self.assertEqual(Occurrence.objects.count(), 1)
        self.assertEqual(self.sent(), [])

    def test_running_twice_asks_once(self):
        """Two runs one after the other (at once: ``TwoRunsAtOnceTest``)"""
        with self.captureOnCommitCallbacks(execute=True):
            first = ops.ask_due(now=at("2027-03-22 09:00"))
            second = ops.ask_due(now=at("2027-03-22 09:00"))
        self.assertEqual((len(first), len(second)), (1, 0))

    def test_question_mail(self):
        self.run_at("2027-03-22 09:00")
        message = self.sent(self.ada)[0]
        occurrence = Occurrence.objects.get()
        self.assertEqual(message.subject, "[Website] How are you?")
        self.assertIn(
            f"https://biwak.example.org/questions/{self.item.pk}/answer/"
            f"?occurrence={occurrence.pk}",
            message.body,
        )
        self.assertIn("Asked every Monday", message.body)
        self.assertNotIn("Clients can see this", message.body)
        self.assertEqual(message.extra_headers["Auto-Submitted"], "auto-generated")
        self.assertIn("https://biwak.example.org", message.alternatives[0].content)

    def test_one_mail_per_person_even_with_the_same_address_case(self):
        self.run_at("2027-03-22 09:00")
        self.assertEqual(len(self.sent()), 2)

    # Daylight saving time -----------------------------------------------------

    def test_daily_at_nine_stays_nine_across_the_change_to_summer_time(self):
        item = self.question(
            "Daily", rule="FREQ=DAILY", starts_on=dt.date(2027, 3, 1),
            now=at("2027-03-26 10:00"),
        )  # fmt: skip
        times = []
        for day in ["27", "28", "29", "30"]:
            self.run_at(f"2027-03-{day} 08:59")
            self.assertNotIn(
                dt.date(2027, 3, int(day)), dates(item), "not yet at 08:59 local"
            )
            self.run_at(f"2027-03-{day} 09:00")
            self.assertIn(dt.date(2027, 3, int(day)), dates(item))
            times.append(
                local(
                    Occurrence.objects
                    .filter(question__item=item)
                    .latest("date")
                    .asked_at
                )
            )
        self.assertEqual(
            times,
            [
                "2027-03-27 09:00",
                "2027-03-28 09:00",
                "2027-03-29 09:00",
                "2027-03-30 09:00",
            ],
        )
        self.assertEqual(len(dates(item)), 4)

    def test_the_moments_in_utc_move_with_the_clocks(self):
        item = self.question(
            "Daily", rule="FREQ=DAILY", starts_on=dt.date(2027, 3, 1),
            now=at("2027-03-26 10:00"),
        )  # fmt: skip
        stored = []
        for day in ["27", "28", "29"]:
            self.run_at(f"2027-03-{day} 09:00")
            stored.append(Question.objects.get(item=item).next_at.isoformat())
        self.assertEqual(
            stored,
            [
                "2027-03-28 07:00:00+00:00".replace(" ", "T", 1),
                "2027-03-29 07:00:00+00:00".replace(" ", "T", 1),
                "2027-03-30 07:00:00+00:00".replace(" ", "T", 1),
            ],
        )

    def test_daily_across_the_change_to_winter_time(self):
        item = self.question(
            "Daily", rule="FREQ=DAILY", starts_on=dt.date(2027, 10, 1),
            now=at("2027-10-29 10:00"),
        )  # fmt: skip
        for day in ["10-30", "10-31", "11-01", "11-02"]:
            self.run_at(f"2027-{day} 08:59")
            self.run_at(f"2027-{day} 09:00")
            self.run_at(f"2027-{day} 09:01")
        self.assertEqual(
            dates(item),
            [
                dt.date(2027, 10, 30),
                dt.date(2027, 10, 31),
                dt.date(2027, 11, 1),
                dt.date(2027, 11, 2),
            ],
        )
        self.assertEqual(
            local(
                Occurrence.objects.get(
                    question__item=item, date=dt.date(2027, 11, 1)
                ).asked_at
            ),
            "2027-11-01 09:00",
        )

    def test_a_time_in_the_skipped_hour_is_asked_once_an_hour_later(self):
        item = self.question(
            "Night", rule="FREQ=DAILY", starts_on=dt.date(2027, 3, 1),
            time_of_day=dt.time(2, 30), now=at("2027-03-27 12:00"),
        )  # fmt: skip
        self.assertEqual(next_at(item), "2027-03-28 03:30")
        self.run_at("2027-03-28 03:29")
        self.assertEqual(dates(item), [])
        self.run_at("2027-03-28 03:30")
        self.run_at("2027-03-28 04:30")
        self.assertEqual(dates(item), [dt.date(2027, 3, 28)])
        self.assertEqual(next_at(item), "2027-03-29 02:30")

    def test_a_time_in_the_repeated_hour_is_asked_once(self):
        item = self.question(
            "Night", rule="FREQ=DAILY", starts_on=dt.date(2027, 10, 1),
            time_of_day=dt.time(2, 30), now=at("2027-10-30 12:00"),
        )  # fmt: skip
        # 02:30 happens at 00:30 UTC (CEST) and again at 01:30 UTC (CET)
        first = at("2027-10-31 00:30", schedule.zone("UTC"))
        with self.captureOnCommitCallbacks(execute=True):
            asked = ops.ask_due(now=first)
            self.assertEqual([o.question.item_id for o in asked].count(item.pk), 1)
            asked = ops.ask_due(now=first + dt.timedelta(hours=1))
            self.assertNotIn(
                item.pk, [o.question.item_id for o in asked], "the second 02:30"
            )
        self.assertEqual(dates(item), [dt.date(2027, 10, 31)])
        self.assertEqual(next_at(item), "2027-11-01 02:30")

    def test_a_time_in_a_skipped_hour_before_midnight_keeps_its_date(self):
        """America/Nuuk goes from Saturday 27 March 2027 23:00 (-02) to
        Sunday 00:00 (-01): Saturday's 23:30 is asked at Sunday 00:30, and
        Sunday's 23:30 is still asked"""
        nuuk = schedule.zone("America/Nuuk")
        item = self.question(
            "Nuuk", rule="FREQ=DAILY", starts_on=dt.date(2027, 3, 1),
            time_of_day=dt.time(23, 30), time_zone="America/Nuuk",
            now=at("2027-03-27 12:00", nuuk),
        )  # fmt: skip
        self.run_at("2027-03-28 00:30", nuuk)
        self.run_at("2027-03-28 23:30", nuuk)
        self.assertEqual(dates(item), [dt.date(2027, 3, 27), dt.date(2027, 3, 28)])

    # Time zones --------------------------------------------------------------

    def test_each_question_in_its_own_time_zone(self):
        tokyo = self.question(
            "Tokyo", time_zone="Asia/Tokyo", now=at("2027-03-19 12:00")
        )
        new_york = self.question(
            "New York", time_zone="America/New_York", now=at("2027-03-19 12:00")
        )
        # Monday 22 March: 09:00 in Tokyo is 00:00 UTC, 09:00 in Zurich
        # (winter time until the 28th) is 08:00 UTC, 09:00 in New York (summer
        # time since the 14th) is 13:00 UTC
        utc = schedule.zone("UTC")
        self.run_at("2027-03-22 00:00", utc)
        self.assertEqual(dates(tokyo), [dt.date(2027, 3, 22)])
        self.assertEqual(dates(self.item), [])
        self.assertEqual(dates(new_york), [])
        self.run_at("2027-03-22 08:00", utc)
        self.assertEqual(dates(self.item), [dt.date(2027, 3, 22)])
        self.assertEqual(dates(new_york), [])
        self.run_at("2027-03-22 13:00", utc)
        self.assertEqual(dates(new_york), [dt.date(2027, 3, 22)])

    def test_the_date_is_the_date_in_the_questions_zone(self):
        """23:30 on Sunday in Zurich is Monday 07:30 in Tokyo, 09:00 there
        is next"""
        tokyo = self.question(
            "Tokyo", time_zone="Asia/Tokyo", now=at("2027-03-21 23:30")
        )
        self.assertEqual(
            local(
                Question.objects.get(item=tokyo).next_at, schedule.zone("Asia/Tokyo")
            ),
            "2027-03-22 09:00",
        )

    def test_default_time_zone_is_the_installations(self):
        item = ops.create_question(
            project=self.project, title="Default", creator=self.ada,
            now=at("2027-03-19 12:00"), **MONDAY_9,
        )  # fmt: skip
        self.assertEqual(item.question.time_zone, "Europe/Zurich")

    def test_unknown_time_zone(self):
        with self.assertRaises(ValueError):
            self.question("Mars", time_zone="Mars/Olympus")
        with self.assertRaises(ValueError):
            ops.update_question(self.item, actor=self.ada, time_zone="Mars/Olympus")

    # Month ends --------------------------------------------------------------

    def test_the_last_day_of_every_month(self):
        item = self.question(
            "Month end",
            rule="FREQ=MONTHLY;BYMONTHDAY=28,29,30,31;BYSETPOS=-1",
            starts_on=dt.date(2027, 1, 1),
            now=at("2027-01-01 00:00"),
        )
        for day in [
            "2027-01-31",
            "2027-02-28",
            "2027-03-31",
            "2027-04-30",
            "2028-01-31",
        ]:
            self.run_at(f"{day} 09:00")
        # 2028 is a leap year, but we jumped from April 2027: January
        self.assertEqual(
            dates(item),
            [
                dt.date(2027, 1, 31),
                dt.date(2027, 2, 28),
                dt.date(2027, 3, 31),
                dt.date(2027, 4, 30),
                dt.date(2028, 1, 31),
            ],
        )

    def test_the_29th_of_february_in_a_leap_year(self):
        item = self.question(
            "Leap",
            rule="FREQ=MONTHLY;BYMONTHDAY=29,30,31;BYSETPOS=-1",
            starts_on=dt.date(2028, 1, 1),
            now=at("2028-02-01 00:00"),
        )
        self.assertEqual(next_at(item), "2028-02-29 09:00")
        self.run_at("2028-02-29 09:00")
        self.assertEqual(next_at(item), "2028-03-31 09:00")

    def test_every_three_months_on_the_31st_ends_on_each_months_last_day(self):
        item = self.question(
            "Quarterly",
            rule="FREQ=MONTHLY;INTERVAL=3;BYMONTHDAY=28,29,30,31;BYSETPOS=-1",
            starts_on=dt.date(2027, 1, 31),
            now=at("2027-01-01 00:00"),
        )
        found = []
        for _n in range(4):
            found.append(next_at(item)[:10])
            self.run_at(f"{found[-1]} 09:00")
        self.assertEqual(
            found, ["2027-01-31", "2027-04-30", "2027-07-31", "2027-10-31"]
        )

    def test_the_first_monday_of_every_month(self):
        item = self.question(
            "First Monday",
            rule="FREQ=MONTHLY;BYDAY=MO;BYSETPOS=1",
            starts_on=dt.date(2027, 1, 1),
            now=at("2027-03-19 12:00"),
        )
        found = []
        for _n in range(3):
            found.append(next_at(item)[:10])
            self.run_at(f"{found[-1]} 09:00")
        self.assertEqual(found, ["2027-04-05", "2027-05-03", "2027-06-07"])

    def test_every_two_weeks_keeps_its_phase(self):
        item = self.question(
            "Biweekly",
            rule="FREQ=WEEKLY;INTERVAL=2;BYDAY=MO",
            starts_on=dt.date(2027, 3, 8),
            now=at("2027-03-19 12:00"),
        )
        found = []
        for _n in range(3):
            found.append(next_at(item)[:10])
            self.run_at(f"{found[-1]} 09:00")
        self.assertEqual(found, ["2027-03-22", "2027-04-05", "2027-04-19"])

    def test_not_before_the_start_date(self):
        item = self.question("Later", starts_on=dt.date(2027, 5, 3))
        self.assertEqual(next_at(item), "2027-05-03 09:00")
        self.run_at("2027-04-26 09:00")
        self.assertEqual(dates(item), [])

    def test_a_first_date_on_another_weekday_or_day(self):
        """Rules from the API or the CLI: the first date is a Friday.
        Current behaviour, to be confirmed (specs/checkins.md): every two
        weeks counts its phase from the first date's week, so the Monday
        right after isn't asked"""
        found = {}
        for rule in [
            "FREQ=WEEKLY;BYDAY=MO",
            "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO",
            "FREQ=MONTHLY;BYMONTHDAY=1",
            "FREQ=MONTHLY;BYDAY=MO;BYSETPOS=1",
            "FREQ=YEARLY;BYMONTH=1;BYMONTHDAY=1",
        ]:
            item = self.question(rule, rule=rule, starts_on=dt.date(2027, 3, 19))
            found[rule] = next_at(item)[:10]
        self.assertEqual(
            found,
            {
                "FREQ=WEEKLY;BYDAY=MO": "2027-03-22",
                "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO": "2027-03-29",
                "FREQ=MONTHLY;BYMONTHDAY=1": "2027-04-01",
                "FREQ=MONTHLY;BYDAY=MO;BYSETPOS=1": "2027-04-05",
                "FREQ=YEARLY;BYMONTH=1;BYMONTHDAY=1": "2028-01-01",
            },
        )
        self.run_at("2027-03-29 09:00")
        self.assertEqual(
            next_at(Item.objects.get(title="FREQ=WEEKLY;INTERVAL=2;BYDAY=MO")),
            "2027-04-12 09:00",
        )

    # Downtime ----------------------------------------------------------------

    def test_after_downtime_the_latest_date_is_asked_once(self):
        item = self.question("Daily", rule="FREQ=DAILY", starts_on=dt.date(2027, 3, 1))
        self.run_at("2027-03-22 12:00")
        # Five days without a run
        self.assertEqual(self.run_at("2027-03-26 10:00")["asked"], 1)
        self.assertEqual(
            dates(item),
            [dt.date(2027, 3, 22), dt.date(2027, 3, 26)],
        )
        self.assertEqual(next_at(item), "2027-03-27 09:00")

    def test_a_run_a_few_minutes_late_still_asks(self):
        self.run_at("2027-03-22 09:07")
        occurrence = Occurrence.objects.get()
        self.assertEqual(occurrence.date, dt.date(2027, 3, 22))
        self.assertEqual(occurrence.asked_at, at("2027-03-22 09:07"))

    # Pausing -----------------------------------------------------------------

    def test_paused_questions_arent_asked(self):
        ops.pause(self.item, actor=self.ada)
        question = Question.objects.get(item=self.item)
        self.assertIsNotNone(question.paused_at)
        self.assertIsNone(question.next_at)
        self.assertEqual(self.run_at("2027-03-22 09:00")["asked"], 0)
        self.assertEqual(self.run_at("2027-03-29 09:00")["asked"], 0)
        self.assertEqual(self.sent(), [])

    def test_resuming_doesnt_ask_the_missed_occurrences(self):
        ops.pause(self.item, actor=self.ada)
        self.run_at("2027-03-22 09:00")
        self.run_at("2027-03-29 09:00")
        # Resumed on Wednesday: Monday's is missed, the next is on the 5th
        ops.resume(self.item, actor=self.ada, now=at("2027-03-31 10:00"))
        self.assertEqual(next_at(self.item), "2027-04-05 09:00")
        self.assertEqual(self.run_at("2027-03-31 10:01")["asked"], 0)
        self.assertEqual(self.run_at("2027-04-05 09:00")["asked"], 1)
        self.assertEqual(dates(self.item), [dt.date(2027, 4, 5)])

    def test_resuming_before_the_time_asks_today(self):
        ops.pause(self.item, actor=self.ada)
        ops.resume(self.item, actor=self.ada, now=at("2027-03-22 08:00"))
        self.assertEqual(next_at(self.item), "2027-03-22 09:00")

    def test_pausing_after_the_time_came_but_before_the_run(self):
        ops.pause(self.item, actor=self.ada)
        self.assertEqual(self.run_at("2027-03-22 09:00")["asked"], 0)

    def test_pausing_and_resuming_twice_changes_nothing(self):
        ops.pause(self.item, actor=self.ada)
        paused_at = Question.objects.get(item=self.item).paused_at
        ops.pause(self.item, actor=self.ada)
        self.assertEqual(Question.objects.get(item=self.item).paused_at, paused_at)
        ops.resume(self.item, actor=self.ada, now=at("2027-03-20 10:00"))
        ops.resume(self.item, actor=self.ada, now=at("2027-03-21 10:00"))
        self.assertEqual(next_at(self.item), "2027-03-22 09:00")

    # Questions which can't be asked ------------------------------------------

    def test_trashed_questions_arent_asked_and_dont_catch_up_when_restored(self):
        item_ops.trash(self.item, actor=self.ada)
        self.assertEqual(self.run_at("2027-03-22 09:00")["asked"], 0)
        self.assertEqual(next_at(self.item), "2027-03-29 09:00")
        item_ops.restore(Item.objects.get(pk=self.item.pk), actor=self.ada)
        self.assertEqual(self.run_at("2027-03-22 10:00")["asked"], 0)
        self.assertEqual(self.run_at("2027-03-29 09:00")["asked"], 1)

    def test_archived_questions_and_questions_of_archived_projects(self):
        item_ops.archive(self.item, actor=self.ada)
        self.assertEqual(self.run_at("2027-03-22 09:00")["asked"], 0)
        item_ops.unarchive(Item.objects.get(pk=self.item.pk), actor=self.ada)
        project_ops.archive_project(self.project, actor=self.ada)
        self.assertEqual(self.run_at("2027-03-29 09:00")["asked"], 0)
        self.assertEqual(dates(self.item), [])
        self.assertEqual(self.sent(), [])

    # Editing the schedule ----------------------------------------------------

    def test_a_new_time_today_asks_today_if_still_ahead(self):
        ops.update_question(
            self.item, actor=self.ada, time_of_day=dt.time(10, 0),
            now=at("2027-03-22 08:00"),
        )  # fmt: skip
        self.assertEqual(next_at(self.item), "2027-03-22 10:00")
        self.run_at("2027-03-22 09:00")
        self.assertEqual(dates(self.item), [])
        self.run_at("2027-03-22 10:00")
        self.assertEqual(dates(self.item), [dt.date(2027, 3, 22)])

    def test_a_new_time_which_passed_asks_next_week(self):
        ops.update_question(
            self.item, actor=self.ada, time_of_day=dt.time(8, 0),
            now=at("2027-03-22 08:30"),
        )  # fmt: skip
        self.assertEqual(next_at(self.item), "2027-03-29 08:00")

    def test_a_date_asked_already_isnt_asked_again_when_the_time_moves(self):
        self.run_at("2027-03-22 09:00")
        self.sent()
        ops.update_question(
            self.item, actor=self.ada, time_of_day=dt.time(11, 0),
            now=at("2027-03-22 09:30"),
        )  # fmt: skip
        self.assertEqual(next_at(self.item), "2027-03-22 11:00")
        self.assertEqual(self.run_at("2027-03-22 11:00")["asked"], 0)
        self.assertEqual(self.sent(), [])
        self.assertEqual(Occurrence.objects.count(), 1)
        self.assertEqual(next_at(self.item), "2027-03-29 11:00")

    def test_a_new_rule_counts_from_now(self):
        ops.update_question(
            self.item, actor=self.ada, rule="FREQ=WEEKLY;BYDAY=WE",
            now=at("2027-03-22 12:00"),
        )  # fmt: skip
        self.assertEqual(next_at(self.item), "2027-03-24 09:00")

    def test_a_new_time_zone_moves_the_moment(self):
        ops.update_question(
            self.item, actor=self.ada, time_zone="Asia/Tokyo",
            now=at("2027-03-19 12:00"),
        )  # fmt: skip
        self.assertEqual(
            local(
                Question.objects.get(item=self.item).next_at,
                schedule.zone("Asia/Tokyo"),
            ),
            "2027-03-22 09:00",
        )

    def test_a_new_rule_on_the_day_it_was_asked(self):
        """Current behaviour, to be confirmed (specs/checkins.md)"""
        self.run_at("2027-03-22 09:00")
        ops.update_question(
            self.item, actor=self.ada, rule="FREQ=DAILY",
            now=at("2027-03-22 10:00"),
        )  # fmt: skip
        self.assertEqual(next_at(self.item), "2027-03-23 09:00")
        self.assertEqual(self.run_at("2027-03-23 09:00")["asked"], 1)
        self.assertEqual(dates(self.item), [dt.date(2027, 3, 22), dt.date(2027, 3, 23)])

    def test_a_new_time_zone_on_the_day_it_was_asked(self):
        """Current behaviour, to be confirmed (specs/checkins.md): a zone
        where it is still Monday asks Monday's date there, which was asked
        already; one where Monday's time passed asks next Monday"""
        new_york = schedule.zone("America/New_York")
        self.run_at("2027-03-22 09:00")
        ops.update_question(
            self.item, actor=self.ada, time_zone="America/New_York",
            now=at("2027-03-22 10:00"),
        )  # fmt: skip
        self.assertEqual(
            local(Question.objects.get(item=self.item).next_at, new_york),
            "2027-03-22 09:00",
        )
        self.assertEqual(self.run_at("2027-03-22 09:00", new_york)["asked"], 0)
        self.assertEqual(dates(self.item), [dt.date(2027, 3, 22)])
        self.assertEqual(
            local(Question.objects.get(item=self.item).next_at, new_york),
            "2027-03-29 09:00",
        )
        ops.update_question(
            self.item, actor=self.ada, time_zone="Asia/Tokyo",
            now=at("2027-03-22 10:00", new_york),
        )  # fmt: skip
        self.assertEqual(
            local(
                Question.objects.get(item=self.item).next_at,
                schedule.zone("Asia/Tokyo"),
            ),
            "2027-03-29 09:00",
        )

    def test_a_new_time_zone_on_the_day_before_it_was_asked(self):
        """Current behaviour, to be confirmed: at 08:00 in Zurich, 09:00
        in Tokyo has passed, so Monday isn't asked at all"""
        ops.update_question(
            self.item, actor=self.ada, time_zone="Asia/Tokyo",
            now=at("2027-03-22 08:00"),
        )  # fmt: skip
        self.assertEqual(
            local(
                Question.objects.get(item=self.item).next_at,
                schedule.zone("Asia/Tokyo"),
            ),
            "2027-03-29 09:00",
        )
        self.run_at("2027-03-22 09:00")
        self.assertEqual(dates(self.item), [])

    def test_editing_a_paused_question_leaves_it_paused(self):
        ops.pause(self.item, actor=self.ada)
        ops.update_question(
            self.item, actor=self.ada, time_of_day=dt.time(10, 0), title="Better"
        )
        self.assertIsNone(Question.objects.get(item=self.item).next_at)
        self.assertEqual(Item.objects.get(pk=self.item.pk).title, "Better")

    def test_invalid_rules(self):
        for rule in ["", "FREQ=HOURLY", "FREQ=DAILY;COUNT=3", "nonsense"]:
            with self.assertRaises(ValueError):
                self.question("Bad", rule=rule)
        with self.assertRaises(ValueError):
            ops.update_question(self.item, actor=self.ada, rule="FREQ=SECONDLY")

    # People ------------------------------------------------------------------

    def test_people_removed_arent_asked(self):
        ops.set_people(self.item, [self.ada], actor=self.ada)
        self.run_at("2027-03-22 09:00")
        self.assertEqual(self.recipients(), [self.ada.email])
        self.assertEqual(set(Occurrence.objects.get().asked.all()), {self.ada})

    def test_people_added_are_asked_from_the_next_occurrence(self):
        self.run_at("2027-03-22 09:00")
        self.sent()
        dora = person("Dora")
        project_ops.add_member(self.project, dora, actor=self.ada)
        ops.set_people(self.item, [self.ada, self.bob, dora], actor=self.ada)
        self.assertEqual(self.recipients(), [])
        self.run_at("2027-03-29 09:00")
        self.assertEqual(
            self.recipients(), sorted([self.ada.email, self.bob.email, dora.email])
        )
        first, second = Occurrence.objects.order_by("date")
        self.assertNotIn(dora, first.asked.all())
        self.assertIn(dora, second.asked.all())

    def test_nobody_asked_still_makes_an_occurrence(self):
        ops.set_people(self.item, [], actor=self.ada)
        self.run_at("2027-03-22 09:00")
        self.assertEqual(Occurrence.objects.count(), 1)
        self.assertEqual(self.sent(), [])

    def test_inactive_people_arent_asked(self):
        self.bob.is_active = False
        self.bob.save()
        self.run_at("2027-03-22 09:00")
        self.assertEqual(self.recipients(), [self.ada.email])

    def test_clients_only_on_visible_questions(self):
        with self.assertRaises(ValueError):
            ops.set_people(self.item, [self.ada, self.cleo], actor=self.ada)
        visible = self.question("Shared", visible=True, people=[self.ada, self.cleo])
        self.assertTrue(visible.is_client_visible)
        self.run_at("2027-03-22 09:00")
        self.assertEqual(self.recipients(), sorted([
            self.ada.email, self.bob.email, self.ada.email, self.cleo.email,
        ]))  # fmt: skip
        # The question turns internal: the client isn't asked any more
        item_ops.set_visibility(
            Item.objects.get(pk=visible.pk), visible=False, actor=self.ada
        )
        self.run_at("2027-03-29 09:00")
        self.assertEqual(
            self.recipients(), sorted([self.ada.email, self.bob.email, self.ada.email])
        )
        # And is still in the list of people when it turns visible again
        item_ops.set_visibility(
            Item.objects.get(pk=visible.pk), visible=True, actor=self.ada
        )
        self.run_at("2027-04-05 09:00")
        self.assertIn(self.cleo.email, self.recipients())

    def test_people_who_arent_members_cant_be_asked(self):
        outsider = person("Dora", client=True)
        with self.assertRaises(ValueError):
            self.question("Shared", visible=True, people=[outsider])

    def test_those_asked_are_subscribed_and_those_removed_are_not(self):
        from biwak.activity.models import Subscription

        def subscribed():
            return set(
                Subscription.objects.filter(item=self.item).values_list(
                    "user", flat=True
                )
            )

        self.assertEqual(subscribed(), {self.ada.pk, self.bob.pk})
        ops.set_people(self.item, [self.bob], actor=self.ada)
        self.assertEqual(subscribed(), {self.bob.pk})
        ops.set_people(self.item, [self.ada, self.bob], actor=self.ada)
        self.assertEqual(subscribed(), {self.ada.pk, self.bob.pk})

    # The command -------------------------------------------------------------

    def test_send_mails_asks_the_questions(self):
        with (
            patch(
                "biwak.checkins.operations.timezone.now",
                return_value=at("2027-03-22 09:00"),
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            call_command("send_mails")
        self.assertEqual(Occurrence.objects.count(), 1)
        self.assertEqual(len(self.sent()), 2)

    def test_failing_mail_doesnt_keep_the_others(self):
        from django.core.mail import EmailMultiAlternatives

        real = EmailMultiAlternatives.send
        calls = []

        def flaky(message, *args, **kwargs):
            calls.append(message.to)
            if len(calls) == 1:
                raise OSError("down")
            return real(message, *args, **kwargs)

        with (
            patch.object(EmailMultiAlternatives, "send", flaky),
            self.assertLogs("biwak.checkins.mails", "ERROR"),
        ):
            self.run_at("2027-03-22 09:00")
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(self.sent()), 1)


@override_settings(
    BASE_URL="https://biwak.example.org", DEFAULT_FROM_EMAIL="biwak@example.org"
)
class TwoRunsAtOnceTest(TransactionTestCase):
    def test_the_second_run_skips_the_question_the_first_is_asking(self):
        """While the first run holds the question's lock, the second skips
        it at once (``skip_locked``) instead of waiting or asking too"""
        ada = person("Ada")
        ops.create_question(
            project=project(members=[ada]), title="How are you?", creator=ada,
            people=[ada], now=at("2027-03-19 12:00"), **MONDAY_9,
        )  # fmt: skip
        locked, release = threading.Event(), threading.Event()
        latest_due = schedule.latest_due

        def first_waits(question, **kwargs):
            if not locked.is_set():
                locked.set()
                release.wait(10)
            return latest_due(question, **kwargs)

        results = {}

        def run(name):
            try:
                results[name] = len(ops.ask_due(now=at("2027-03-22 09:00")))
            finally:
                close_old_connections()
                connection.close()

        with patch.object(schedule, "latest_due", first_waits):
            first = threading.Thread(target=run, args=["first"])
            first.start()
            self.assertTrue(locked.wait(10))
            second = threading.Thread(target=run, args=["second"])
            second.start()
            second.join(5)
            waited = second.is_alive()
            release.set()
            first.join()
            second.join()
        self.assertFalse(waited, "the second run waited for the first")
        self.assertEqual(results, {"first": 1, "second": 0})
        self.assertEqual(Occurrence.objects.count(), 1)
