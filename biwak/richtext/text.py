"""Plain text helpers"""

import datetime as dt
import re

from django.utils import timezone
from django.utils.timesince import timesince
from django.utils.translation import gettext, npgettext_lazy


_BREAKS = re.compile(r"\r\n?")


def line_breaks(text):
    r"""``\n`` for every line break: browsers send a textarea's as ``\r\n``,
    and the live editor (CodeMirror) counts a line break as one character
    where Yjs would count two (specs/collaboration.md)"""
    return _BREAKS.sub("\n", text) if text else text


# "vor 2 Tagen": after "vor" German needs the dative, which Django's own
# units ("2 Tage") aren't, so the units of "… ago" are entries of their own
# (specs/languages.md)
AGO_UNITS = {
    "year": npgettext_lazy("ago", "%(num)d year", "%(num)d years", "num"),
    "month": npgettext_lazy("ago", "%(num)d month", "%(num)d months", "num"),
    "week": npgettext_lazy("ago", "%(num)d week", "%(num)d weeks", "num"),
    "day": npgettext_lazy("ago", "%(num)d day", "%(num)d days", "num"),
    "hour": npgettext_lazy("ago", "%(num)d hour", "%(num)d hours", "num"),
    "minute": npgettext_lazy("ago", "%(num)d minute", "%(num)d minutes", "num"),
}


def ago(when, *, now=None, just_now=None):
    """How long ago, one unit: "13 hours ago", not "13 hours, 37 minutes
    ago" (decided 2026-11-22); under a minute ``just_now``, "just now" by
    default"""
    now = now or timezone.now()
    if now - when < dt.timedelta(minutes=1):
        return just_now or gettext("just now")
    return gettext("%(time)s ago") % {
        "time": timesince(when, now, depth=1, time_strings=AGO_UNITS)
    }


# Moments within this show how long ago, older ones their date (decided
# 2026-11-22, specs/ui.md)
RELATIVE = dt.timedelta(days=7)


def moment(when, *, now=None, on=False):
    """A past moment, one rule everywhere on pages: "3 hours ago" within
    seven days, then the date ("12 Nov 2026"), "on 12 Nov 2026" with ``on``
    for sentences ("completed on …", "completed 3 days ago")"""
    from biwak.formats import format_date

    now = now or timezone.now()
    if now - when < RELATIVE:
        return ago(when, now=now)
    date = format_date(timezone.localtime(when), "SHORT_DATE_FORMAT")
    return gettext("on %(date)s") % {"date": date} if on else date
