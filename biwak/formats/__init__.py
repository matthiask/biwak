"""Dates and times per language (``FORMAT_MODULE_PATH``, specs/languages.md):
"22 Nov 2026" in English, "22. Nov. 2026" in German. Django's names
(``SHORT_DATE_FORMAT``…) and a few of our own (``WEEKDAY_DATE_FORMAT``…),
all through ``format_date()`` and the ``dateformat`` filter."""

from django.utils import dateformat, formats, timezone
from django.utils.translation import get_language


def get(name):
    """The active language's format called ``name``"""
    for module in formats.get_format_modules(get_language()):
        if hasattr(module, name):
            return getattr(module, name)
    return formats.get_format(name)


# The short formats without the year, and theirs with it for a day in
# another year: "17 Nov", but "17 Nov 2024"
WITH_YEAR = {
    "MONTH_DAY_FORMAT": "SHORT_DATE_FORMAT",
    "MONTH_DAY_TIME_FORMAT": "SHORT_DATETIME_FORMAT",
    "SHORT_WEEKDAY_MONTH_DAY_FORMAT": "SHORT_WEEKDAY_DATE_FORMAT",
}


def _format(value, name):
    return dateformat.format(value, get(name))


def with_year(value, name):
    """``name``, or its format with the year when ``value`` isn't in this
    year"""
    if value.year != timezone.localdate().year:
        return WITH_YEAR.get(name, name)
    return name


def format_date(value, name):
    """``value`` (a date, or a datetime in local time) in the format
    ``name``; the short ones without the year get it for another year"""
    return _format(value, with_year(value, name))


# A range's start, by the format of its end: within one month only the day
# ("3–7 Dec"), within one year without the year ("28 Nov – 3 Dec 2026"),
# else in full (specs/start-dates.md); the year on both ends across years
# and at the end in another year, also for formats without it
RANGE_STARTS = {
    "MONTH_DAY_FORMAT": "MONTH_DAY_FORMAT",
    "SHORT_DATE_FORMAT": "MONTH_DAY_FORMAT",
    "SHORT_WEEKDAY_DATE_FORMAT": "SHORT_WEEKDAY_MONTH_DAY_FORMAT",
}


def format_range(start, end, name):
    """``start`` to ``end`` in the format ``name`` (a key of
    ``RANGE_STARTS``): "3–7 Dec", "28 Nov – 3 Dec"; ``end`` alone without
    a ``start`` or when they're the same day"""
    if start is None or start == end:
        return format_date(end, name)
    if start.year != end.year:
        name = WITH_YEAR.get(name, name)
        first = _format(start, name)
    elif start.month == end.month and name in {"MONTH_DAY_FORMAT", "SHORT_DATE_FORMAT"}:
        return f"{_format(start, 'RANGE_DAY_FORMAT')}–{format_date(end, name)}"
    else:
        first = _format(start, RANGE_STARTS[name])
    return f"{first} – {format_date(end, name)}"
