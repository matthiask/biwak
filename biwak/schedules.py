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
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class InvalidRule(ValueError):
    pass


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


def validate(rule):
    """The rule normalized (upper case, without ``RRULE:``); raises
    ``InvalidRule`` for anything we can't use: unknown or unsupported
    parts, intervals shorter than a day, ``COUNT``/``UNTIL``/``DTSTART``,
    rules without any date"""
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
    try:
        parsed = rrule.rrulestr(rule, dtstart=dt.datetime(2028, 1, 1))
        first = parsed.after(dt.datetime(2028, 1, 1), inc=True)
    except (ValueError, TypeError, KeyError) as exc:
        raise InvalidRule(_("Not a valid schedule: %(rule)s") % {"rule": rule}) from exc
    if first is None:
        raise InvalidRule(_("The schedule never produces a date."))
    return rule


def next_date(rule, after, tz=None, *, anchor=None):
    """The first date of the rule after the date ``after`` (a datetime is
    taken as the date in ``tz``, default ``TIME_ZONE``); ``None`` when
    there's none. ``anchor`` is the date the rule starts counting from
    (default ``after``): "every two weeks" depends on it, a to-do's due
    date keeps the phase."""
    if isinstance(after, dt.datetime):
        after = (
            timezone.localtime(after, _tz(tz)).date() if after.tzinfo else after.date()
        )
    anchor = anchor or after
    start = dt.datetime.combine(anchor, dt.time())
    parsed = rrule.rrulestr(validate(rule), dtstart=start)
    found = parsed.after(dt.datetime.combine(after, dt.time.max))
    return found.date() if found else None


def today(tz=None):
    return timezone.localtime(timezone.now(), _tz(tz)).date()


# Presets ----------------------------------------------------------------


def _clamped(day, extra=""):
    """A day of the month; the 29th to 31st fall on the last day of shorter
    months"""
    if day <= 28:
        return f"BYMONTHDAY={day}{extra}"
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


def preset_choices():
    r"""For the forms: ``("", "Doesn't repeat")``, the presets, "custom\""""
    return [
        ("", _("Doesn't repeat")),
        *((key, label) for key, (label, _build) in PRESETS.items()),
        (CUSTOM, _("Custom (RRULE)")),
    ]


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


# Describing -------------------------------------------------------------


def _ordinal(n):
    if n in ORDINALS:
        return str(ORDINALS[n])
    suffix = (
        "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    )
    return f"{n}{suffix}"


def _every(interval, unit):
    return f"every {unit}" if interval == 1 else f"every {interval} {unit}s"


def _describe_weekly(interval, days, parts):
    names = {day: str(DAY_NAMES[i]) for i, day in enumerate(DAYS)}
    if parts.keys() - {"FREQ", "INTERVAL", "BYDAY", "WKST"}:
        return None
    if not days:
        return _every(interval, "week")
    if days == WEEKDAYS.split(","):
        return "every weekday" if interval == 1 else None
    if len(days) == 1 and days[0] in names and interval in {1, 2}:
        other = "" if interval == 1 else "other "
        return f"every {other}{names[days[0]]}"
    if interval == 1 and all(day in names for day in days):
        return "every " + ", ".join(names[day] for day in days)
    return None


def _describe_monthly(interval, days, monthdays, parts):
    names = {day: str(DAY_NAMES[i]) for i, day in enumerate(DAYS)}
    month = _every(interval, "month")
    setpos = parts.get("BYSETPOS", "")
    if parts.keys() - {"FREQ", "INTERVAL", "BYDAY", "BYMONTHDAY", "BYSETPOS", "WKST"}:
        return None
    if len(days) == 1 and days[0] in names and setpos.lstrip("-").isdigit():
        return f"the {_ordinal(int(setpos))} {names[days[0]]} of {month}"
    if days == WEEKDAYS.split(",") and setpos in {"1", "-1"}:
        return f"the {_ordinal(int(setpos))} weekday of {month}"
    if len(monthdays) == 1 and not days and not setpos:
        return f"the {_ordinal(int(monthdays[0]))} of {month}"
    if monthdays and not days and setpos == "-1":
        last = int(monthdays[-1])
        if monthdays == [str(d) for d in range(28, last + 1)]:
            return f"the {_ordinal(last)} (or the last day) of {month}"
    return None


def _describe_yearly(interval, parts, monthdays):
    month_number = parts.get("BYMONTH", "")
    setpos = parts.get("BYSETPOS")
    if interval != 1 or parts.keys() - {
        "FREQ",
        "INTERVAL",
        "BYMONTH",
        "BYMONTHDAY",
        "BYSETPOS",
    }:
        return None
    if not (month_number.isdigit() and 1 <= int(month_number) <= 12):
        return None
    month_name = dt.date(2028, int(month_number), 1).strftime("%B")
    if len(monthdays) == 1 and not setpos:
        return f"every year on {month_name} {monthdays[0]}"
    if monthdays == ["28", "29"] and setpos == "-1":
        return f"every year on {month_name} 29 (or the last day)"
    return None


def describe(rule):
    """A short English text: "every Monday", "the first Monday of every
    month"; unusual rules show the rule itself"""
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
    return text if text and interval else f"custom schedule ({rule})"
