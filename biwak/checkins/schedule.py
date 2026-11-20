"""When a question is asked (specs/checkins.md)

A question is asked on the dates its rule produces (``biwak.schedules``),
at its time of day in its own time zone: "09:00 Europe/Zurich" stays 09:00
on the wall clock across daylight saving time changes, so in UTC it moves
by an hour twice a year. Dates are calendar dates in that time zone.

Two times of day are odd on the days the clocks change:

- one which doesn't exist (02:30 when the clocks go forward from 02:00 to
  03:00) is asked an hour later, at 03:30, the same as the rest of the
  world's calendars do;
- one which happens twice (02:30 when they go back from 03:00 to 02:00)
  is asked the first time only: one date is one occurrence.
"""

import datetime as dt
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from biwak import schedules


def zone(name):
    """The time zone; ``ValueError`` for a name we don't know"""
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
        raise ValueError(f"Unknown time zone: {name}") from exc


def fire_at(day, time_of_day, time_zone):
    """The moment (UTC) of ``time_of_day`` on ``day`` in the time zone"""
    local = dt.datetime.combine(day, time_of_day.replace(tzinfo=None))
    # fold=0: the first of two equal wall clock times; a time that doesn't
    # exist is read with the offset from before the change
    return local.replace(tzinfo=zone(time_zone), fold=0).astimezone(dt.UTC)


def local_date(moment, time_zone):
    return moment.astimezone(zone(time_zone)).date()


def next_fire(*, rule, starts_on, time_of_day, time_zone, after):
    """The first moment strictly after ``after`` the rule asks, or None"""
    # The day before ``after``'s: next_date() is strictly after its date,
    # and today's time of day may still be ahead
    day = local_date(after, time_zone) - dt.timedelta(days=1)
    # Two dates are enough: the second is after ``after`` whatever the clocks
    # did; the guard is only against a rule going nowhere
    for _attempt in range(4):
        day = schedules.next_date(rule, day, anchor=starts_on)
        if day is None:
            return None
        fire = fire_at(day, time_of_day, time_zone)
        if fire > after:
            return fire
    return None  # pragma: no cover


def next_fire_of(question, *, after):
    return next_fire(
        rule=question.rule,
        starts_on=question.starts_on,
        time_of_day=question.time_of_day,
        time_zone=question.time_zone,
        after=after,
    )


def latest_fire(question, *, first, now):
    """The last moment up to ``now`` the rule asks, counting on from
    ``first`` (the stored next time): after downtime, a question is asked
    once, for the latest date, not for every date missed"""
    latest = first
    while (following := next_fire_of(question, after=latest)) and following <= now:
        latest = following
    return latest
