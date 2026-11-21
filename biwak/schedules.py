"""Schedules as RRULE strings (specs/todos.md), used by recurring to-dos and
check-ins.

A rule is an RFC 5545 RRULE without ``DTSTART``, ``COUNT`` and ``UNTIL``
(ends are the business of whoever uses the rule: a to-do's end date and
count), at most daily. Dates are calendar dates in the installation's time
zone; there are no times of day here (check-ins add theirs), so daylight
saving time never moves a date.

Presets build a rule from an anchor date (a to-do's due date): "every
week" repeats on the anchor's weekday. Days which don't exist in every
month (the 31st, 29 February) fall on the last day instead of skipping
months.
"""

import datetime as dt
import functools
from zoneinfo import ZoneInfo

from dateutil import rrule
from django.conf import settings
from django.contrib.humanize.templatetags.humanize import ordinal
from django.utils import timezone
from django.utils.dates import MONTHS
from django.utils.translation import gettext, gettext_lazy as _, ngettext


class InvalidRule(ValueError):
    """A rule we can't use. ``errors`` has a message per field of the rule
    widget (``build_rule``), empty for everything else"""

    def __init__(self, message="", errors=None):
        self.errors = errors or {}
        if not message and self.errors:
            message = " ".join(str(m) for m in self.errors.values())
        super().__init__(message)


DAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
DAY_NAMES = [
    _("Monday"),
    _("Tuesday"),
    _("Wednesday"),
    _("Thursday"),
    _("Friday"),
    _("Saturday"),
    _("Sunday"),
]
WEEKDAYS = "MO,TU,WE,TH,FR"
ORDINALS = {
    1: _("first"),
    2: _("second"),
    3: _("third"),
    4: _("fourth"),
    -1: _("last"),
}
FREQUENCIES = {"DAILY", "WEEKLY", "MONTHLY", "YEARLY"}
# Parts we understand and take responsibility for
PARTS = {
    "FREQ",
    "INTERVAL",
    "BYDAY",
    "BYMONTHDAY",
    "BYMONTH",
    "BYSETPOS",
    "WKST",
}
# The longest interval: the rule widget's maximum too
MAX_INTERVAL = 99


def _tz(tz=None):
    return tz or ZoneInfo(settings.TIME_ZONE)


def _parts(rule):
    parts = {}
    for part in rule.split(";"):
        name, sep, value = part.partition("=")
        if not sep or not value or name in parts:
            raise InvalidRule(_("Not a valid schedule: %(rule)s") % {"rule": rule})
        parts[name] = value
    return parts


def _is_number(value):
    return value.removeprefix("-").removeprefix("+").isdecimal()


def _check_numbers(parts):
    """dateutil loops forever for ``INTERVAL=0``, fails for negative ones
    and reads a day 0 as every day"""
    interval = parts.get("INTERVAL", "1")
    if not (interval.isdecimal() and 1 <= int(interval) <= MAX_INTERVAL):
        raise InvalidRule(
            _("The interval is a number from 1 to %(max)s.") % {"max": MAX_INTERVAL}
        )
    for name in ["BYMONTHDAY", "BYSETPOS"]:
        if name in parts and not all(
            _is_number(value) and int(value) != 0 for value in parts[name].split(",")
        ):
            raise InvalidRule(
                _("Not a valid schedule: %(rule)s") % {"rule": f"{name}={parts[name]}"}
            )


def validate(rule):
    """The rule normalized (upper case, without ``RRULE:``); raises
    ``InvalidRule`` for anything we can't use: unknown or unsupported
    parts, intervals shorter than a day or longer than ``MAX_INTERVAL``,
    ``COUNT``/``UNTIL``/``DTSTART``, rules without a date or with only
    one"""
    rule = (rule or "").strip().removeprefix("RRULE:").removeprefix("rrule:")
    rule = rule.strip().upper()
    if not rule:
        raise InvalidRule(_("The schedule is empty."))
    if len(rule) > 200:
        raise InvalidRule(_("The schedule is too long."))
    parts = _parts(rule)
    if parts.get("FREQ") not in FREQUENCIES:
        raise InvalidRule(
            _("The schedule needs FREQ=DAILY, WEEKLY, MONTHLY or YEARLY.")
        )
    if unknown := set(parts) - PARTS:
        raise InvalidRule(
            _("Not supported in a schedule: %(parts)s. Ends are set separately.")
            % {"parts": ", ".join(sorted(unknown))}
        )
    _check_numbers(parts)
    try:
        parsed = rrule.rrulestr(rule, dtstart=dt.datetime(2028, 1, 1))
        first = parsed.after(dt.datetime(2028, 1, 1), inc=True)
        second = first and parsed.after(first)
    except (ValueError, TypeError, KeyError) as exc:
        raise InvalidRule(_("Not a valid schedule: %(rule)s") % {"rule": rule}) from exc
    if first is None or second is None:
        raise InvalidRule(_("The schedule never produces a date."))
    return rule


def next_date(rule, after, tz=None, *, anchor=None):
    """The first date of the rule after the date ``after`` (a datetime is
    taken as the date in ``tz``, default ``TIME_ZONE``); ``None`` when
    there's none. ``anchor`` is the date the rule starts counting from
    (default ``after``): "every two weeks" depends on it, a to-do's due
    date keeps the phase. A stored rule which isn't valid (any more)
    produces no date: no next to-do, no next check-in."""
    if isinstance(after, dt.datetime):
        after = (
            timezone.localtime(after, _tz(tz)).date() if after.tzinfo else after.date()
        )
    anchor = anchor or after
    start = dt.datetime.combine(anchor, dt.time())
    try:
        rule = validate(rule)
    except InvalidRule:
        return None
    parsed = rrule.rrulestr(rule, dtstart=start)
    found = parsed.after(dt.datetime.combine(after, dt.time.max))
    return found.date() if found else None


def today(tz=None):
    return timezone.localtime(timezone.now(), _tz(tz)).date()


# Presets ----------------------------------------------------------------


def _clamped(day):
    """A day of the month; the 29th to 31st fall on the last day of shorter
    months (the presets and the widget)"""
    if day <= 28:
        return f"BYMONTHDAY={day}"
    return f"BYMONTHDAY={','.join(str(d) for d in range(28, day + 1))};BYSETPOS=-1"


def _weekly(anchor, interval=1):
    interval_part = f";INTERVAL={interval}" if interval > 1 else ""
    return f"FREQ=WEEKLY{interval_part};BYDAY={DAYS[anchor.weekday()]}"


def _yearly(anchor):
    if (anchor.month, anchor.day) == (2, 29):
        return "FREQ=YEARLY;BYMONTH=2;BYMONTHDAY=28,29;BYSETPOS=-1"
    return f"FREQ=YEARLY;BYMONTH={anchor.month};BYMONTHDAY={anchor.day}"


PRESETS = {
    "weekdays": (
        _("Every weekday"),
        lambda anchor: f"FREQ=WEEKLY;BYDAY={WEEKDAYS}",
    ),
    "weekly": (_("Every week"), _weekly),
    "biweekly": (_("Every two weeks"), lambda anchor: _weekly(anchor, 2)),
    "monthly": (
        _("Every month"),
        lambda anchor: f"FREQ=MONTHLY;{_clamped(anchor.day)}",
    ),
    "monthly-first": (
        _("The first weekday of every month"),
        lambda anchor: f"FREQ=MONTHLY;BYDAY={DAYS[anchor.weekday()]};BYSETPOS=1",
    ),
    "monthly-last": (
        _("The last weekday of every month"),
        lambda anchor: f"FREQ=MONTHLY;BYDAY={DAYS[anchor.weekday()]};BYSETPOS=-1",
    ),
    "quarterly": (
        _("Every three months"),
        lambda anchor: f"FREQ=MONTHLY;INTERVAL=3;{_clamped(anchor.day)}",
    ),
    "yearly": (_("Every year"), _yearly),
}
CUSTOM = "custom"


def from_preset(key, anchor):
    """The rule of a preset, counting from the date ``anchor``"""
    try:
        return PRESETS[key][1](anchor)
    except KeyError:
        raise InvalidRule(_("Unknown schedule: %(key)s") % {"key": key}) from None


def resolve(value, anchor):
    """A preset name or an RRULE as a valid rule (the API and the CLI);
    empty for no schedule"""
    value = (value or "").strip()
    if not value:
        return ""
    if value.lower() in PRESETS:
        return from_preset(value.lower(), anchor)
    return validate(value)


@functools.cache
def _preset_rules():
    # Every day of a leap year as the anchor covers all shapes
    first = dt.date(2028, 1, 1)
    days = [first + dt.timedelta(days=n) for n in range(366)]
    return {build(day): key for key, (_label, build) in PRESETS.items() for day in days}


def preset_of(rule):
    """The preset a rule is the result of (for whatever anchor), else
    ``"custom"``; ``""`` for no rule"""
    if not rule:
        return ""
    return _preset_rules().get(rule, CUSTOM)


# The rule widget (specs/rule-widget.md) ---------------------------------
#
# ``rule_fields()`` and ``build_rule()`` are the only code which knows how
# the widget's fields map to RRULE parts.

FREQUENCY_FIELDS = {
    "daily": "DAILY",
    "weekly": "WEEKLY",
    "monthly": "MONTHLY",
    "yearly": "YEARLY",
}
ORDINAL_VALUES = [1, 2, 3, 4, -1]
WORKING_DAY = "WD"


def default_fields(anchor, frequency=""):
    """The widget's fields for a new rule: everything on the anchor's
    weekday, day and date"""
    nth = (anchor.day - 1) // 7 + 1
    return {
        "frequency": frequency,
        "interval": 1,
        "weekdays": [DAYS[anchor.weekday()]],
        "monthly": "day",
        "month_day": anchor.day,
        "ordinal": nth if nth in ORDINAL_VALUES else -1,
        "weekday": DAYS[anchor.weekday()],
        "year_month": anchor.month,
        "year_day": anchor.day,
    }


def _int(value, low, high):
    try:
        number = int(str(value).strip())
    except TypeError, ValueError:
        return None
    return number if low <= number <= high else None


def _build_weekly(fields, errors):
    days = fields.get("weekdays") or []
    if isinstance(days, str):
        days = [days]
    if not days or not set(days) <= set(DAYS):
        errors["weekdays"] = _("Choose at least one weekday.")
        return ""
    return ";BYDAY=" + ",".join(d for d in DAYS if d in days)


def _build_monthly(fields, errors):
    match fields.get("monthly"):
        case "nth":
            ordinal = _int(fields.get("ordinal"), -1, 4)
            weekday = fields.get("weekday")
            if ordinal not in ORDINAL_VALUES:
                errors["ordinal"] = _("Choose first, second, third, fourth or last.")
            if weekday != WORKING_DAY and weekday not in DAYS:
                errors["weekday"] = _("Choose a weekday or working day.")
            if errors:
                return ""
            byday = WEEKDAYS if weekday == WORKING_DAY else weekday
            return f";BYDAY={byday};BYSETPOS={ordinal}"
        case "day":
            day = _int(fields.get("month_day"), 1, 31)
            if day is None:
                errors["month_day"] = _("Enter a day from 1 to 31.")
                return ""
            return ";" + _clamped(day)
    errors["monthly"] = _("Choose a day or a weekday.")
    return ""


def _build_yearly(fields, errors):
    month = _int(fields.get("year_month"), 1, 12)
    day = _int(fields.get("year_day"), 1, 31)
    if month is None:
        errors["year_month"] = _("Choose a month.")
    if day is None:
        errors["year_day"] = _("Enter a day from 1 to 31.")
    if errors:
        return ""
    if (month, day) == (2, 29):
        return ";BYMONTH=2;BYMONTHDAY=28,29;BYSETPOS=-1"
    return f";BYMONTH={month};BYMONTHDAY={day}"


def build_rule(fields):
    """The normalized rule for the widget's fields (``rule_fields()``'s
    keys, values as posted); ``""`` without a frequency. Only the fields
    of the chosen frequency count. Raises ``InvalidRule`` with a message
    per field in ``errors``."""
    frequency = str(fields.get("frequency") or "")
    if not frequency:
        return ""
    if frequency not in FREQUENCY_FIELDS:
        raise InvalidRule(errors={"frequency": _("Choose how often it repeats.")})
    errors = {}
    interval = _int(fields.get("interval"), 1, MAX_INTERVAL)
    if interval is None:
        errors["interval"] = _("Enter a number from 1 to %(max)s.") % {
            "max": MAX_INTERVAL
        }
    head = f"FREQ={FREQUENCY_FIELDS[frequency]}"
    if interval and interval > 1:
        head += f";INTERVAL={interval}"
    builder = {
        "weekly": _build_weekly,
        "monthly": _build_monthly,
        "yearly": _build_yearly,
    }.get(frequency)
    tail = builder(fields, errors) if builder else ""
    if errors:
        raise InvalidRule(errors=errors)
    try:
        return validate(head + tail)
    except InvalidRule:
        # Only 30 and 31 February, 31 April and the like never happen
        raise InvalidRule(errors={"year_day": _("This date doesn't exist.")}) from None


def _canonical(rule):
    parts = _parts(rule)
    if parts.get("INTERVAL") == "1":
        del parts["INTERVAL"]
    if parts.get("WKST") == "MO":
        del parts["WKST"]
    if "BYDAY" in parts:
        days = parts["BYDAY"].split(",")
        parts["BYDAY"] = ",".join(
            sorted(days, key=lambda d: DAYS.index(d) if d in DAYS else 99)
        )
    return sorted(parts.items())


def same_rule(a, b):
    """Whether two valid rules are the same apart from how they're written
    (order of days, the default interval and week start)"""
    return _canonical(a) == _canonical(b)


def _guess_fields(parts):
    interval = _int(parts.get("INTERVAL", "1"), 1, MAX_INTERVAL)
    fields = {"interval": interval}
    days = parts["BYDAY"].split(",") if "BYDAY" in parts else []
    monthdays = parts["BYMONTHDAY"].split(",") if "BYMONTHDAY" in parts else []
    setpos = parts.get("BYSETPOS", "")
    match parts["FREQ"]:
        case "DAILY":
            fields["frequency"] = "daily"
        case "WEEKLY":
            fields |= {"frequency": "weekly", "weekdays": days}
        case "MONTHLY":
            fields["frequency"] = "monthly"
            if days:
                fields |= {
                    "monthly": "nth",
                    "ordinal": int(setpos),
                    "weekday": WORKING_DAY if days == WEEKDAYS.split(",") else days[0],
                }
            else:
                fields |= {"monthly": "day", "month_day": _day_of(monthdays, setpos)}
        case "YEARLY":
            fields |= {
                "frequency": "yearly",
                "year_month": int(parts["BYMONTH"]),
                "year_day": _day_of(monthdays, setpos),
            }
    return fields


def _day_of(monthdays, setpos):
    """The day of ``BYMONTHDAY=5`` or ``BYMONTHDAY=28,29,30;BYSETPOS=-1``"""
    if setpos:
        return int(monthdays[-1])
    return int(monthdays[0])


def rule_fields(rule):
    """The widget's fields for the rule, or ``None`` if the widget can't
    show it. What's returned always builds the same rule again
    (``build_rule(rule_fields(rule)) == rule``, normalized): a rule the
    widget would change is not shown, so that saving a form never
    rewrites it."""
    if not rule:
        return {"frequency": ""}
    try:
        rule = validate(rule)
        fields = _guess_fields(_parts(rule))
        if _canonical(build_rule(fields)) == _canonical(rule):
            return fields
    except InvalidRule, ValueError, KeyError, IndexError:
        pass
    return None


# Describing -------------------------------------------------------------
#
# Every text goes through gettext (whole phrases with placeholders, so
# that a translation can order them); month names and ordinal numbers come
# from Django's catalogs.


def _ordinal(n):
    if n in ORDINALS:
        return str(ORDINALS[n])
    return ordinal(n)


def _every(interval, unit):
    texts = {
        "day": lambda: ngettext("every day", "every %(n)s days", interval),
        "week": lambda: ngettext("every week", "every %(n)s weeks", interval),
        "month": lambda: ngettext("every month", "every %(n)s months", interval),
        "year": lambda: ngettext("every year", "every %(n)s years", interval),
    }
    return texts[unit]() % {"n": interval}


def _describe_weekly(interval, days, parts):
    names = {day: str(DAY_NAMES[i]) for i, day in enumerate(DAYS)}
    if parts.keys() - {"FREQ", "INTERVAL", "BYDAY", "WKST"}:
        return None
    if not days:
        return _every(interval, "week")
    if not all(day in names for day in days):
        return None
    if days == WEEKDAYS.split(","):
        if interval == 1:
            return gettext("every weekday")
        return gettext("%(every)s on weekdays") % {"every": _every(interval, "week")}
    listed = ", ".join(names[day] for day in days)
    if interval == 1:
        return gettext("every %(days)s") % {"days": listed}
    if len(days) == 1 and interval == 2:
        return gettext("every other %(day)s") % {"day": listed}
    return gettext("%(every)s on %(days)s") % {
        "every": _every(interval, "week"),
        "days": listed,
    }


def _describe_monthly(interval, days, monthdays, parts):
    names = {day: str(DAY_NAMES[i]) for i, day in enumerate(DAYS)}
    month = _every(interval, "month")
    setpos = parts.get("BYSETPOS", "")
    if parts.keys() - {"FREQ", "INTERVAL", "BYDAY", "BYMONTHDAY", "BYSETPOS", "WKST"}:
        return None
    nth = setpos.lstrip("-").isdigit() and int(setpos) in ORDINALS
    if len(days) == 1 and days[0] in names and nth:
        return gettext("the %(nth)s %(day)s of %(every)s") % {
            "nth": _ordinal(int(setpos)),
            "day": names[days[0]],
            "every": month,
        }
    if days == WEEKDAYS.split(",") and nth:
        return gettext("the %(nth)s working day of %(every)s") % {
            "nth": _ordinal(int(setpos)),
            "every": month,
        }
    if len(monthdays) == 1 and not days and not setpos:
        return gettext("the %(day)s of %(every)s") % {
            "day": _ordinal(int(monthdays[0])),
            "every": month,
        }
    if monthdays and not days and setpos == "-1":
        last = int(monthdays[-1])
        if monthdays == [str(d) for d in range(28, last + 1)]:
            return gettext("the %(day)s (or the last day) of %(every)s") % {
                "day": _ordinal(last),
                "every": month,
            }
    return None


def _describe_yearly(interval, parts, monthdays):
    month_number = parts.get("BYMONTH", "")
    setpos = parts.get("BYSETPOS")
    year = _every(interval, "year")
    if parts.keys() - {
        "FREQ",
        "INTERVAL",
        "BYMONTH",
        "BYMONTHDAY",
        "BYSETPOS",
    }:
        return None
    if not (month_number.isdigit() and 1 <= int(month_number) <= 12):
        return None
    month_name = str(MONTHS[int(month_number)])
    if len(monthdays) == 1 and not setpos:
        return gettext("%(every)s on %(month)s %(day)s") % {
            "every": year,
            "month": month_name,
            "day": monthdays[0],
        }
    if monthdays == ["28", "29"] and setpos == "-1":
        return gettext("%(every)s on %(month)s 29 (or the last day)") % {
            "every": year,
            "month": month_name,
        }
    return None


def describe(rule):
    """A short text: "every Monday", "the first Monday of every month";
    unusual rules show the rule itself. In the active language."""
    if not rule:
        return ""
    parts = _parts(rule)
    interval = (
        int(parts.get("INTERVAL", "1")) if parts.get("INTERVAL", "1").isdigit() else 0
    )
    days = parts["BYDAY"].split(",") if "BYDAY" in parts else []
    monthdays = parts["BYMONTHDAY"].split(",") if "BYMONTHDAY" in parts else []
    text = None
    match parts["FREQ"]:
        case "DAILY" if (
            not days and not monthdays and parts.keys() <= {"FREQ", "INTERVAL"}
        ):
            text = _every(interval, "day")
        case "WEEKLY":
            text = _describe_weekly(interval, days, parts)
        case "MONTHLY":
            text = _describe_monthly(interval, days, monthdays, parts)
        case "YEARLY":
            text = _describe_yearly(interval, parts, monthdays)
    if text and interval:
        return text
    return gettext("custom schedule (%(rule)s)") % {"rule": rule}
