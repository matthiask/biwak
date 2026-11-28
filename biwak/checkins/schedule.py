"""When a question is asked (specs/checkins.md)

A question is asked on the dates its rule produces (``biwak.schedules``),
at its time of day in the installation's time zone (``TIME_ZONE``, the
only one, decided 2026-11-22): "09:00 Europe/Zurich" stays 09:00 on the
wall clock across daylight saving time changes, so in UTC it moves by an
hour twice a year. Dates are calendar dates in that time zone. The
functions below take the zone, the questions' are called with
``time_zone()``.

Two times of day are odd on the days the clocks change:

- one which doesn't exist (02:30 when the clocks go forward from 02:00 to
  03:00) is asked an hour later, at 03:30, the same as the rest of the
  world's calendars do;
- one which happens twice (02:30 when they go back from 03:00 to 02:00)
  is asked the first time only: one date is one occurrence.
"""

import datetime as dt
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.utils.translation import gettext

from biwak import schedules


def time_zone():
    """The installation's time zone, the one questions are asked in"""
    return settings.TIME_ZONE


def zone(name):
    """The time zone; ``ValueError`` for a name we don't know"""
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        raise ValueError(
            gettext("Unknown time zone: %(name)s") % {"name": name}
        ) from exc


def fire_at(day, time_of_day, time_zone):
    """The moment (UTC) of ``time_of_day`` on ``day`` in the time zone"""
    local = dt.datetime.combine(day, time_of_day.replace(tzinfo=None))
    # fold=0: the first of two equal wall clock times; a time that doesn't
    # exist is read with the offset from before the change
    return local.replace(tzinfo=zone(time_zone), fold=0).astimezone(dt.UTC)


def local_date(moment, time_zone):
    return moment.astimezone(zone(time_zone)).date()


def next_occurrence(*, rule, starts_on, time_of_day, time_zone, after):
    """The first date the rule asks strictly after ``after`` and its moment
    (UTC), as ``(date, moment)``, or None. The date is the rule's: the
    moment of a time in a gap just before midnight is on the next day."""
    # Two days before ``after``'s date: next_date() is strictly after its
    # date, today's time of day may still be ahead, and yesterday's may be
    # today (a time in a gap before midnight)
    day = local_date(after, time_zone) - dt.timedelta(days=2)
    # Three dates are enough: the third is after ``after`` whatever the
    # clocks did; the guard is only against a rule going nowhere
    for _attempt in range(5):
        day = schedules.next_date(rule, day, anchor=starts_on)
        if day is None:
            return None
        fire = fire_at(day, time_of_day, time_zone)
        if fire > after:
            return day, fire
    return None  # pragma: no cover


def next_occurrence_of(question, *, after):
    return next_occurrence(
        rule=question.rule,
        starts_on=question.starts_on,
        time_of_day=question.time_of_day,
        time_zone=time_zone(),
        after=after,
    )


def next_fire_of(question, *, after):
    found = next_occurrence_of(question, after=after)
    return found and found[1]


def latest_due(question, *, first, now):
    """The last date up to ``now`` the rule asks and its moment, as
    ``(date, moment)``, counting on from ``first`` (the stored next time,
    one of the rule's moments): after downtime, a question is asked once,
    for the latest date, not for every date missed. (An ``Occurrence`` is
    what's created for it: ``operations.latest_occurrence()``.) None when
    the rule gives no date (a stored rule which isn't valid any more)."""
    latest = next_occurrence_of(question, after=first - dt.timedelta(microseconds=1))
    if latest is None:
        return None
    while (following := next_occurrence_of(question, after=latest[1])) and (
        following[1] <= now
    ):
        latest = following
    return latest
