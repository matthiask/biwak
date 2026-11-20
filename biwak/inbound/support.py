"""Shared by the tests of replying by mail"""

import base64

from django.test import TestCase, override_settings

from biwak.activity.operations import subscribe
from biwak.inbound.models import ReplyToken
from biwak.items import operations as ops
from biwak.items.models import Comment
from biwak.test_utils import person, project


SECRET = "whsec_" + base64.b64encode(b"biwak-test-webhook-secret-0123").decode()

replying = override_settings(
    REPLY_DOMAIN="reply.example.org",
    RESEND_API_KEY="re_test_key",
    RESEND_WEBHOOK_SECRET=SECRET,
    BASE_URL="https://biwak.example.org",
    DEFAULT_FROM_EMAIL="biwak@example.org",
)


@replying
class ReplyTestCase(TestCase):
    """Ada and Bea (staff), Cleo (a client) in "Website"; Bea's to-do in a
    list visible to clients, Ada and Cleo subscribed"""

    def setUp(self):
        self.ada = person("Ada")
        self.bea = person("Bea")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.bea, self.cleo])
        self.shared = ops.create_list(
            project=self.project, title="Shared", creator=self.bea, visible=True
        )
        self.todo = ops.create_todo(
            todolist=self.shared,
            title="Update the copy on the landing page",
            creator=self.bea,
        )
        subscribe(self.ada, self.todo)
        subscribe(self.cleo, self.todo)

    def token(self, user=None, item=None, **kwargs):
        return ReplyToken.objects.create(
            user=user or self.ada, item=item or self.todo, **kwargs
        )

    def comments(self):
        return list(Comment.objects.filter(item=self.todo).order_by("pk"))
