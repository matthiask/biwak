"""Moving to another project through every entry point (AGENTS.md,
specs/access.md): the pages, the feed, search, mails, mail replies and the
API follow the item into its new project"""

import datetime as dt

from django.core import mail
from django.utils import timezone

from biwak.accounts.models import APIToken
from biwak.activity.mails import send_mails
from biwak.activity.operations import subscribe
from biwak.inbound.models import InboundStatus
from biwak.inbound.support import ReplyTestCase
from biwak.inbound.support_mails import ReceiveMixin, sample
from biwak.items import operations as ops
from biwak.items.models import Comment
from biwak.test_utils import person, project


class MovedTest(ReceiveMixin, ReplyTestCase):
    """Bea's visible list "Shared" with its to-do moves from Website (Ada,
    Bea, Cleo) to Shop (Ada, Bea, Dan, another client)"""

    def setUp(self):
        super().setUp()
        self.dan = person("Dan", client=True, organization="Example Shop Ltd")
        self.shop = project("Shop", members=[self.ada, self.bea, self.dan])
        self.doc = ops.create_doc(
            project=self.project, title="Zebra notes", creator=self.bea
        )
        with self.captureOnCommitCallbacks(execute=True):
            ops.add_comment(self.todo, author=self.cleo, content="Giraffe sizes")

    def move(self):
        with self.captureOnCommitCallbacks(execute=True):
            ops.move_to_project(self.shared, project=self.shop, actor=self.bea)
            ops.move_to_project(self.doc, project=self.shop, actor=self.bea)

    def api(self, user):
        _token, secret = APIToken.create_for(user=user, title="T", access="read")
        return {"authorization": f"Bearer {secret}"}

    def test_pages(self):
        self.move()
        for user, status in [(self.cleo, 404), (self.dan, 200), (self.ada, 200)]:
            self.client.force_login(user)
            with self.subTest(user=str(user)):
                self.assertEqual(
                    self.client.get(self.todo.get_absolute_url()).status_code, status
                )
                self.assertEqual(
                    self.client.get(self.shared.get_absolute_url()).status_code,
                    status,
                )
        # Internal stays internal
        self.client.force_login(self.dan)
        self.assertEqual(self.client.get(self.doc.get_absolute_url()).status_code, 404)
        # The project pages
        page = self.client.get(self.shop.get_absolute_url())
        self.assertContains(page, "Shared")
        self.assertNotContains(page, "Zebra")
        self.client.force_login(self.ada)
        page = self.client.get(self.project.get_absolute_url())
        self.assertNotContains(page, "Zebra notes")
        self.assertNotContains(page, "Shared")

    def test_feeds(self):
        self.move()
        self.client.force_login(self.cleo)
        self.assertNotContains(self.client.get("/feed/"), "Giraffe")
        self.assertNotContains(self.client.get("/feed/"), "Update the copy")
        self.client.force_login(self.dan)
        feed = self.client.get(f"/projects/{self.shop.pk}/feed/")
        # What clients saw before comes along, the internal doc doesn't
        self.assertContains(feed, "Giraffe")
        self.assertNotContains(feed, "Zebra")
        # Not the project it came from
        self.assertNotContains(feed, "Website")
        self.assertContains(feed, "to Shop")
        self.client.force_login(self.ada)
        old = self.client.get(f"/projects/{self.project.pk}/feed/")
        self.assertNotContains(old, "Giraffe")
        self.assertNotContains(old, "Zebra")
        new = self.client.get(f"/projects/{self.shop.pk}/feed/")
        self.assertContains(new, "Giraffe")
        self.assertContains(new, "Zebra notes")
        self.assertContains(new, "from Website to Shop", count=2)

    def test_search(self):
        self.move()
        for user, found in [(self.cleo, []), (self.dan, ["Update the copy"])]:
            self.client.force_login(user)
            with self.subTest(user=str(user)):
                response = self.client.get("/search/", {"q": "giraffe"})
                self.assertEqual(
                    [r["item"].title[:15] for r in response.context["results"]],
                    found,
                )
                response = self.client.get(
                    "/api/v1/search/", {"q": "zebra"}, headers=self.api(user)
                )
                self.assertEqual(response.json()["results"], [])
        self.client.force_login(self.ada)
        response = self.client.get(
            "/search/", {"q": "zebra", "project": self.project.pk}
        )
        self.assertEqual(list(response.context["results"]), [])
        response = self.client.get("/search/", {"q": "zebra", "project": self.shop.pk})
        self.assertEqual(len(response.context["results"]), 1)

    def test_mails(self):
        """Cleo (dropped) isn't told about what happened before or after;
        nobody is told about the move"""
        subscribe(self.dan, self.todo)
        mail.outbox = []
        with self.captureOnCommitCallbacks(execute=True):
            ops.add_comment(self.todo, author=self.ada, content="Before")
        self.move()
        with self.captureOnCommitCallbacks(execute=True):
            ops.add_comment(self.todo, author=self.ada, content="After")
        with self.captureOnCommitCallbacks(execute=True):
            send_mails(now=timezone.now() + dt.timedelta(minutes=11))
        recipients = {message.to[0] for message in mail.outbox}
        self.assertNotIn(self.cleo.email, recipients)
        self.assertIn(self.dan.email, recipients)
        for message in mail.outbox:
            self.assertNotIn("moved", message.body)

    def test_mail_replies(self):
        cleo, ada = self.token(self.cleo), self.token(self.ada)
        self.move()
        message = self.receive(sample("iphone_de.eml", cleo))
        self.assertEqual(message.status, InboundStatus.NO_ACCESS)
        message = self.receive(sample("gmail_en.eml", ada))
        self.assertEqual(message.status, InboundStatus.POSTED)
        self.assertEqual(
            Comment.objects.filter(item=self.todo, author=self.cleo).count(), 1
        )

    def test_api(self):
        self.move()
        for user, status in [(self.cleo, 404), (self.dan, 200)]:
            with self.subTest(user=str(user)):
                response = self.client.get(
                    f"/api/v1/todos/{self.todo.pk}/", headers=self.api(user)
                )
                self.assertEqual(response.status_code, status)
        response = self.client.get(
            f"/api/v1/todos/{self.todo.pk}/", headers=self.api(self.ada)
        )
        self.assertEqual(response.json()["project_id"], self.shop.pk)
        # The event names the projects the reader opens only
        response = self.client.get(
            "/api/v1/feed/", {"action": "moved"}, headers=self.api(self.dan)
        )
        [event] = response.json()["results"]
        self.assertEqual(event["data"]["to_project"], "Shop")
        self.assertNotIn("from_project", event["data"])
        self.assertNotIn("from_project_id", event["data"])
        response = self.client.get(
            "/api/v1/feed/",
            {"action": "moved", "project_id": self.shop.pk},
            headers=self.api(self.ada),
        )
        data = response.json()["results"][0]["data"]
        self.assertEqual(data["from_project"], "Website")
        self.assertEqual(data["from_project_id"], self.project.pk)
        response = self.client.get(
            f"/api/v1/projects/{self.project.pk}/feed/", headers=self.api(self.cleo)
        )
        self.assertEqual(response.json()["results"], [])
