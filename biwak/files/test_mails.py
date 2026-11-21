import datetime as dt

from django.core import mail
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.utils import timezone

from biwak.activity.mails import send_mails
from biwak.files import operations
from biwak.items import operations as ops
from biwak.test_utils import person, project


@override_settings(
    BASE_URL="https://biwak.example.org", DEFAULT_FROM_EMAIL="biwak@example.org"
)
class MailsTest(TestCase):
    """Mails about messages, docs and files go out like the others and
    follow visibility"""

    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.bob, self.cleo])

    def send(self, run):
        with self.captureOnCommitCallbacks(execute=True):
            run()
        with self.captureOnCommitCallbacks(execute=True):
            send_mails(now=timezone.now() + dt.timedelta(minutes=11))
        mails = {m.to[0]: m for m in mail.outbox}
        mail.outbox.clear()
        return mails

    def test_a_visible_message_tells_everybody(self):
        mails = self.send(
            lambda: ops.create_message(
                project=self.project,
                title="Kick-off",
                content="We start **Monday**",
                creator=self.ada,
                visible=True,
                whom="everybody",
            )
        )
        self.assertEqual(set(mails), {self.bob.email, self.cleo.email})
        body = mails[self.cleo.email].body
        self.assertTrue(body.startswith("Clients can see this."))
        self.assertIn("We start **Monday**", body)
        self.assertIn("https://biwak.example.org/messages/", body)

    def test_an_internal_message_does_not_reach_clients(self):
        mails = self.send(
            lambda: ops.create_message(
                project=self.project,
                title="Internal",
                creator=self.ada,
                whom="everybody",
            )
        )
        self.assertEqual(set(mails), {self.bob.email})
        self.assertNotIn("Clients can see this", mails[self.bob.email].body)

    def test_chosen_people_only(self):
        mails = self.send(
            lambda: ops.create_message(
                project=self.project,
                title="Hi",
                creator=self.ada,
                visible=True,
                whom=[self.cleo],
            )
        )
        self.assertEqual(set(mails), {self.cleo.email})

    def test_a_doc(self):
        mails = self.send(
            lambda: ops.create_doc(
                project=self.project,
                title="Minutes",
                content="Decided: **yes**",
                creator=self.ada,
                visible=True,
                whom="everybody",
            )
        )
        self.assertEqual(set(mails), {self.bob.email, self.cleo.email})
        self.assertIn("Decided: **yes**", mails[self.cleo.email].body)
        self.assertIn("/docs/", mails[self.cleo.email].body)

    def test_a_file(self):
        folder = ops.create_folder(
            project=self.project, title="Specs", creator=self.ada, visible=True
        )
        mails = self.send(
            lambda: ops.create_upload(
                project=self.project,
                file=ContentFile(b"x", name="plan.pdf"),
                description="The latest plan",
                creator=self.ada,
                parent=folder,
                whom="everybody",
            )
        )
        self.assertEqual(set(mails), {self.bob.email, self.cleo.email})
        self.assertIn("The latest plan", mails[self.cleo.email].body)
        self.assertIn("/files/", mails[self.cleo.email].body)

    def test_an_internal_file_does_not_reach_clients(self):
        mails = self.send(
            lambda: ops.create_upload(
                project=self.project,
                file=ContentFile(b"x", name="plan.pdf"),
                creator=self.ada,
                whom=[self.bob, self.cleo],
            )
        )
        self.assertEqual(set(mails), {self.bob.email})

    def test_pinning_sends_no_mail(self):
        message = ops.create_message(
            project=self.project,
            title="Hi",
            creator=self.ada,
            visible=True,
            whom="everybody",
        )
        self.send(lambda: None)
        mails = self.send(lambda: operations.pin_message(message, actor=self.ada))
        self.assertEqual(mails, {})

    def test_comments_on_a_message(self):
        message = ops.create_message(
            project=self.project,
            title="Hi",
            creator=self.ada,
            visible=True,
            whom="everybody",
        )
        self.send(lambda: None)
        mails = self.send(
            lambda: ops.add_comment(message, author=self.cleo, content="Thanks")
        )
        self.assertEqual(set(mails), {self.ada.email, self.bob.email})
        self.assertIn("Thanks", mails[self.ada.email].body)
