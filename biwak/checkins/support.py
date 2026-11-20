"""Shared by the check-in tests"""

import datetime as dt
from zoneinfo import ZoneInfo

from django.core import mail
from django.test import TestCase, override_settings

from biwak.checkins import operations as ops
from biwak.test_utils import person, project


ZURICH = ZoneInfo("Europe/Zurich")
MONDAY_9 = {
    "rule": "FREQ=WEEKLY;BYDAY=MO",
    "starts_on": dt.date(2027, 3, 15),
    "time_of_day": dt.time(9, 0),
}


def at(text, tz=ZURICH):
    """A moment from local wall clock time"""
    return dt.datetime.fromisoformat(text).replace(tzinfo=tz)


def local(moment, tz=ZURICH):
    return moment.astimezone(tz).replace(tzinfo=None).isoformat(" ", "minutes")


@override_settings(
    BASE_URL="https://biwak.example.org", DEFAULT_FROM_EMAIL="biwak@example.org"
)
class CheckinTestCase(TestCase):
    """Ada, Bob (staff) and Cleo (a client) in the project "Website"; a
    question "How are you?" every Monday at 09:00 Europe/Zurich for Ada and
    Bob, created on Friday 19 March 2027"""

    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.bob, self.cleo])
        self.item = self.question()

    def question(self, title="How are you?", **kwargs):
        kwargs = (
            {
                "project": self.project,
                "title": title,
                "creator": self.ada,
                "people": [self.ada, self.bob],
                "now": at("2027-03-19 12:00"),
            }
            | MONDAY_9
            | kwargs
        )
        return ops.create_question(**kwargs)

    def run_at(self, text, tz=ZURICH):
        """What ``send_mails`` does at the local time, mails included"""
        with self.captureOnCommitCallbacks(execute=True):
            return ops.run(now=at(text, tz))

    def sent(self, to=None, *, clear=True):
        messages = [m for m in mail.outbox if to is None or m.to == [to.email]]
        if clear:
            mail.outbox.clear()
        return messages

    def recipients(self):
        """Who got mail since, sorted by address"""
        return sorted(address for m in self.sent() for address in m.to)
