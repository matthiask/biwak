"""The timeline on messages, docs and files (specs/timeline.md, decided
2026-11-23): edits after the first comment, the switch, moves between
folders, the trash"""

import datetime as dt

from django.core.files.base import ContentFile
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from biwak.accounts.models import APIToken
from biwak.activity.models import Action, Event
from biwak.activity.test_timeline import region
from biwak.collab import live
from biwak.files import operations as files_ops
from biwak.items import operations as ops
from biwak.items.models import Comment, MessageCategory
from biwak.test_utils import person, project


def ago(minutes):
    return timezone.now() - dt.timedelta(minutes=minutes)


class ItemTimelineBase(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.bob, self.cleo])
        self.message = ops.create_message(
            project=self.project,
            title="Kick-off",
            content="Monday at nine",
            creator=self.ada,
            visible=True,
        )
        self.doc = ops.create_doc(
            project=self.project,
            title="Brief",
            content="The tent",
            creator=self.ada,
            visible=True,
        )
        Event.objects.all().delete()

    def html(self, item, user=None):
        self.client.force_login(user or self.ada)
        response = self.client.get(item.get_absolute_url())
        self.assertEqual(response.status_code, 200)
        return response

    def lines(self, item, user=None):
        return region(self.html(item, user))

    def comment(self, item, minutes=30):
        """A comment some time ago: what comes later may refer to it"""
        comment = ops.add_comment(item, author=self.bob, content="Sounds good")
        Comment.objects.filter(pk=comment.pk).update(created_at=ago(minutes))
        return comment

    def age(self, action, minutes):
        Event.objects.filter(action=action).update(created_at=ago(minutes))

    def type(self, item, text, user=None):
        """Typing in the live editor, saved like the editor saves"""
        item.refresh_from_db()
        with self.captureOnCommitCallbacks(execute=True):
            live.apply_text(item.doc, text, user=user or self.ada)
            files_ops.save_live(item.pk)


class MessageTest(ItemTimelineBase):
    def test_edits_before_the_first_comment_are_not_shown(self):
        # Nobody can have referred to the old text yet
        files_ops.update_message(self.message, actor=self.ada, title="Kick-off!")
        self.assertEqual(self.lines(self.message), [])

    def test_an_edit_after_a_comment(self):
        self.comment(self.message)
        files_ops.update_message(self.message, actor=self.ada, content="Monday at ten")
        (line,) = self.lines(self.message)
        self.assertTrue(line.startswith("Ada edited this ·"), line)

    def test_a_category_alone_is_no_edit_of_the_text(self):
        self.comment(self.message)
        category = MessageCategory.objects.create(name="News")
        files_ops.update_message(self.message, actor=self.ada, category=category)
        self.assertEqual(self.lines(self.message), [])

    def test_the_history_link_for_staff_only(self):
        self.comment(self.message)
        files_ops.update_message(self.message, actor=self.ada, title="Kick-off!")
        link = f'<a href="/items/{self.message.pk}/history/">edited this</a>'
        self.assertContains(self.html(self.message), link, count=1)
        response = self.html(self.message, self.cleo)
        self.assertNotContains(response, "/history/")
        (line,) = region(response)
        self.assertTrue(line.startswith("Ada edited this ·"), line)

    def test_shown_to_clients_and_made_internal(self):
        ops.set_visibility(self.message, visible=False, actor=self.ada)
        self.age(Action.VISIBILITY_CHANGED, 60)
        ops.set_visibility(self.message, visible=True, actor=self.bob)
        first, second = self.lines(self.message)
        self.assertTrue(first.startswith("Ada made this internal"), first)
        self.assertTrue(second.startswith("Bob showed this to clients"), second)

    def test_shown_and_hidden_again_is_no_line(self):
        ops.set_visibility(self.message, visible=False, actor=self.ada)
        ops.set_visibility(self.message, visible=True, actor=self.ada)
        self.assertEqual(self.lines(self.message), [])

    def test_the_same_person_within_ten_minutes_is_one_line(self):
        self.comment(self.message)
        files_ops.update_message(self.message, actor=self.ada, title="Kick-off!")
        ops.set_visibility(self.message, visible=False, actor=self.ada)
        (line,) = self.lines(self.message)
        self.assertIn("Ada edited this and made it internal", line)

    def test_a_comment_in_between_breaks_it(self):
        self.comment(self.message)
        files_ops.update_message(self.message, actor=self.ada, title="Kick-off!")
        self.age(Action.EDITED, 5)
        self.comment(self.message, minutes=3)
        ops.set_visibility(self.message, visible=False, actor=self.ada)
        lines = self.lines(self.message)
        self.assertEqual(len(lines), 2)
        self.assertIn("edited this", lines[0])
        self.assertIn("made this internal", lines[1])

    def test_a_client_sees_nothing_of_the_time_it_was_internal(self):
        message = ops.create_message(
            project=self.project, title="Rates", content="Draft", creator=self.ada
        )
        self.comment(message, minutes=90)
        files_ops.update_message(message, actor=self.ada, content="Internal draft")
        self.age(Action.EDITED, 80)
        ops.set_visibility(message, visible=True, actor=self.ada)
        self.age(Action.VISIBILITY_CHANGED, 60)
        files_ops.update_message(message, actor=self.bob, content="For Cleo")
        self.age(Action.EDITED, 50)
        ops.set_visibility(message, visible=False, actor=self.ada)
        files_ops.update_message(message, actor=self.ada, content="Internal again")
        Event.objects.filter(
            action__in=[Action.VISIBILITY_CHANGED, Action.EDITED], created_at__gt=ago(1)
        ).update(created_at=ago(30))
        ops.set_visibility(message, visible=True, actor=self.ada)
        staff = self.lines(message)
        self.assertEqual(len(staff), 5, staff)
        self.assertIn("Ada made this internal", staff[3])
        client = self.lines(message, self.cleo)
        self.assertEqual(len(client), 3, client)
        self.assertTrue(client[0].startswith("Ada showed this to clients"), client)
        self.assertTrue(client[1].startswith("Bob edited this"), client)
        self.assertTrue(client[2].startswith("Ada showed this to clients"), client)
        self.assertNotIn("internal", " ".join(client))

    def test_a_line_is_a_live_region(self):
        self.comment(self.message)
        files_ops.update_message(self.message, actor=self.ada, title="Kick-off!")
        event = Event.objects.get(action=Action.EDITED)
        html = self.html(self.message).content.decode()
        self.assertIn(f'id="event-{event.pk}" data-live', html)
        self.assertLess(html.index('id="live-comments"'), html.index("event-"))


class DocTest(ItemTimelineBase):
    def setUp(self):
        super().setUp()
        self.minutes = ops.create_folder(
            project=self.project, title="Minutes", creator=self.ada, visible=True
        )
        self.briefs = ops.create_folder(
            project=self.project, title="Briefs", creator=self.ada, visible=True
        )
        Event.objects.all().delete()

    def test_writing_a_new_doc_is_not_told(self):
        draft = ops.create_draft(project=self.project, creator=self.ada)
        self.type(draft, "# Plan\n\nFirst")
        self.type(draft, "# Plan\n\nFirst and second")
        draft.refresh_from_db()
        self.assertFalse(draft.is_draft)
        self.assertEqual(self.lines(draft), [])

    def test_a_live_editing_session_is_one_line_per_person(self):
        self.comment(self.doc)
        for text in ["The tent", "The tent and", "The tent and the pegs"]:
            self.type(self.doc, f"# Brief\n\n{text}")
        self.type(self.doc, "# Brief\n\nThe tent and the pegs!", self.bob)
        lines = self.lines(self.doc)
        self.assertEqual(len(lines), 2, lines)
        self.assertTrue(lines[0].startswith("Ada edited this"), lines)
        self.assertTrue(lines[1].startswith("Bob edited this"), lines)

    def test_saving_a_version_alone_is_no_line(self):
        self.comment(self.doc)
        files_ops.save_version(self.doc, actor=self.ada)
        self.assertEqual(self.lines(self.doc), [])

    def test_moved_between_folders(self):
        ops.move_item(self.doc, parent=self.minutes, actor=self.ada)
        self.age(Action.MOVED, 60)
        ops.move_item(self.doc, parent=self.briefs, actor=self.bob)
        first, second = self.lines(self.doc)
        self.assertTrue(first.startswith("Ada moved this to Minutes"), first)
        self.assertTrue(second.startswith("Bob moved this to Briefs"), second)
        client = self.lines(self.doc, self.cleo)
        self.assertEqual(len(client), 2, client)
        self.assertIn("Bob moved this to Briefs", client[1])

    def test_out_of_its_folder(self):
        ops.move_item(self.doc, parent=self.minutes, actor=self.ada)
        self.age(Action.MOVED, 60)
        ops.move_item(self.doc, parent=None, actor=self.ada)
        self.assertIn("Ada moved this out of its folder", self.lines(self.doc)[1])

    def test_moved_and_moved_back_is_no_line(self):
        ops.move_item(self.doc, parent=self.minutes, actor=self.ada)
        ops.move_item(self.doc, parent=self.briefs, actor=self.ada)
        ops.move_item(self.doc, parent=None, actor=self.ada)
        self.assertEqual(self.lines(self.doc), [])

    def test_folders_the_viewer_cant_see(self):
        secret = ops.create_folder(
            project=self.project, title="Secret", creator=self.ada
        )
        ops.move_item(self.doc, parent=self.minutes, actor=self.ada)
        ops.move_item(self.doc, parent=secret, actor=self.ada)
        # As if the folder's switch had changed meanwhile
        Event.objects.update(is_client_visible=True, created_at=ago(30))
        ops.move_item(self.doc, parent=self.minutes, actor=self.bob)
        self.assertIn("moved this to Secret", self.lines(self.doc)[0])
        client = self.lines(self.doc, self.cleo)
        self.assertIn("Ada moved this to another folder", client[0])
        self.assertNotIn("Secret", " ".join(client))

    def test_older_moves_say_moved(self):
        ops.move_item(self.doc, parent=self.minutes, actor=self.ada)
        Event.objects.update(data={})
        self.assertIn("Ada moved this", self.lines(self.doc)[0])

    def test_trashed_and_restored(self):
        ops.trash(self.doc, actor=self.ada)
        self.age(Action.TRASHED, 60)
        ops.restore(self.doc, actor=self.bob)
        first, second = self.lines(self.doc)
        self.assertIn("Ada trashed this", first)
        self.assertIn("Bob restored this", second)

    def test_a_client_sees_no_edits_from_when_it_was_internal(self):
        doc = ops.create_doc(
            project=self.project, title="Offer", content="Rates", creator=self.ada
        )
        self.comment(doc, minutes=90)
        self.type(doc, "# Offer\n\nOur rates")
        self.age(Action.EDITED, 60)
        ops.set_visibility(doc, visible=True, actor=self.ada)
        response = self.html(doc)
        staff = region(response)
        self.assertTrue(staff[0].startswith("Ada edited this"), staff)
        self.assertTrue(staff[1].startswith("Ada showed this to clients"), staff)
        self.assertContains(response, f'href="/items/{doc.pk}/history/">edited')
        response = self.html(doc, self.cleo)
        (line,) = region(response)
        self.assertTrue(line.startswith("Ada showed this to clients"), line)
        self.assertNotContains(response, "/history/")

    def test_no_query_per_line(self):
        self.comment(self.doc, minutes=200)

        def count():
            self.client.force_login(self.ada)
            self.client.get(self.doc.get_absolute_url())
            with CaptureQueriesContext(connection) as queries:
                self.client.get(self.doc.get_absolute_url())
            return len(queries)

        ops.move_item(self.doc, parent=self.minutes, actor=self.ada)
        self.age(Action.MOVED, 150)
        few = count()
        for n, folder in enumerate([self.briefs, self.minutes] * 3):
            self.type(self.doc, f"# Brief\n\nVersion {n}")
            ops.move_item(self.doc, parent=folder, actor=self.bob)
            ops.add_comment(self.doc, author=self.ada, content=f"Comment {n}")
            Event.objects.filter(created_at__gt=ago(1)).update(
                created_at=ago(100 - n * 11)
            )
        self.assertEqual(len(self.lines(self.doc)), 13)
        self.assertEqual(count(), few)


class FileTest(ItemTimelineBase):
    def setUp(self):
        super().setUp()
        self.upload = ops.create_upload(
            project=self.project,
            file=ContentFile(b"one", name="plan.pdf"),
            creator=self.ada,
            visible=True,
        )
        Event.objects.all().delete()

    def test_a_new_version_and_a_new_name(self):
        self.comment(self.upload)
        files_ops.replace_upload(
            self.upload, ContentFile(b"two", name="plan-2.pdf"), actor=self.ada
        )
        (line,) = self.lines(self.upload)
        self.assertTrue(line.startswith("Ada uploaded a new version"), line)
        files_ops.update_upload(self.upload, actor=self.ada, title="Final plan.pdf")
        (line,) = self.lines(self.upload)
        self.assertIn("Ada edited this and uploaded a new version", line)


class APITest(ItemTimelineBase):
    def test_the_folders_ids_are_for_the_timeline_only(self):
        folder = ops.create_folder(
            project=self.project, title="Minutes", creator=self.ada, visible=True
        )
        ops.move_item(self.doc, parent=folder, actor=self.ada)
        self.assertEqual(
            Event.objects.get(action=Action.MOVED).data["folder_id"], folder.pk
        )
        for user in [self.ada, self.cleo]:
            _token, secret = APIToken.create_for(user=user, title="T", access="read")
            results = self.client.get(
                "/api/v1/feed/", headers={"authorization": f"Bearer {secret}"}
            ).json()["results"]
            moved = next(e for e in results if e["action"] == "moved")
            self.assertNotIn("folder_id", moved["data"])
            self.assertNotIn("folder_was", moved["data"])
