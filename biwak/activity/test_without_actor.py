"""Events without an actor: Biwak itself did it (specs/stale-todos.md).
Everywhere an event is read it says "Biwak"."""

import datetime as dt

import time_machine
from django.core import mail
from django.utils import timezone

from biwak.accounts.models import APIToken, MailDelivery
from biwak.activity import lantern
from biwak.activity.models import Action, Notification
from biwak.activity.operations import record
from biwak.activity.test_mails import MailsBase
from biwak.api_conventions import person_out


class WithoutActorTest(MailsBase):
    def setUp(self):
        super().setUp()
        self.created_at = timezone.now()
        self.act(
            lambda: record(
                actor=None,
                action=Action.COMPLETED,
                project=self.project,
                item=self.todo,
            )
        )

    def test_told_like_any_other(self):
        # Ada (the creator) and Bob are subscribed, nobody is left out as
        # the actor
        self.assertEqual(
            set(Notification.objects.values_list("user", flat=True)),
            {self.ada.pk, self.bob.pk},
        )
        self.client.force_login(self.bob)
        response = self.client.get("/lantern/")
        self.assertContains(response, "Biwak completed it.")

    def test_mail_per_change(self):
        self.send(timezone.now() + dt.timedelta(minutes=11))
        message = next(m for m in mail.outbox if m.to == [self.bob.email])
        self.assertTrue(message.from_email.startswith("Biwak <"), message.from_email)
        self.assertIn("Biwak completed it.", message.body)

    def test_digest(self):
        self.bob.mail_delivery = MailDelivery.DIGEST
        self.bob.save()
        tomorrow = timezone.localtime(self.created_at) + dt.timedelta(days=1)
        with time_machine.travel(tomorrow.replace(hour=8), tick=False):
            self.send(timezone.now())
        message = next(m for m in mail.outbox if m.to == [self.bob.email])
        self.assertIn("Biwak", message.body)
        self.assertNotIn("None", message.body)

    def test_feed_and_timeline(self):
        self.client.force_login(self.bob)
        for url, name in [
            ("/feed/", '<span class="fw-semibold">Biwak</span>'),
            (self.todo.get_absolute_url(), "<strong>Biwak</strong>"),
        ]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertContains(response, name)
                self.assertNotContains(response, ">None<")

    def test_api(self):
        _token, secret = APIToken.create_for(user=self.bob, title="T", access="read")
        response = self.client.get(
            f"/api/v1/projects/{self.project.pk}/feed/",
            headers={"authorization": f"Bearer {secret}"},
        )
        self.assertEqual(response.status_code, 200)
        events = response.json()["results"]
        self.assertEqual(events[0]["action"], "completed")
        self.assertIsNone(events[0]["actor"])
        self.assertEqual(events[1]["actor"], person_out(self.ada))

    def test_lantern_unread(self):
        self.assertEqual(lantern.unread_count(self.bob), 1)
