import datetime as dt
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from biwak import schedules
from biwak.schedules import InvalidRule, describe, next_date, validate


def d(text):
    return dt.date.fromisoformat(text)


class ValidateTest(SimpleTestCase):
    def test_normalizes(self):
        self.assertEqual(
            validate(" rrule:freq=weekly;byday=mo "), "FREQ=WEEKLY;BYDAY=MO"
        )

    def test_rejects(self):
        for rule in [
            "",
            "nonsense",
            "FREQ=HOURLY",
            "FREQ=WEEKLY;COUNT=3",
            "FREQ=WEEKLY;UNTIL=20300101",
            "FREQ=WEEKLY;BYDAY=XX",
            "FREQ=MONTHLY;BYMONTHDAY=31;BYMONTH=2",
            "FREQ=WEEKLY;FREQ=DAILY",
            "FREQ=" + "X" * 300,
        ]:
            with self.subTest(rule=rule), self.assertRaises(InvalidRule):
                validate(rule)


class NextDateTest(SimpleTestCase):
    def test_weekdays(self):
        rule = schedules.from_preset("weekdays", d("2026-11-20"))
        self.assertEqual(next_date(rule, d("2026-11-20")), d("2026-11-23"))
        self.assertEqual(next_date(rule, d("2026-11-18")), d("2026-11-19"))

    def test_month_end_clamps(self):
        rule = schedules.from_preset("monthly", d("2026-01-31"))
        self.assertEqual(next_date(rule, d("2026-01-31")), d("2026-02-28"))
        self.assertEqual(next_date(rule, d("2026-02-28")), d("2026-03-31"))
        self.assertEqual(next_date(rule, d("2026-03-31")), d("2026-04-30"))
        # Leap year
        self.assertEqual(next_date(rule, d("2028-01-31")), d("2028-02-29"))

    def test_the_thirtieth(self):
        rule = schedules.from_preset("monthly", d("2026-01-30"))
        self.assertEqual(next_date(rule, d("2026-01-30")), d("2026-02-28"))
        self.assertEqual(next_date(rule, d("2026-02-28")), d("2026-03-30"))
        self.assertEqual(next_date(rule, d("2026-03-30")), d("2026-04-30"))

    def test_leap_day(self):
        rule = schedules.from_preset("yearly", d("2028-02-29"))
        self.assertEqual(next_date(rule, d("2028-02-29")), d("2029-02-28"))
        self.assertEqual(next_date(rule, d("2029-02-28")), d("2030-02-28"))
        self.assertEqual(next_date(rule, d("2031-03-01")), d("2032-02-29"))

    def test_last_weekday_of_the_month(self):
        rule = schedules.from_preset("monthly-last", d("2026-11-30"))  # a Monday
        self.assertEqual(rule, "FREQ=MONTHLY;BYDAY=MO;BYSETPOS=-1")
        self.assertEqual(next_date(rule, d("2026-11-30")), d("2026-12-28"))
        # Working days
        rule = "FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1"
        self.assertEqual(next_date(rule, d("2026-10-31")), d("2026-11-30"))
        self.assertEqual(next_date(rule, d("2026-11-30")), d("2026-12-31"))
        self.assertEqual(next_date(rule, d("2026-12-31")), d("2027-01-29"))

    def test_first_weekday_of_the_month(self):
        rule = schedules.from_preset("monthly-first", d("2026-11-02"))
        self.assertEqual(next_date(rule, d("2026-11-02")), d("2026-12-07"))

    def test_every_two_weeks_keeps_the_phase_of_the_anchor(self):
        anchor = d("2026-11-02")
        rule = schedules.from_preset("biweekly", anchor)
        self.assertEqual(
            next_date(rule, d("2026-11-10"), anchor=anchor), d("2026-11-16")
        )
        self.assertEqual(
            next_date(rule, d("2026-11-16"), anchor=anchor), d("2026-11-30")
        )

    def test_quarterly(self):
        rule = schedules.from_preset("quarterly", d("2026-11-30"))
        self.assertEqual(next_date(rule, d("2026-11-30")), d("2027-02-28"))

    def test_time_zone_and_daylight_saving(self):
        zurich = ZoneInfo("Europe/Zurich")
        rule = "FREQ=DAILY"
        # 23:30 UTC on 27 Oct 2026 is already 28 Oct in Zurich (UTC+1 after
        # the change on the 25th)
        late = dt.datetime(2026, 10, 27, 23, 30, tzinfo=dt.UTC)
        self.assertEqual(next_date(rule, late, zurich), d("2026-10-29"))
        self.assertEqual(next_date(rule, late, ZoneInfo("UTC")), d("2026-10-28"))
        # Around the change to winter time: still one date per day
        self.assertEqual(next_date(rule, d("2026-10-25")), d("2026-10-26"))
        night = dt.datetime(2026, 3, 28, 23, 30, tzinfo=dt.UTC)  # 29 March, 00:30 CET
        self.assertEqual(next_date(rule, night, zurich), d("2026-03-30"))
        # Summer time starts that morning: 00:30 CET is 00:30 on the 29th
        night = dt.datetime(2026, 3, 29, 22, 30, tzinfo=dt.UTC)  # 30 March, 00:30 CEST
        self.assertEqual(next_date(rule, night, zurich), d("2026-03-31"))

    def test_rule_without_dates(self):
        # 30 February never exists
        with self.assertRaises(InvalidRule):
            next_date("FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=30", d("2026-01-01"))


class PresetsTest(SimpleTestCase):
    def test_every_preset_is_valid_on_every_day(self):
        day = d("2028-01-01")
        for offset in range(366):
            for key in schedules.PRESETS:
                rule = schedules.from_preset(key, day + dt.timedelta(days=offset))
                self.assertEqual(validate(rule), rule)
                self.assertEqual(schedules.preset_of(rule), key)
                self.assertTrue(describe(rule), rule)
                self.assertFalse(describe(rule).startswith("custom"), rule)

    def test_custom(self):
        self.assertEqual(schedules.preset_of(""), "")
        self.assertEqual(schedules.preset_of("FREQ=DAILY;INTERVAL=3"), "custom")

    def test_resolve(self):
        anchor = d("2026-11-20")
        self.assertEqual(schedules.resolve("weekly", anchor), "FREQ=WEEKLY;BYDAY=FR")
        self.assertEqual(schedules.resolve("FREQ=DAILY", anchor), "FREQ=DAILY")
        self.assertEqual(schedules.resolve("", anchor), "")
        with self.assertRaises(InvalidRule):
            schedules.resolve("sometimes", anchor)

    def test_describe(self):
        for rule, text in [
            ("FREQ=WEEKLY;BYDAY=MO", "every Monday"),
            ("FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR", "every weekday"),
            ("FREQ=WEEKLY;INTERVAL=2;BYDAY=TU", "every other Tuesday"),
            ("FREQ=MONTHLY;BYDAY=MO;BYSETPOS=1", "the first Monday of every month"),
            ("FREQ=MONTHLY;BYDAY=FR;BYSETPOS=-1", "the last Friday of every month"),
            ("FREQ=MONTHLY;BYMONTHDAY=5", "the 5th of every month"),
            (
                "FREQ=MONTHLY;INTERVAL=3;BYMONTHDAY=28,29,30,31;BYSETPOS=-1",
                "the 31st (or the last day) of every 3 months",
            ),
            ("FREQ=YEARLY;BYMONTH=3;BYMONTHDAY=14", "every year on March 14"),
            ("FREQ=DAILY;INTERVAL=3", "every 3 days"),
            (
                "FREQ=WEEKLY;BYDAY=MO;BYMONTH=1",
                "custom schedule (FREQ=WEEKLY;BYDAY=MO;BYMONTH=1)",
            ),
        ]:
            with self.subTest(rule=rule):
                self.assertEqual(describe(rule), text)
        self.assertEqual(describe(""), "")
