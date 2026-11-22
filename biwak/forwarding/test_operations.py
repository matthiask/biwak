"""Filing, deleting and the 30-day cleanup (specs/forwarding.md)"""

import datetime as dt
import io

from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from biwak.activity.models import Notification
from biwak.files.models import Attachment
from biwak.forwarding import operations
from biwak.forwarding.models import ForwardedFile, ForwardedMail
from biwak.forwarding.support import IMAGE, sample
from biwak.inbound.support import replying
from biwak.items import operations as ops
from biwak.items.models import MessageCategory
from biwak.test_utils import person, project


@replying
class FilingTestCase(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.bea = person("Bea")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.bea, self.cleo])
        self.internal = ops.create_list(
            project=self.project, title="Internal", creator=self.bea
        )
        self.shared = ops.create_list(
            project=self.project, title="Shared", creator=self.bea, visible=True
        )

    def forwarded(self, name="outlook_en.eml", user=None):
        return operations.store(user or self.ada, sample(name))


class FileAsMessageTest(FilingTestCase):
    def test_an_internal_message_with_everything(self):
        forwarded = self.forwarded()
        category = MessageCategory.objects.create(name="Quotes")
        with self.captureOnCommitCallbacks(execute=True):
            item = operations.file_as_message(
                forwarded,
                project=self.project,
                title=forwarded.subject,
                category=category,
                actor=self.ada,
            )
        self.assertEqual(item.kind, "message")
        self.assertEqual(item.title, "Revised quote for the landing page")
        self.assertEqual(item.creator, self.ada)
        self.assertFalse(item.is_client_visible)
        self.assertEqual(item.message.category, category)
        content = item.message.content
        self.assertTrue(
            content.startswith(
                "Forwarded from Dora Example <dora@example.com>, 20 Nov 2026\n"
                "To: Ada Example \\<ada@example.org\\>, Bea Example"
                " \\<bea@example.org\\>\n"
                "Cc: Finn Example \\<finn@example.com\\>\n\n"
                "For the website project."
            ),
            content,
        )
        image, pdf = Attachment.objects.filter(item=item).order_by("pk")
        self.assertIn(f"![image001.png](attachment:{image.key})", content)
        self.assertIn(f"[Quote 2026-117.pdf](attachment:{pdf.key})", content)
        self.assertNotIn("forwarded:", content)
        with image.file.open("rb") as handle:
            self.assertEqual(handle.read(), IMAGE)
        self.assertEqual(image.uploaded_by, self.ada)
        # Gone from the list, files too
        self.assertFalse(ForwardedMail.objects.exists())
        self.assertFalse(ForwardedFile.objects.exists())
        # Posting tells people as posting a message does: staff, no clients
        self.assertEqual(
            set(Notification.objects.values_list("user", flat=True)), {self.bea.pk}
        )

    def test_in_the_forwarders_language(self):
        self.ada.language = "de"
        self.ada.save()
        item = operations.file_as_message(
            self.forwarded("apple_mail_en.eml"),
            project=self.project,
            title="Broken link",
            actor=self.ada,
        )
        self.assertTrue(
            item.message.content.startswith(
                "Weitergeleitet von Dora Example <dora@example.com>, 20. Nov. 2026\n"
                "An: Ada Example \\<ada@example.org\\>\n\n"
            ),
            item.message.content,
        )

    def test_only_by_the_forwarder(self):
        forwarded = self.forwarded()
        with self.assertRaises(PermissionDenied):
            operations.file_as_message(
                forwarded, project=self.project, title="Quote", actor=self.bea
            )
        self.assertTrue(ForwardedMail.objects.exists())


class FileAsTodoTest(FilingTestCase):
    def test_a_todo_with_notes_and_attachments(self):
        group = ops.create_group(todolist=self.internal.todolist, title="Bugs")
        forwarded = self.forwarded("gmail_en.eml")
        item = operations.file_as_todo(
            forwarded,
            todolist=self.internal,
            group=group,
            title=forwarded.subject,
            actor=self.ada,
        )
        self.assertEqual(item.parent, self.internal)
        self.assertEqual(item.todo.group, group)
        self.assertEqual(item.title, "Analytics export")
        self.assertFalse(item.is_client_visible)
        notes = item.todo.notes
        self.assertTrue(notes.startswith("Forwarded from Dora Example"))
        self.assertIn("Numbers are **up 12%** in November.", notes)
        [csv] = Attachment.objects.filter(item=item)
        self.assertIn(f"[analytics-2026-11.csv](attachment:{csv.key})", notes)
        self.assertFalse(ForwardedMail.objects.exists())

    def test_into_a_list_clients_see_the_todo_follows_it(self):
        item = operations.file_as_todo(
            self.forwarded("gmail_en.eml"),
            todolist=self.shared,
            title="Export",
            actor=self.ada,
        )
        self.assertTrue(item.is_client_visible)
        self.assertTrue(
            Attachment.objects.visible_to(self.cleo).filter(item=item).exists()
        )
        self.assertFalse(ForwardedMail.objects.exists())


class DeleteTest(FilingTestCase):
    def test_delete(self):
        forwarded = self.forwarded()
        with self.assertRaises(PermissionDenied):
            operations.delete(forwarded, actor=self.bea)
        operations.delete(forwarded, actor=self.ada)
        self.assertFalse(ForwardedMail.objects.exists())
        self.assertFalse(ForwardedFile.objects.exists())

    def test_unfiled_mails_go_after_30_days(self):
        old = self.forwarded()
        ForwardedMail.objects.filter(pk=old.pk).update(
            received_at=timezone.now() - dt.timedelta(days=31)
        )
        recent = self.forwarded("gmail_en.eml")
        ForwardedMail.objects.filter(pk=recent.pk).update(
            received_at=timezone.now() - dt.timedelta(days=29)
        )
        call_command("fairy_tasks", stdout=io.StringIO())
        self.assertEqual(list(ForwardedMail.objects.all()), [recent])
        self.assertEqual(ForwardedFile.objects.get().mail, recent)

    def test_waiting(self):
        self.forwarded()
        self.forwarded(user=self.bea)
        self.assertEqual(operations.waiting(self.ada), 1)
        self.assertEqual(operations.waiting(self.cleo), 0)
        self.assertEqual(list(operations.forwarded_for(self.cleo)), [])
