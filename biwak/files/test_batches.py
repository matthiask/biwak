"""Files uploaded together tell once (specs/files.md, "Uploading files"): one
entry in the lantern, one mail, one entry of the digest"""

import datetime as dt
import zoneinfo

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from biwak.accounts.models import MailDelivery
from biwak.activity import lantern
from biwak.activity.mails import send_mails
from biwak.activity.models import Notification
from biwak.items import operations as ops
from biwak.test_utils import person, project


ZURICH = zoneinfo.ZoneInfo("Europe/Zurich")
BATCH = "a" * 32


@override_settings(
    BASE_URL="https://biwak.example.org", DEFAULT_FROM_EMAIL="biwak@example.org"
)
class BatchTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.bob, self.cleo])
        self.minutes = ops.create_folder(
            project=self.project, title="Minutes", creator=self.ada, visible=True
        )

    def upload(self, names, *, batch=BATCH, whom="everybody", parent="minutes"):
        with self.captureOnCommitCallbacks(execute=True):
            return [
                ops.create_upload(
                    project=self.project,
                    file=SimpleUploadedFile(name, b"x"),
                    creator=self.ada,
                    parent=self.minutes if parent == "minutes" else parent,
                    whom=whom,
                    batch=batch,
                )
                for name in names
            ]

    def send(self, now):
        with self.captureOnCommitCallbacks(execute=True):
            return send_mails(now=now)

    def test_one_lantern_entry(self):
        files = self.upload(["a.txt", "b.txt", "c.txt"])
        self.assertEqual(Notification.objects.filter(user=self.bob).count(), 3)
        self.assertEqual(lantern.unread_counts(self.bob), (3, 1))
        self.assertEqual(lantern.unread_count(self.cleo), 1)
        _marks, unread, _read, _more = lantern.menu(self.bob)
        self.assertEqual(len(unread), 1)
        batch, entries = unread[0]
        self.assertTrue(batch.is_batch)
        self.assertEqual([f.pk for f in batch.files], [f.pk for f in files])
        self.assertEqual(batch.line, "Ada Example uploaded 3 files to Minutes.")
        self.assertEqual(len(entries), 1)

        self.client.force_login(self.bob)
        response = self.client.get(reverse("lantern_menu"))
        self.assertContains(response, "Ada Example uploaded 3 files to Minutes.")
        self.assertContains(response, self.minutes.get_absolute_url())
        for item in files:
            self.assertContains(response, item.get_absolute_url())
        self.assertEqual(self.client.get(reverse("lantern_count")).json()["unread"], 1)
        # Following it reads the batch
        notification = Notification.objects.filter(user=self.bob).first()
        self.client.post(
            reverse("lantern_open", args=[notification.pk]),
            headers={"HX-Request": "true"},
        )
        self.assertEqual(lantern.unread_counts(self.bob), (0, 0))
        # Unread again, and read with its button (all the files)
        self.client.post(reverse("lantern_unread"), {"item": [f.pk for f in files]})
        self.assertEqual(lantern.unread_count(self.bob), 1)
        self.client.post(reverse("lantern_read"), {"item": [f.pk for f in files]})
        self.assertEqual(lantern.unread_count(self.bob), 0)

    def test_other_uploads_and_other_events_stay_apart(self):
        files = self.upload(["a.txt", "b.txt"])
        self.upload(["c.txt"], batch="b" * 32)
        self.upload(["d.txt"], batch=None)
        with self.captureOnCommitCallbacks(execute=True):
            ops.add_comment(files[0], author=self.ada, content="Look")
        self.assertEqual(lantern.unread_count(self.bob), 4)

    def test_a_client_gets_only_what_clients_see(self):
        private = ops.create_folder(
            project=self.project, title="Private", creator=self.ada
        )
        self.upload(["a.txt", "b.txt"], parent=private)
        self.assertEqual(lantern.unread_count(self.cleo), 0)
        self.assertEqual(lantern.unread_count(self.bob), 1)

    def test_one_mail(self):
        files = self.upload(["a.txt", "b.txt", "c.txt"])
        later = timezone.now() + dt.timedelta(minutes=3)
        self.assertEqual(self.send(later), 2)  # Bob and Cleo
        message = next(m for m in mail.outbox if m.to == [self.bob.email])
        self.assertEqual(message.subject, "[Website] Minutes")
        self.assertIn("Ada Example uploaded 3 files to Minutes.", message.body)
        for item in files:
            self.assertIn(
                f"https://biwak.example.org{item.get_absolute_url()}", message.body
            )
        self.assertIn("Clients can see this.", message.body)
        html = message.alternatives[0][0]
        self.assertIn("Ada Example uploaded 3 files to Minutes.", html)
        self.assertEqual(self.send(later), 0)

    def test_one_entry_of_the_digest(self):
        self.bob.mail_delivery = MailDelivery.DIGEST
        self.bob.save()
        self.upload(["a.txt", "b.txt"])
        self.upload(["top.txt"], parent=None, batch="c" * 32)
        evening = dt.datetime(2026, 11, 19, 22, 0, tzinfo=ZURICH)
        Notification.objects.update(created_at=evening)
        self.send(dt.datetime(2026, 11, 20, 7, 0, tzinfo=ZURICH))
        message = next(m for m in mail.outbox if m.to == [self.bob.email])
        self.assertEqual(
            message.body.count("Ada Example uploaded 2 files to Minutes."), 1
        )
        self.assertIn("Ada Example uploaded a file to Docs and files.", message.body)
        self.assertIn("top.txt", message.body)
