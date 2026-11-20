"""Reactions on messages, docs, files and check-in answers, and on their
comments (specs/reactions.md): visibility through the pages and the API"""

import json

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from biwak.accounts.models import APIToken
from biwak.activity.models import Notification
from biwak.checkins import operations as checkin_ops
from biwak.checkins.support import MONDAY_9, at
from biwak.items import operations as ops
from biwak.items.models import Kind
from biwak.reactions import operations
from biwak.reactions.models import Reaction
from biwak.test_utils import person, project


class KindsTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.bob, self.cleo])
        self.things = {}
        for visible in (True, False):
            word = "shared" if visible else "secret"
            self.things[word] = {
                Kind.MESSAGE: ops.create_message(
                    project=self.project,
                    title=f"{word} message",
                    content="Text",
                    creator=self.ada,
                    visible=visible,
                ),
                Kind.DOC: ops.create_doc(
                    project=self.project,
                    title=f"{word} doc",
                    content="Text",
                    creator=self.ada,
                    visible=visible,
                ),
                Kind.FILE: ops.create_upload(
                    project=self.project,
                    file=SimpleUploadedFile(f"{word}.txt", b"Plan"),
                    creator=self.ada,
                    visible=visible,
                ),
            }
        for word, visible in (("shared", True), ("secret", False)):
            question = checkin_ops.create_question(
                project=self.project,
                title=f"{word} question",
                creator=self.ada,
                people=[self.ada, self.bob],
                now=at("2027-03-19 12:00"),
                visible=visible,
                **MONDAY_9,
            )
            checkin_ops.run(now=at("2027-03-22 09:00"))
            self.things[word][Kind.QUESTION] = question
            self.things[word][Kind.ANSWER] = checkin_ops.answer(
                question, user=self.ada, content="Fine"
            )

    def headers(self, user):
        _token, secret = APIToken.create_for(user=user, title="T", access="write")
        return {"authorization": f"Bearer {secret}"}

    def api(self, method, user, path, content=None):
        kwargs = {}
        if content is not None and method != "get":
            kwargs = {
                "data": json.dumps({"content": content}),
                "content_type": "application/json",
            }
        return getattr(self.client, method)(
            f"/api/v1/{path}", headers=self.headers(user), **kwargs
        )

    def kinds(self):
        return [Kind.MESSAGE, Kind.DOC, Kind.FILE, Kind.ANSWER]

    def page_of(self, item):
        if item.kind == Kind.ANSWER:
            return item.parent.get_absolute_url()
        return item.get_absolute_url()

    def test_pages_show_the_block_to_staff_and_clients(self):
        for user in (self.bob, self.cleo):
            self.client.force_login(user)
            for kind in self.kinds():
                item = self.things["shared"][kind]
                if kind == Kind.ANSWER:
                    item.parent.question.people.add(self.cleo)
                comment = ops.add_comment(item, author=self.ada, content="A comment")
                with self.subTest(user=user.pk, kind=kind):
                    response = self.client.get(self.page_of(item))
                    self.assertEqual(response.status_code, 200)
                    self.assertContains(response, f"/items/{item.pk}/reactions/")
                    self.assertContains(response, f"/comments/{comment.pk}/reactions/")

    def test_toggle_through_the_pages(self):
        for user in (self.bob, self.cleo):
            self.client.force_login(user)
            for kind in self.kinds():
                item = self.things["shared"][kind]
                comment = ops.add_comment(item, author=self.ada, content="A comment")
                with self.subTest(user=user.pk, kind=kind):
                    response = self.client.post(
                        f"/items/{item.pk}/reactions/", {"content": "👍"}
                    )
                    self.assertEqual(response.status_code, 302)
                    self.assertTrue(
                        Reaction.objects.filter(user=user, item=item, comment=None)
                    )
                    self.client.post(
                        f"/comments/{comment.pk}/reactions/", {"content": "🎉"}
                    )
                    self.assertTrue(Reaction.objects.filter(user=user, comment=comment))
                    page = self.client.get(self.page_of(item))
                    self.assertContains(page, "wb-reaction is-mine")

    def test_clients_get_404_for_internal_items(self):
        self.client.force_login(self.cleo)
        for kind in self.kinds():
            item = self.things["secret"][kind]
            comment = ops.add_comment(item, author=self.ada, content="Hush")
            with self.subTest(kind=kind):
                self.assertEqual(
                    self.client.post(
                        f"/items/{item.pk}/reactions/", {"content": "👍"}
                    ).status_code,
                    404,
                )
                self.assertEqual(
                    self.client.post(
                        f"/comments/{comment.pk}/reactions/", {"content": "👍"}
                    ).status_code,
                    404,
                )
                self.assertEqual(self.client.get(self.page_of(item)).status_code, 404)
        self.assertFalse(Reaction.objects.exists())

    def test_api_returns_reactions(self):
        for kind, path in [
            (Kind.MESSAGE, "messages/{pk}/"),
            (Kind.DOC, "docs/{pk}/"),
            (Kind.FILE, "files/{pk}/"),
        ]:
            item = self.things["shared"][kind]
            operations.toggle_reaction(self.bob, "👍", item=item)
            operations.toggle_reaction(self.ada, "👍", item=item)
            for user in (self.bob, self.cleo):
                with self.subTest(kind=kind, user=user.pk):
                    response = self.api("get", user, path.format(pk=item.pk))
                    self.assertEqual(response.status_code, 200)
                    found = response.json()["reactions"]
                    self.assertEqual(
                        [(r["content"], r["count"], r["mine"]) for r in found],
                        [("👍", 2, user == self.bob)],
                    )

    def test_api_reactions_on_messages_list_and_answers(self):
        message = self.things["shared"][Kind.MESSAGE]
        operations.toggle_reaction(self.bob, "🎉", item=message)
        response = self.api("get", self.cleo, f"projects/{self.project.pk}/messages/")
        [row] = response.json()["results"]
        self.assertEqual([r["content"] for r in row["reactions"]], ["🎉"])
        answer = self.things["shared"][Kind.ANSWER]
        operations.toggle_reaction(self.bob, "👀", item=answer)
        response = self.api(
            "get", self.bob, f"checkins/{answer.parent_id}/occurrences/"
        )
        [found] = response.json()["results"][0]["answers"]
        self.assertEqual([r["content"] for r in found["reactions"]], ["👀"])

    def test_api_toggle_and_404_for_clients(self):
        for kind in self.kinds():
            shared, secret = self.things["shared"][kind], self.things["secret"][kind]
            with self.subTest(kind=kind):
                response = self.api(
                    "post", self.cleo, f"items/{shared.pk}/reactions/", "👍"
                )
                self.assertEqual(response.status_code, 201)
                self.assertEqual(response.json()[0]["content"], "👍")
                for method in ("post", "get"):
                    response = self.api(
                        method, self.cleo, f"items/{secret.pk}/reactions/", "👍"
                    )
                    self.assertEqual(response.status_code, 404)
                # Staff can, and see them
                response = self.api(
                    "post", self.bob, f"items/{secret.pk}/reactions/", "👍"
                )
                self.assertEqual(response.status_code, 201)

    def test_comments_on_the_new_kinds(self):
        for kind in self.kinds():
            shared, secret = self.things["shared"][kind], self.things["secret"][kind]
            comment = ops.add_comment(shared, author=self.ada, content="Hi")
            hidden = ops.add_comment(secret, author=self.ada, content="Hush")
            operations.toggle_reaction(self.bob, "👍", comment=comment)
            with self.subTest(kind=kind):
                response = self.api("get", self.cleo, f"items/{shared.pk}/comments/")
                [found] = response.json()["results"]
                self.assertEqual(found["reactions"][0]["content"], "👍")
                response = self.api(
                    "post", self.cleo, f"comments/{hidden.pk}/reactions/", "👍"
                )
                self.assertEqual(response.status_code, 404)

    def test_the_author_is_told(self):
        for kind in self.kinds():
            item = self.things["shared"][kind]
            Notification.objects.all().delete()
            with self.captureOnCommitCallbacks(execute=True):
                operations.toggle_reaction(self.bob, "👍", item=item)
            with self.subTest(kind=kind):
                told = {n.user for n in Notification.objects.select_related("user")}
                self.assertEqual(told, {self.ada})

    def test_a_client_does_not_see_reactions_in_the_feed_of_internal_items(self):
        operations.toggle_reaction(self.bob, "👍", item=self.things["secret"][Kind.DOC])
        self.client.force_login(self.cleo)
        response = self.client.get("/feed/")
        self.assertNotContains(response, "secret doc")
