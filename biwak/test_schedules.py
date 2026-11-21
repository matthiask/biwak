import datetime as dt
import itertools
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
            # INTERVAL=0 made dateutil loop forever, -1 raise, a huge one
            # produce a single date
            "FREQ=DAILY;INTERVAL=0",
            "FREQ=DAILY;INTERVAL=-1",
            "FREQ=DAILY;INTERVAL=x",
            "FREQ=DAILY;INTERVAL=100",
            "FREQ=DAILY;INTERVAL=99999999999",
            # dateutil reads 0 as "every day"
            "FREQ=MONTHLY;BYMONTHDAY=0",
            "FREQ=MONTHLY;BYMONTHDAY=0,5",
            "FREQ=MONTHLY;BYDAY=MO;BYSETPOS=0",
        ]:
            with self.subTest(rule=rule), self.assertRaises(InvalidRule):
                validate(rule)

    def test_intervals_up_to_the_widgets_maximum(self):
        self.assertEqual(validate("FREQ=WEEKLY;INTERVAL=99"), "FREQ=WEEKLY;INTERVAL=99")


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
        self.assertIsNone(
            next_date("FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=30", d("2026-01-01"))
        )

    def test_a_stored_rule_which_isnt_valid_has_no_next_date(self):
        """Rules stored before validate() refused them (completing a to-do,
        asking a check-in): no date instead of a hang or an error"""
        for rule in ["FREQ=DAILY;INTERVAL=0", "FREQ=DAILY;INTERVAL=-1"]:
            with self.subTest(rule=rule):
                self.assertIsNone(next_date(rule, d("2026-01-01")))


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

    def test_describe_working_day_positions(self):
        self.assertEqual(
            describe("FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1"),
            "the last working day of every month",
        )
        rule = "FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-2"
        self.assertEqual(describe(rule), f"custom schedule ({rule})")
        rule = "FREQ=MONTHLY;BYDAY=MO;BYSETPOS=-2"
        self.assertEqual(describe(rule), f"custom schedule ({rule})")


def all_widget_fields():
    """Every rule the widget can build, as its fields"""
    for interval in [1, 2, 3, 12, 99]:
        yield {"frequency": "daily", "interval": interval}
        for size in range(1, 8):
            for days in itertools.combinations(schedules.DAYS, size):
                yield {
                    "frequency": "weekly",
                    "interval": interval,
                    "weekdays": list(days),
                }
        for day in range(1, 32):
            yield {
                "frequency": "monthly",
                "interval": interval,
                "monthly": "day",
                "month_day": day,
            }
        for ordinal in schedules.ORDINAL_VALUES:
            for weekday in [*schedules.DAYS, schedules.WORKING_DAY]:
                yield {
                    "frequency": "monthly",
                    "interval": interval,
                    "monthly": "nth",
                    "ordinal": ordinal,
                    "weekday": weekday,
                }
    for interval in [1, 2]:
        for offset in range(366):
            day = d("2028-01-01") + dt.timedelta(days=offset)
            yield {
                "frequency": "yearly",
                "interval": interval,
                "year_month": day.month,
                "year_day": day.day,
            }


class RuleFieldsTest(SimpleTestCase):
    def test_every_rule_the_widget_builds_round_trips(self):
        count = 0
        for fields in all_widget_fields():
            with self.subTest(fields=fields):
                rule = schedules.build_rule(fields)
                self.assertEqual(validate(rule), rule)
                shown = schedules.rule_fields(rule)
                self.assertIsNotNone(shown)
                self.assertEqual(schedules.build_rule(shown), rule)
                self.assertEqual({k: shown[k] for k in fields}, fields)
                self.assertFalse(describe(rule).startswith("custom"), rule)
            count += 1
        self.assertGreater(count, 1700)

    def test_every_preset_round_trips(self):
        day = d("2028-01-01")
        for offset in range(366):
            for key in schedules.PRESETS:
                rule = schedules.from_preset(key, day + dt.timedelta(days=offset))
                with self.subTest(rule=rule):
                    shown = schedules.rule_fields(rule)
                    self.assertIsNotNone(shown, rule)
                    self.assertEqual(schedules.build_rule(shown), rule)

    def test_equivalent_spellings_show_and_normalize(self):
        for rule, normal in [
            ("FREQ=WEEKLY;BYDAY=FR,MO", "FREQ=WEEKLY;BYDAY=MO,FR"),
            ("BYDAY=MO;FREQ=WEEKLY;INTERVAL=1", "FREQ=WEEKLY;BYDAY=MO"),
            ("freq=weekly;byday=mo;wkst=mo", "FREQ=WEEKLY;BYDAY=MO"),
        ]:
            with self.subTest(rule=rule):
                shown = schedules.rule_fields(rule)
                self.assertEqual(schedules.build_rule(shown), normal)

    def test_rules_the_widget_cant_show(self):
        for rule in [
            "FREQ=WEEKLY",  # the day comes from the first date
            "FREQ=WEEKLY;WKST=SU;BYDAY=MO,TU",
            "FREQ=DAILY;INTERVAL=100",
            "FREQ=DAILY;BYDAY=MO",
            "FREQ=MONTHLY;BYMONTHDAY=1,15",
            "FREQ=MONTHLY;BYMONTHDAY=-1",
            "FREQ=MONTHLY;BYMONTHDAY=5;BYSETPOS=1",
            "FREQ=MONTHLY;BYDAY=MO,WE;BYSETPOS=1",
            "FREQ=MONTHLY;BYDAY=MO;BYSETPOS=5",
            "FREQ=MONTHLY;BYDAY=MO;BYSETPOS=2;BYMONTH=3",
            "FREQ=MONTHLY;BYDAY=MO",
            "FREQ=MONTHLY",
            "FREQ=YEARLY",
            "FREQ=YEARLY;BYMONTH=1,7;BYMONTHDAY=1",
            "FREQ=YEARLY;BYMONTH=3",
            "FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=29",
            "FREQ=WEEKLY;BYDAY=1MO",
            "FREQ=HOURLY",
            "nonsense",
        ]:
            with self.subTest(rule=rule):
                self.assertIsNone(schedules.rule_fields(rule))

    def test_no_rule(self):
        self.assertEqual(schedules.rule_fields(""), {"frequency": ""})
        self.assertEqual(schedules.build_rule({"frequency": ""}), "")
        self.assertEqual(schedules.build_rule({}), "")

    def test_clamped_days_and_leap_day(self):
        self.assertEqual(
            schedules.build_rule({
                "frequency": "monthly",
                "interval": 1,
                "monthly": "day",
                "month_day": 30,
            }),
            "FREQ=MONTHLY;BYMONTHDAY=28,29,30;BYSETPOS=-1",
        )
        self.assertEqual(
            schedules.build_rule({
                "frequency": "yearly",
                "interval": 1,
                "year_month": 2,
                "year_day": 29,
            }),
            "FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=28,29;BYSETPOS=-1",
        )

    def test_values_as_posted(self):
        self.assertEqual(
            schedules.build_rule({
                "frequency": "monthly",
                "interval": " 2 ",
                "monthly": "nth",
                "ordinal": "-1",
                "weekday": "WD",
            }),
            "FREQ=MONTHLY;INTERVAL=2;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1",
        )

    def errors(self, **fields):
        with self.assertRaises(InvalidRule) as caught:
            schedules.build_rule(fields)
        return caught.exception.errors

    def test_a_message_per_field(self):
        ok = {"frequency": "weekly", "interval": 1, "weekdays": ["MO"]}
        self.assertEqual(
            self.errors(frequency="hourly"),
            {"frequency": "Choose how often it repeats."} | {},
        )
        for interval in ["", "0", "100", "x", "-1", "1.5"]:
            self.assertEqual(
                list(self.errors(**ok | {"interval": interval})), ["interval"]
            )
        self.assertEqual(list(self.errors(**ok | {"weekdays": []})), ["weekdays"])
        self.assertEqual(list(self.errors(**ok | {"weekdays": ["XX"]})), ["weekdays"])
        monthly = {"frequency": "monthly", "interval": 1}
        self.assertEqual(list(self.errors(**monthly)), ["monthly"])
        self.assertEqual(
            list(self.errors(**monthly | {"monthly": "day", "month_day": "32"})),
            ["month_day"],
        )
        self.assertEqual(
            list(
                self.errors(
                    **monthly | {"monthly": "nth", "ordinal": 5, "weekday": "XX"}
                )
            ),
            ["ordinal", "weekday"],
        )
        yearly = {"frequency": "yearly", "interval": 1}
        self.assertEqual(
            list(self.errors(**yearly | {"year_month": "13", "year_day": "0"})),
            ["year_month", "year_day"],
        )
        for month, day in [(2, 30), (2, 31), (4, 31)]:
            self.assertEqual(
                list(self.errors(**yearly | {"year_month": month, "year_day": day})),
                ["year_day"],
            )
        # Several at once, and the message is readable
        errors = self.errors(frequency="weekly", interval="x")
        self.assertEqual(list(errors), ["interval", "weekdays"])

    def test_defaults_from_the_anchor(self):
        fields = schedules.default_fields(d("2026-11-20"), "weekly")
        self.assertEqual(
            (
                fields["weekdays"],
                fields["month_day"],
                fields["ordinal"],
                fields["weekday"],
            ),
            (["FR"], 20, 3, "FR"),
        )
        self.assertEqual((fields["year_month"], fields["year_day"]), (11, 20))
        # The fifth Friday is the last
        self.assertEqual(schedules.default_fields(d("2026-11-27"))["ordinal"], 4)
        self.assertEqual(schedules.default_fields(d("2026-10-30"))["ordinal"], -1)
        for anchor in [d("2028-01-01") + dt.timedelta(days=n) for n in range(366)]:
            for frequency in schedules.FREQUENCY_FIELDS:
                schedules.build_rule(schedules.default_fields(anchor, frequency))

    def test_describing_what_the_widget_builds(self):
        for fields, text in [
            (
                {"frequency": "weekly", "interval": 3, "weekdays": ["MO", "FR"]},
                "every 3 weeks on Monday, Friday",
            ),
            (
                {
                    "frequency": "weekly",
                    "interval": 2,
                    "weekdays": ["MO", "TU", "WE", "TH", "FR"],
                },
                "every 2 weeks on weekdays",
            ),
            (
                {"frequency": "weekly", "interval": 2, "weekdays": ["MO"]},
                "every other Monday",
            ),
            (
                {
                    "frequency": "monthly",
                    "interval": 1,
                    "monthly": "nth",
                    "ordinal": -1,
                    "weekday": "WD",
                },
                "the last working day of every month",
            ),
            (
                {
                    "frequency": "monthly",
                    "interval": 1,
                    "monthly": "nth",
                    "ordinal": 2,
                    "weekday": "TU",
                },
                "the second Tuesday of every month",
            ),
            (
                {"frequency": "yearly", "interval": 2, "year_month": 3, "year_day": 5},
                "every 2 years on March 5",
            ),
        ]:
            with self.subTest(text=text):
                self.assertEqual(describe(schedules.build_rule(fields)), text)
