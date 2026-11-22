"""Dates and times per language (``FORMAT_MODULE_PATH``, specs/languages.md):
"22 Nov 2026" in English, "22. Nov. 2026" in German. Django's names
(``SHORT_DATE_FORMAT``…) and a few of our own (``WEEKDAY_DATE_FORMAT``…),
all through ``format_date()`` and the ``dateformat`` filter."""

from django.utils import dateformat, formats
from django.utils.translation import get_language


def get(name):
    """The active language's format called ``name``"""
    for module in formats.get_format_modules(get_language()):
        if hasattr(module, name):
            return getattr(module, name)
    return formats.get_format(name)


def format_date(value, name):
    """``value`` (a date, or a datetime in local time) in the format ``name``"""
    return dateformat.format(value, get(name))
