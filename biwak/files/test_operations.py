import datetime as dt

import time_machine
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.test import TestCase
from django.utils import timezone

from biwak.accounts.models import NotificationLevel
from biwak.activity.models import Action, Event, Notification, Subscription
from biwak.collab import live, ytext
from biwak.collab.models import LiveState
from biwak.files import attachments, operations
from biwak.files.models import MAX_SIZE, FileVersion
from biwak.items import operations as ops, visibility
from biwak.items.models import DocVersion, Item, Kind, MessageCategory
from biwak.test_utils import bare_doc, person, project


def file(name="plan.pdf", content=b"%PDF-1.4"):
    return ContentFile(content, name=name)


class Fixture:
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.bob, self.cleo])

    def told(self, run):
        before = set(Notification.objects.values_list("pk", flat=True))
        with self.captureOnCommitCallbacks(execute=True):
            run()
        return {
            n.user
            for n in Notification.objects.exclude(pk__in=before).select_related("user")
        }


class MessageTest(Fixture, TestCase):
    def test_create(self):
        category = MessageCategory.objects.create(name="Announcement", emoji="📣")
        item = ops.create_message(
            project=self.project,
            title="Hello",
            content="Text",
            creator=self.ada,
            category=category,
            visible=True,
        )
        self.assertEqual(item.message.category, category)
        self.assertTrue(item.is_client_visible)
        self.assertIsNone(item.message.pinned_at)
        self.assertEqual(str(category), "📣 Announcement")
        self.assertTrue(item.is_commentable)

    def test_what_clients_post_is_visible_to_clients(self):
        item = ops.create_message(project=self.project, title="Hi", creator=self.cleo)
        self.assertTrue(item.visible_to_clients)
        self.assertTrue(item.is_client_visible)

    def test_who_is_told(self):
        """Those who want to hear, and ``also`` whom the poster adds
        (decided 2026-11-21: additive)"""

        def post(also=()):
            return self.told(
                lambda: ops.create_message(
                    project=self.project,
                    title="Hi",
                    creator=self.ada,
                    visible=True,
                    also=also,
                )
            )

        self.assertEqual(post(), {self.bob, self.cleo})
        self.bob.notification_level = NotificationLevel.CONCERNS_ME
        self.bob.save()
        self.assertEqual(post(), {self.cleo})
        self.assertEqual(post([self.bob]), {self.bob, self.cleo})

    def test_internal_messages_do_not_notify_clients(self):
        told = self.told(
            lambda: ops.create_message(
                project=self.project, title="Hi", creator=self.ada
            )
        )
        self.assertEqual(told, {self.bob})

    def test_update(self):
        item = ops.create_message(
            project=self.project, title="Hi", content="One", creator=self.ada
        )
        category = MessageCategory.objects.create(name="News")
        operations.update_message(
            item, actor=self.ada, title="Hello", content="Two", category=category
        )
        item.refresh_from_db()
        self.assertEqual(item.title, "Hello")
        self.assertEqual(item.message.content, "Two")
        self.assertEqual(item.message.category, category)
        self.assertEqual(
            Event.objects.filter(item=item, action=Action.EDITED).count(), 1
        )
        operations.update_message(item, actor=self.ada, category=None)
        item.message.refresh_from_db()
        self.assertIsNone(item.message.category)

    def test_mention_notifies(self):
        told = self.told(
            lambda: ops.create_message(
                project=self.project,
                title="Hi",
                content=f"[@Bob](person:{self.bob.pk})",
                creator=self.ada,
            )
        )
        self.assertEqual(told, {self.bob})


class PinningTest(Fixture, TestCase):
    def setUp(self):
        super().setUp()
        self.message = ops.create_message(
            project=self.project, title="Hi", creator=self.ada, visible=True
        )

    def test_pin_and_unpin(self):
        self.assertTrue(operations.pin_message(self.message, actor=self.ada))
        self.message.message.refresh_from_db()
        self.assertIsNotNone(self.message.message.pinned_at)
        # Pinning twice changes nothing and records nothing
        self.assertFalse(operations.pin_message(self.message, actor=self.ada))
        self.assertEqual(
            Event.objects.filter(item=self.message, action=Action.PINNED).count(), 1
        )
        self.assertTrue(operations.unpin_message(self.message, actor=self.ada))
        self.message.message.refresh_from_db()
        self.assertIsNone(self.message.message.pinned_at)
        self.assertFalse(operations.unpin_message(self.message, actor=self.ada))
        self.assertTrue(
            Event.objects.filter(item=self.message, action=Action.UNPINNED).exists()
        )

    def test_clients_cannot_pin(self):
        with self.assertRaises(PermissionDenied):
            operations.pin_message(self.message, actor=self.cleo)
        operations.pin_message(self.message, actor=self.ada)
        with self.assertRaises(PermissionDenied):
            operations.unpin_message(self.message, actor=self.cleo)

    def test_events_notify_nobody(self):
        Subscription.objects.get_or_create(user=self.bob, item=self.message)
        Subscription.objects.get_or_create(user=self.cleo, item=self.message)
        self.assertEqual(
            self.told(lambda: operations.pin_message(self.message, actor=self.ada)),
            set(),
        )
        self.assertEqual(
            self.told(lambda: operations.unpin_message(self.message, actor=self.ada)),
            set(),
        )

    def test_trashing_keeps_the_pin(self):
        operations.pin_message(self.message, actor=self.ada)
        ops.trash(self.message, actor=self.ada)
        ops.restore(self.message, actor=self.ada)
        self.message.message.refresh_from_db()
        self.assertIsNotNone(self.message.message.pinned_at)


class DocTest(Fixture, TestCase):
    def setUp(self):
        super().setUp()
        self.doc = bare_doc(
            project=self.project, title="Notes", content="One", creator=self.ada
        )

    def versions(self):
        return list(self.doc.doc.versions.all())

    def test_creating_makes_the_first_version(self):
        (version,) = self.versions()
        self.assertEqual((version.title, version.content), ("Notes", "One"))
        self.assertEqual(version.created_by, self.ada)

    def test_saving_within_ten_minutes_by_the_same_person_updates_the_version(self):
        operations.update_doc(self.doc, actor=self.ada, content="Two")
        self.doc.doc.refresh_from_db()
        self.assertEqual(self.doc.doc.content, "Two")
        (version,) = self.versions()
        self.assertEqual(version.content, "Two")

    def test_a_new_version_after_ten_minutes(self):
        with time_machine.travel(timezone.now() + dt.timedelta(minutes=11)):
            operations.update_doc(self.doc, actor=self.ada, content="Two")
        self.assertEqual([v.content for v in self.versions()], ["Two", "One"])

    def test_a_new_version_by_somebody_else(self):
        operations.update_doc(self.doc, actor=self.bob, content="Two")
        self.assertEqual(
            [(v.content, v.created_by) for v in self.versions()],
            [("Two", self.bob), ("One", self.ada)],
        )

    def test_save_as_a_version(self):
        operations.update_doc(self.doc, actor=self.ada, content="Two")
        operations.update_doc(
            self.doc, actor=self.ada, content="Three", new_version=True
        )
        self.assertEqual([v.content for v in self.versions()], ["Three", "Two"])

    def test_unchanged_saves_nothing(self):
        before = Event.objects.count()
        operations.update_doc(self.doc, actor=self.bob, content="One")
        self.assertEqual(len(self.versions()), 1)
        self.assertEqual(Event.objects.count(), before)

    def test_the_title_is_the_first_line_of_the_text(self):
        operations.update_doc(
            self.doc, actor=self.bob, content="## Meeting notes\n\nText"
        )
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.title, "Meeting notes")
        self.assertEqual(self.versions()[0].title, "Meeting notes")
        operations.update_doc(self.doc, actor=self.bob, content="Plain *line*\nmore")
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.title, "Plain line")
        operations.update_doc(self.doc, actor=self.bob, content="")
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.title, "")
        self.assertEqual(self.doc.shown_title, "Untitled")

    def test_a_save_without_a_new_text_keeps_the_title(self):
        operations.save_version(self.doc, actor=self.bob)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.title, "Notes")

    def test_restoring_sets_the_title_too(self):
        operations.update_doc(self.doc, actor=self.bob, content="# Two\n")
        operations.update_doc(
            self.doc, actor=self.bob, content="# Three\n", new_version=True
        )
        operations.restore_doc_version(self.doc, self.versions()[1], actor=self.ada)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.title, "Two")

    def test_creating_starts_with_the_title_as_a_heading(self):
        doc = ops.create_doc(
            project=self.project, title="Plan", content="Body", creator=self.ada
        )
        self.assertEqual(doc.doc.content, "# Plan\n\nBody")
        self.assertEqual(doc.title, "Plan")
        self.assertEqual(doc.doc.versions.get().content, "# Plan\n\nBody")
        empty = ops.create_doc(project=self.project, title="Empty", creator=self.ada)
        self.assertEqual(empty.doc.content, "# Empty\n\n")

    def test_restoring_saves_the_old_content_as_a_new_version(self):
        operations.update_doc(self.doc, actor=self.bob, content="Two")
        old = self.versions()[1]
        operations.restore_doc_version(self.doc, old, actor=self.ada)
        self.doc.doc.refresh_from_db()
        self.assertEqual(self.doc.doc.content, "One")
        self.assertEqual([v.content for v in self.versions()], ["One", "Two", "One"])

    def test_restoring_another_docs_version(self):
        other = bare_doc(project=self.project, title="Other", creator=self.ada)
        with self.assertRaises(ValueError):
            operations.restore_doc_version(
                self.doc, other.doc.versions.get(), actor=self.ada
            )

    def test_read_only(self):
        """Nobody edits a read-only doc (specs/collaboration.md); staff
        switch it"""
        self.assertTrue(
            operations.set_read_only(self.doc, read_only=True, actor=self.ada)
        )
        self.assertFalse(
            operations.set_read_only(self.doc, read_only=True, actor=self.ada)
        )
        with self.assertRaises(operations.DocReadOnly):
            operations.update_doc(self.doc, actor=self.ada, content="Two")
        with self.assertRaises(operations.DocReadOnly):
            operations.restore_doc_version(self.doc, self.versions()[0], actor=self.ada)
        with self.assertRaises(PermissionDenied):
            operations.set_read_only(self.doc, read_only=False, actor=self.cleo)
        operations.set_read_only(self.doc, read_only=False, actor=self.bob)
        operations.update_doc(self.doc, actor=self.ada, content="Two")
        self.doc.doc.refresh_from_db()
        self.assertEqual(self.doc.doc.content, "Two")

    def test_refusing_to_overwrite_a_newer_version_by_somebody_else(self):
        base = self.versions()[0].pk
        operations.update_doc(self.doc, actor=self.bob, content="Bob's")
        with self.assertRaises(operations.DocConflict) as raised:
            operations.update_doc(
                self.doc, actor=self.ada, content="Ada's", base_version=base
            )
        self.assertEqual(raised.exception.version.created_by, self.bob)
        self.doc.doc.refresh_from_db()
        self.assertEqual(self.doc.doc.content, "Bob's")
        # With the newest version as the base it works
        operations.update_doc(
            self.doc,
            actor=self.ada,
            content="Ada's",
            base_version=self.versions()[0].pk,
        )

    def test_refusing_to_overwrite_a_version_changed_in_place_by_somebody_else(self):
        # Bob's second save within ten minutes changes his version
        operations.update_doc(self.doc, actor=self.bob, content="Bob's")
        base = self.versions()[0].pk
        operations.update_doc(self.doc, actor=self.bob, content="Bob's newer")
        with self.assertRaises(operations.DocConflict):
            operations.update_doc(
                self.doc, actor=self.ada, content="Ada's", base_version=base
            )
        self.doc.doc.refresh_from_db()
        self.assertEqual(self.doc.doc.content, "Bob's newer")

    def type(self, user, text):
        doc = self.doc.doc
        if not LiveState.objects.filter(doc=doc).exists():
            live.prepare(doc.pk)
        live.append(doc.pk, ytext.edit(live.load(doc.pk), text), user)

    def test_refusing_to_overwrite_typing_merged_into_ones_own_version(self):
        """Bob's typing merged with Ada's into her version, within its
        window or as a new one, is somebody else's newer version for her"""
        base = self.versions()[0].pk
        self.type(self.bob, "One\n\nBob's")
        self.type(self.ada, "One!\n\nBob's")
        operations.save_live(self.doc.pk)
        self.assertEqual(self.versions()[0].created_by, self.ada)
        with self.assertRaises(operations.DocConflict) as raised:
            operations.update_doc(
                self.doc, actor=self.ada, content="Ada's", base_version=base
            )
        self.assertEqual(raised.exception.author, self.bob)
        with time_machine.travel(timezone.now() + dt.timedelta(minutes=11)):
            base = self.versions()[0].pk
            self.type(self.ada, "One!!\n\nBob's")
            self.type(self.bob, "One!!\n\nBob's too")
            operations.save_live(self.doc.pk)
            self.assertEqual(self.versions()[0].created_by, self.ada)
            with self.assertRaises(operations.DocConflict):
                operations.update_doc(
                    self.doc, actor=self.ada, content="Ada's", base_version=base
                )
            self.doc.doc.refresh_from_db()
            self.assertEqual(self.doc.doc.content, "One!!\n\nBob's too")
            # The same for Bob: the version has Ada's typing too
            with self.assertRaises(operations.DocConflict) as raised:
                operations.update_doc(
                    self.doc, actor=self.bob, content="Bob's", base_version=base
                )
            self.assertEqual(raised.exception.author, self.ada)

    def test_a_newer_version_by_the_same_person_is_no_conflict(self):
        base = self.versions()[0].pk
        operations.update_doc(self.doc, actor=self.ada, content="Two", new_version=True)
        operations.update_doc(
            self.doc, actor=self.ada, content="Three", base_version=base
        )
        self.doc.doc.refresh_from_db()
        self.assertEqual(self.doc.doc.content, "Three")

    def test_attachments_are_linked(self):
        attachment = attachments.upload(
            project=self.project, file=file("a.png", b"x"), uploaded_by=self.bob
        )
        operations.update_doc(self.doc, actor=self.bob, content=attachment.markdown)
        attachment.refresh_from_db()
        self.assertEqual(attachment.item, self.doc)

    def test_doc_versions_are_not_items(self):
        self.assertEqual(DocVersion.objects.count(), 1)
        self.assertEqual(Item.objects.filter(kind=Kind.DOC).count(), 1)


class UploadTest(Fixture, TestCase):
    def test_create(self):
        item = ops.create_upload(
            project=self.project,
            file=file("Plan v1.pdf"),
            creator=self.ada,
            description="The plan",
        )
        self.assertEqual(item.kind, Kind.FILE)
        self.assertEqual(item.title, "Plan v1.pdf")
        self.assertEqual(item.detail.description, "The plan")
        (version,) = item.upload.versions.all()
        self.assertEqual(version.content_type, "application/pdf")
        self.assertEqual(version.size, 8)
        self.assertTrue(
            version.file.name.startswith(f"files/{self.project.pk}/")
            and version.file.name.endswith("/Plan_v1.pdf")
        )
        self.assertTrue(version.is_inline)
        self.assertTrue(version.has_preview)

    def test_the_type_comes_from_the_name(self):
        item = ops.create_upload(
            project=self.project,
            file=file("page.html", b"<script>"),
            creator=self.ada,
        )
        version = item.upload.versions.get()
        self.assertEqual(version.content_type, "text/html")
        self.assertFalse(version.is_inline)
        self.assertFalse(version.has_preview)

    def test_size_limit(self):
        big = file("big.bin", b"x")
        big.size = MAX_SIZE + 1
        with self.assertRaises(attachments.UploadError):
            ops.create_upload(project=self.project, file=big, creator=self.ada)
        self.assertFalse(Item.objects.filter(kind=Kind.FILE).exists())

    def test_in_a_folder_and_notifying(self):
        folder = ops.create_folder(
            project=self.project, title="Specs", creator=self.ada, visible=True
        )
        told = self.told(
            lambda: ops.create_upload(
                project=self.project,
                file=file(),
                creator=self.ada,
                parent=folder,
                visible=True,
            )
        )
        self.assertEqual(told, {self.bob, self.cleo})
        item = Item.objects.get(kind=Kind.FILE)
        self.assertEqual(item.parent, folder)
        # Nested files inherit the visibility, they have no switch
        self.assertTrue(item.is_client_visible)
        self.assertFalse(item.visible_to_clients)

    def test_files_cannot_hold_children(self):
        item = ops.create_upload(project=self.project, file=file(), creator=self.ada)
        with self.assertRaises(ValidationError):
            ops.create_folder(
                project=self.project, title="x", creator=self.ada, parent=item
            )

    def test_replacing_keeps_the_item_and_the_comments(self):
        item = ops.create_upload(project=self.project, file=file(), creator=self.ada)
        ops.add_comment(item, author=self.bob, content="Nice")
        version = operations.replace_upload(
            item, file("plan-v2.pdf", b"%PDF-2"), actor=self.bob
        )
        self.assertEqual(version.uploaded_by, self.bob)
        names = [v.name for v in item.upload.versions.all()]
        self.assertEqual(names, ["plan-v2.pdf", "plan.pdf"])
        self.assertEqual(item.comments.count(), 1)
        self.assertEqual(Item.objects.filter(kind=Kind.FILE).count(), 1)

    def test_update(self):
        item = ops.create_upload(project=self.project, file=file(), creator=self.ada)
        operations.update_upload(
            item, actor=self.ada, title="The plan", description="New"
        )
        item.refresh_from_db()
        self.assertEqual(item.title, "The plan")
        self.assertEqual(item.upload.description, "New")

    def test_deleting_the_item_deletes_the_files(self):
        item = ops.create_upload(project=self.project, file=file(), creator=self.ada)
        operations.replace_upload(item, file("v2.pdf"), actor=self.ada)
        versions = list(item.upload.versions.all())
        storage = versions[0].file.storage
        names = [v.file.name for v in versions]
        self.assertTrue(all(storage.exists(name) for name in names))
        with self.captureOnCommitCallbacks(execute=True):
            item.delete()
        self.assertFalse(any(storage.exists(name) for name in names))
        self.assertFalse(FileVersion.objects.exists())


class MoveTest(Fixture, TestCase):
    def setUp(self):
        super().setUp()
        self.public = ops.create_folder(
            project=self.project, title="Public", creator=self.ada, visible=True
        )
        self.private = ops.create_folder(
            project=self.project, title="Private", creator=self.ada
        )
        self.doc = bare_doc(
            project=self.project, title="Notes", creator=self.ada, parent=self.private
        )
        self.file = ops.create_upload(
            project=self.project, file=file(), creator=self.ada, parent=self.private
        )

    def test_moving_a_folder_changes_the_visibility_of_its_contents(self):
        self.assertFalse(self.doc.is_client_visible)
        ops.move_item(self.private, parent=self.public, actor=self.ada)
        for item in [self.private, self.doc, self.file]:
            item.refresh_from_db()
            self.assertTrue(item.is_client_visible, item)
        self.assertEqual(visibility.check(), [])
        ops.move_item(self.private, parent=None, actor=self.ada)
        for item in [self.private, self.doc, self.file]:
            item.refresh_from_db()
            self.assertFalse(item.is_client_visible, item)
        self.assertEqual(visibility.check(), [])

    def test_moving_resets_the_switch_when_nested(self):
        ops.set_visibility(self.private, visible=True, actor=self.ada)
        ops.move_item(self.private, parent=self.public, actor=self.ada)
        self.private.refresh_from_db()
        self.assertFalse(self.private.visible_to_clients)
        self.assertTrue(self.private.is_client_visible)

    def test_a_folder_cannot_move_into_itself(self):
        child = ops.create_folder(
            project=self.project, title="Child", creator=self.ada, parent=self.private
        )
        for parent in [self.private, child]:
            with self.assertRaises(ValueError):
                ops.move_item(self.private, parent=parent, actor=self.ada)

    def test_files_and_docs_only_go_into_folders(self):
        message = ops.create_message(project=self.project, title="Hi", creator=self.ada)
        with self.assertRaises(ValidationError):
            ops.move_item(self.doc, parent=message, actor=self.ada)
        with self.assertRaises(ValidationError):
            ops.move_item(self.file, parent=self.doc, actor=self.ada)
