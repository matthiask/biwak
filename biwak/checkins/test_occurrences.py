import datetime as dt

from django.core import mail

from biwak.checkins import operations as ops
from biwak.checkins.models import Occurrence
from biwak.checkins.support import CheckinTestCase, at


class AddOccurrenceTest(CheckinTestCase):
    """The past occurrences the importer adds (specs/import-basecamp.md)"""

    def test_adds_one_without_asking_anybody(self):
        day = dt.date(2027, 1, 4)
        occurrence = ops.add_occurrence(
            self.item, date=day, asked_at=at("2027-01-04 09:00"), people=[self.ada]
        )
        self.assertEqual(occurrence.date, day)
        self.assertEqual(list(occurrence.asked.all()), [self.ada])
        self.assertEqual(mail.outbox, [])

    def test_again_for_the_date_is_the_same_occurrence(self):
        args = {"date": dt.date(2027, 1, 4), "asked_at": at("2027-01-04 09:00")}
        first = ops.add_occurrence(self.item, **args)
        self.assertEqual(ops.add_occurrence(self.item, **args), first)
        self.assertEqual(Occurrence.objects.count(), 1)

    def test_answers_are_created_for_anybody(self):
        # The importer answers for people who aren't asked (anymore)
        occurrence = ops.add_occurrence(
            self.item, date=dt.date(2027, 1, 4), asked_at=at("2027-01-04 09:00")
        )
        answer = ops.create_answer(self.item, self.cleo, "Hello", occurrence)
        self.assertEqual(answer.answer.author, self.cleo)
