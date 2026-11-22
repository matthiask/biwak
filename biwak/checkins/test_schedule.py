import datetime as dt
from importlib import import_module
from zoneinfo import ZoneInfo

from django.apps import apps
from django.test import SimpleTestCase, override_settings

from biwak.activity.models import Event
from biwak.checkins import schedule
from biwak.checkins.models import Question
from biwak.checkins.support import CheckinTestCase
from biwak.items import operations as item_ops
from biwak.items.models import Todo


ZURICH = ZoneInfo("Europe/Zurich")
UTC = dt.UTC


def utc(text):
    return dt.datetime.fromisoformat(text).replace(tzinfo=UTC)


def local(moment, tz=ZURICH):
    return moment.astimezone(tz).replace(tzinfo=None).isoformat(" ")


def next_fire(**kwargs):
    """The moment of ``schedule.next_occurrence()``"""
    found = schedule.next_occurrence(**kwargs)
    return found and found[1]


def fires(rule, after, *, at=dt.time(9, 0), tz="Europe/Zurich", starts_on, count=3):
    """The next ``count`` moments, in local wall clock time"""
    result = []
    moment = utc(after)
    for _n in range(count):
        moment = next_fire(
            rule=rule, starts_on=starts_on, time_of_day=at, time_zone=tz, after=moment
        )
        result.append(local(moment, ZoneInfo(tz)))
    return result


class FireAtTest(SimpleTestCase):
    def test_wall_clock_time_stays_across_the_changes(self):
        """09:00 in Zurich is 08:00 UTC in winter and 07:00 UTC in summer"""
        nine = dt.time(9, 0)
        self.assertEqual(
            schedule.fire_at(dt.date(2027, 3, 27), nine, "Europe/Zurich"),
            utc("2027-03-27 08:00"),
        )
        self.assertEqual(
            schedule.fire_at(dt.date(2027, 3, 29), nine, "Europe/Zurich"),
            utc("2027-03-29 07:00"),
        )
        self.assertEqual(
            schedule.fire_at(dt.date(2027, 10, 30), nine, "Europe/Zurich"),
            utc("2027-10-30 07:00"),
        )
        self.assertEqual(
            schedule.fire_at(dt.date(2027, 11, 1), nine, "Europe/Zurich"),
            utc("2027-11-01 08:00"),
        )

    def test_other_zones_change_on_their_own_dates(self):
        """09:00 stays 09:00 in New York (clocks forward on 14 March, back on
        7 November 2027) and in Sydney (back on 4 April, forward on 3
        October: the southern summer)"""
        nine = dt.time(9, 0)
        for zone, day, offset in [
            ("America/New_York", dt.date(2027, 3, 13), 5),
            ("America/New_York", dt.date(2027, 3, 15), 4),
            ("America/New_York", dt.date(2027, 11, 6), 4),
            ("America/New_York", dt.date(2027, 11, 8), 5),
            ("Australia/Sydney", dt.date(2027, 4, 3), -11),
            ("Australia/Sydney", dt.date(2027, 4, 5), -10),
            ("Australia/Sydney", dt.date(2027, 10, 2), -10),
            ("Australia/Sydney", dt.date(2027, 10, 4), -11),
        ]:
            moment = schedule.fire_at(day, nine, zone)
            expected = dt.datetime.combine(day, nine, tzinfo=UTC) + dt.timedelta(
                hours=offset
            )
            self.assertEqual(moment, expected, (zone, day))
            self.assertEqual(local(moment, ZoneInfo(zone)), f"{day} 09:00:00")

    def test_time_zones(self):
        nine = dt.time(9, 0)
        day = dt.date(2027, 1, 15)
        self.assertEqual(schedule.fire_at(day, nine, "UTC"), utc("2027-01-15 09:00"))
        self.assertEqual(
            schedule.fire_at(day, nine, "America/New_York"), utc("2027-01-15 14:00")
        )
        # No daylight saving time, half an hour
        self.assertEqual(
            schedule.fire_at(day, nine, "Asia/Kolkata"), utc("2027-01-15 03:30")
        )
        # The date is the date in the zone: 23:30 in Auckland is the day
        # before in UTC
        self.assertEqual(
            schedule.fire_at(day, dt.time(23, 30), "Pacific/Auckland"),
            utc("2027-01-15 10:30"),
        )

    def test_a_time_which_doesnt_exist_is_an_hour_later(self):
        # 28 March 2027: 02:00 became 03:00 in Zurich
        moment = schedule.fire_at(dt.date(2027, 3, 28), dt.time(2, 30), "Europe/Zurich")
        self.assertEqual(local(moment), "2027-03-28 03:30:00")

    def test_a_time_which_happens_twice_is_the_first(self):
        # 31 October 2027: 03:00 became 02:00, 02:30 happens twice
        moment = schedule.fire_at(
            dt.date(2027, 10, 31), dt.time(2, 30), "Europe/Zurich"
        )
        self.assertEqual(moment, utc("2027-10-31 00:30"))  # 02:30 CEST

    def test_unknown_time_zone(self):
        for name in ["Mars/Olympus", "", "../etc/passwd"]:
            with self.assertRaises(ValueError):
                schedule.zone(name)


class NextFireTest(SimpleTestCase):
    def test_daily_across_the_change_to_summer_time(self):
        self.assertEqual(
            fires(
                "FREQ=DAILY", "2027-03-26 12:00", starts_on=dt.date(2027, 1, 1), count=4
            ),
            [
                "2027-03-27 09:00:00",
                "2027-03-28 09:00:00",
                "2027-03-29 09:00:00",
                "2027-03-30 09:00:00",
            ],
        )

    def test_daily_across_the_change_to_winter_time(self):
        self.assertEqual(
            fires(
                "FREQ=DAILY", "2027-10-29 12:00", starts_on=dt.date(2027, 1, 1), count=4
            ),
            [
                "2027-10-30 09:00:00",
                "2027-10-31 09:00:00",
                "2027-11-01 09:00:00",
                "2027-11-02 09:00:00",
            ],
        )

    def test_the_gaps_between_utc_times_are_23_and_25_hours(self):
        before = schedule.fire_at(dt.date(2027, 3, 27), dt.time(9), "Europe/Zurich")
        after = next_fire(
            rule="FREQ=DAILY",
            starts_on=dt.date(2027, 1, 1),
            time_of_day=dt.time(9),
            time_zone="Europe/Zurich",
            after=before,
        )
        self.assertEqual(after - before, dt.timedelta(hours=23))
        before = schedule.fire_at(dt.date(2027, 10, 30), dt.time(9), "Europe/Zurich")
        after = next_fire(
            rule="FREQ=DAILY",
            starts_on=dt.date(2027, 1, 1),
            time_of_day=dt.time(9),
            time_zone="Europe/Zurich",
            after=before,
        )
        self.assertEqual(after - before, dt.timedelta(hours=25))

    def test_today_if_the_time_is_still_ahead_else_the_next_date(self):
        weekly = "FREQ=WEEKLY;BYDAY=MO"
        start = dt.date(2027, 1, 4)
        # Monday 8 March 2027, 09:00 Zurich is 08:00 UTC
        self.assertEqual(
            fires(weekly, "2027-03-08 07:59", starts_on=start, count=1),
            ["2027-03-08 09:00:00"],
        )
        # Exactly at the time: strictly after
        self.assertEqual(
            fires(weekly, "2027-03-08 08:00", starts_on=start, count=1),
            ["2027-03-15 09:00:00"],
        )

    def test_the_date_is_the_date_in_the_zone(self):
        """23:30 UTC on Sunday is already Monday 00:30 in Zurich: Monday's
        09:00 is next, not the following Monday"""
        self.assertEqual(
            fires(
                "FREQ=WEEKLY;BYDAY=MO",
                "2027-01-10 23:30",
                starts_on=dt.date(2027, 1, 4),
                count=1,
            ),
            ["2027-01-11 09:00:00"],
        )
        # And the other way: Monday 08:00 in Los Angeles is Monday 16:00 UTC
        self.assertEqual(
            fires(
                "FREQ=WEEKLY;BYDAY=MO",
                "2027-01-11 03:00",
                at=dt.time(8, 0),
                tz="America/Los_Angeles",
                starts_on=dt.date(2027, 1, 4),
                count=1,
            ),
            ["2027-01-11 08:00:00"],
        )

    def test_month_ends(self):
        rule = "FREQ=MONTHLY;BYMONTHDAY=28,29,30,31;BYSETPOS=-1"
        self.assertEqual(
            fires(rule, "2027-01-01 00:00", starts_on=dt.date(2027, 1, 1), count=4),
            [
                "2027-01-31 09:00:00",
                "2027-02-28 09:00:00",
                "2027-03-31 09:00:00",
                "2027-04-30 09:00:00",
            ],
        )
        # The 31st clamped to the last day, a leap year included
        self.assertEqual(
            fires(rule, "2028-01-31 12:00", starts_on=dt.date(2027, 1, 1), count=1),
            ["2028-02-29 09:00:00"],
        )

    def test_the_first_weekday_of_the_month(self):
        self.assertEqual(
            fires(
                "FREQ=MONTHLY;BYDAY=MO;BYSETPOS=1",
                "2027-03-01 00:00",
                starts_on=dt.date(2027, 1, 4),
                count=3,
            ),
            ["2027-03-01 09:00:00", "2027-04-05 09:00:00", "2027-05-03 09:00:00"],
        )

    def test_every_two_weeks_keeps_its_phase_from_the_start_date(self):
        rule = "FREQ=WEEKLY;INTERVAL=2;BYDAY=MO"
        self.assertEqual(
            fires(rule, "2027-03-01 00:00", starts_on=dt.date(2027, 3, 1), count=3),
            ["2027-03-01 09:00:00", "2027-03-15 09:00:00", "2027-03-29 09:00:00"],
        )
        # Counted from another Monday: the other weeks
        self.assertEqual(
            fires(rule, "2027-03-01 00:00", starts_on=dt.date(2027, 3, 8), count=2),
            ["2027-03-08 09:00:00", "2027-03-22 09:00:00"],
        )

    def test_not_before_the_start_date(self):
        self.assertEqual(
            fires(
                "FREQ=WEEKLY;BYDAY=MO",
                "2027-01-01 00:00",
                starts_on=dt.date(2027, 2, 1),
                count=1,
            ),
            ["2027-02-01 09:00:00"],
        )

    def test_a_time_which_doesnt_exist_asks_once_an_hour_later(self):
        self.assertEqual(
            fires(
                "FREQ=DAILY",
                "2027-03-27 12:00",
                at=dt.time(2, 30),
                starts_on=dt.date(2027, 1, 1),
                count=3,
            ),
            ["2027-03-28 03:30:00", "2027-03-29 02:30:00", "2027-03-30 02:30:00"],
        )

    def test_a_time_which_happens_twice_asks_once(self):
        # 02:30 CEST (00:30 UTC) is the first, 02:30 CET (01:30 UTC) the second
        moments = []
        moment = utc("2027-10-30 12:00")
        for _n in range(3):
            moment = next_fire(
                rule="FREQ=DAILY",
                starts_on=dt.date(2027, 1, 1),
                time_of_day=dt.time(2, 30),
                time_zone="Europe/Zurich",
                after=moment,
            )
            moments.append(moment)
        self.assertEqual(
            moments,
            [utc("2027-10-31 00:30"), utc("2027-11-01 01:30"), utc("2027-11-02 01:30")],
        )

    def test_yearly_on_the_29th_of_february(self):
        rule = "FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=28,29;BYSETPOS=-1"
        self.assertEqual(
            fires(rule, "2027-01-01 00:00", starts_on=dt.date(2024, 2, 29), count=3),
            ["2027-02-28 09:00:00", "2028-02-29 09:00:00", "2029-02-28 09:00:00"],
        )

    def test_latest_due_after_downtime_is_one_date(self):
        class Q:
            rule = "FREQ=DAILY"
            starts_on = dt.date(2027, 1, 1)
            time_of_day = dt.time(9)

        first = schedule.fire_at(dt.date(2027, 3, 1), dt.time(9), "Europe/Zurich")
        now = schedule.fire_at(dt.date(2027, 3, 5), dt.time(9, 30), "Europe/Zurich")
        self.assertEqual(
            schedule.latest_due(Q, first=first, now=now),
            (
                dt.date(2027, 3, 5),
                schedule.fire_at(dt.date(2027, 3, 5), dt.time(9), "Europe/Zurich"),
            ),
        )
        # Nothing missed: the first stays
        self.assertEqual(
            schedule.latest_due(Q, first=first, now=first + dt.timedelta(minutes=5)),
            (dt.date(2027, 3, 1), first),
        )

    @override_settings(TIME_ZONE="America/Nuuk")
    def test_the_date_of_a_time_in_a_gap_before_midnight_is_the_rules(self):
        """America/Nuuk goes from Saturday 27 March 2027 23:00 (-02) to
        Sunday 00:00 (-01): Saturday's 23:30 is Sunday 00:30"""

        class Q:
            rule = "FREQ=DAILY"
            starts_on = dt.date(2027, 1, 1)
            time_of_day = dt.time(23, 30)

        nuuk = "America/Nuuk"
        saturday = schedule.fire_at(dt.date(2027, 3, 27), Q.time_of_day, nuuk)
        self.assertEqual(schedule.local_date(saturday, nuuk).day, 28)
        self.assertEqual(
            schedule.latest_due(Q, first=saturday, now=saturday),
            (dt.date(2027, 3, 27), saturday),
        )
        # A minute before it (Sunday 00:29), Saturday's is next, not Sunday's
        self.assertEqual(
            schedule.next_occurrence_of(Q, after=saturday - dt.timedelta(minutes=1)),
            (dt.date(2027, 3, 27), saturday),
        )


class StoredRuleTest(SimpleTestCase):
    def test_a_stored_rule_which_isnt_valid_is_never_asked(self):
        """INTERVAL=0 made send_mails loop forever"""
        self.assertIsNone(
            next_fire(
                rule="FREQ=DAILY;INTERVAL=0",
                starts_on=dt.date(2027, 3, 22),
                time_of_day=dt.time(9, 0),
                time_zone="Europe/Zurich",
                after=utc("2027-03-22 12:00"),
            )
        )


class CanonicalRulesMigrationTest(CheckinTestCase):
    def test_stored_rules_become_canonical(self):
        """To-do recurrences and question rules, without events and
        without a new ``next_at``; rules which aren't valid stay"""
        migration = import_module("biwak.checkins.migrations.0005_canonical_rules")
        todolist = item_ops.create_list(
            project=self.project, title="Chores", creator=self.ada
        )
        todos = [
            item_ops.create_todo(todolist=todolist, title=str(n), creator=self.ada)
            for n in range(4)
        ]
        written = {
            "FREQ=WEEKLY;BYDAY=TH,MO": "FREQ=WEEKLY;BYDAY=MO,TH",
            "BYDAY=MO;FREQ=WEEKLY;INTERVAL=1;WKST=MO": "FREQ=WEEKLY;BYDAY=MO",
            "FREQ=DAILY;INTERVAL=0": "FREQ=DAILY;INTERVAL=0",
            "": "",
        }
        for todo, rule in zip(todos, written, strict=True):
            Todo.objects.filter(item=todo).update(recurrence=rule)
        Question.objects.filter(item=self.item).update(
            rule="FREQ=WEEKLY;BYDAY=MO,MO;WKST=MO"
        )
        before = Question.objects.get(item=self.item)
        events = Event.objects.count()

        migration.canonical_rules(apps, None)

        self.assertEqual(
            [Todo.objects.get(item=todo).recurrence for todo in todos],
            list(written.values()),
        )
        after = Question.objects.get(item=self.item)
        self.assertEqual(after.rule, "FREQ=WEEKLY;BYDAY=MO")
        self.assertEqual(after.next_at, before.next_at)
        self.assertEqual(Event.objects.count(), events)
