import re

from django.core import mail
from django.core.cache import cache
from django.test import TestCase

from biwak.projects import operations as project_ops
from biwak.test_utils import person, project


class ChangedAddressTest(TestCase):
    """A changed address replaces the old one: the old one doesn't log in
    anymore and can be given to somebody else (specs/access.md)"""

    def setUp(self):
        cache.clear()
        self.cleo = person("Cleo", client=True)
        self.cleo.email = "cleo@new.example.org"
        self.cleo.save()
        mail.outbox.clear()

    def test_old_address_does_not_log_in(self):
        self.client.post("/accounts/login/code/", {"email": "cleo@example.org"})
        # allauth's "unknown account" mail at most, no code
        self.assertFalse([
            m for m in mail.outbox if re.search(r"\b[A-Z0-9]{4}-[A-Z0-9]{4}\b", m.body)
        ])

    def test_old_address_given_to_somebody_else(self):
        ada = person("Ada")
        invited, _ = project_ops.invite(
            project("Website", members=[ada]), email="cleo@example.org", actor=ada
        )
        self.assertNotEqual(invited, self.cleo)
        self.assertEqual(invited.email, "cleo@example.org")
