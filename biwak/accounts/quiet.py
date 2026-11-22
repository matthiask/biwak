"""Quiet hours and out of office (specs/quiet-hours.md): when somebody's
notification mails and digests wait, and how being away is shown. One time
zone, the installation's (``TIME_ZONE``, decided 2026-11-22)."""

from django.utils import timezone
from django.utils.formats import date_format
from django.utils.translation import gettext as _


NOTE_LENGTH = 200


def is_away(user, today=None):
    """Away on ``today`` (the installation's date): up to and including
    ``away_until``"""
    today = today or timezone.localdate()
    return user.away_until is not None and user.away_until >= today


def in_working_time(user, local):
    """Whether the local time ``local`` is in the person's working days and
    hours (quiet hours on); from inclusive, until exclusive"""
    return (
        local.weekday() in (user.working_days or ())
        and user.working_from <= local.time() < user.working_until
    )


def mails_held(user, now=None):
    """Whether the person's notification mails and digests wait now: while
    away, and with quiet hours outside their working time"""
    local = timezone.localtime(now or timezone.now())
    if is_away(user, local.date()):
        return True
    return user.quiet_hours and not in_working_time(user, local)


def short_date(day, today=None):
    """ "3 Dec", with the year when it isn't this one"""
    today = today or timezone.localdate()
    return date_format(
        day, "MONTH_DAY_FORMAT" if day.year == today.year else "SHORT_DATE_FORMAT"
    )


def away_text(user):
    """The mark's title: "Away until 3 Dec: back on the 4th", "" when not
    away"""
    if not is_away(user):
        return ""
    day = short_date(user.away_until)
    if user.away_note:
        return _("Away until %(date)s: %(note)s") % {
            "date": day,
            "note": user.away_note,
        }
    return _("Away until %(date)s") % {"date": day}


def away_detail(user):
    """In pickers, the ``@`` list and teams: "away until 3 Dec" """
    if not is_away(user):
        return ""
    return _("away until %(date)s") % {"date": short_date(user.away_until)}


def away_notice(user, name=None):
    """Shown once in a form assigning or mentioning them: "Ada is away until
    3 Dec: back on the 4th, ask Bob meanwhile" """
    if not is_away(user):
        return ""
    context = {
        "name": name or user.get_short_name(),
        "date": short_date(user.away_until),
        "note": user.away_note,
    }
    if user.away_note:
        return _("%(name)s is away until %(date)s: %(note)s") % context
    return _("%(name)s is away until %(date)s.") % context
