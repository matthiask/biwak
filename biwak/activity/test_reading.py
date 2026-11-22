"""Reading by acting (specs/lantern.md): the strong signals read the actor's
notifications of the item, and nothing else does"""

import datetime as dt

from django.urls import reverse
from django.utils import timezone

from biwak.activity import lantern
from biwak.activity.mails import send_mails
from biwak.activity.models import Action, Event, Notification
from biwak.activity.operations import importing, subscribe
from biwak.activity.test_lantern import LanternTestCase
from biwak.bookmarks.operations import add_bookmark
from biwak.checkins import operations as checkin_ops
from biwak.files import operations as file_ops
from biwak.items import operations as ops
from biwak.items.models import Comment
from biwak.reactions.operations import add_reaction, remove_reaction, toggle_reaction
from biwak.test_utils import bare_doc, check_in_answers, person


class ReadingTestCase(LanternTestCase):
    def setUp(self):
        super().setUp()
        self.dan = person("Dan")

    def prime(self, item):
        """Dan comments: Ada, Bob (and Cleo, where she sees it) have an unread
        notification about the item (an edit by him where there are no comments)"""
        for user in [self.ada, self.bob, self.cleo]:
            if lantern_sees(user, item):
                subscribe(user, item)
        if item.is_commentable:
            self.comment(item, "From Dan", author=self.dan)
            return
        event = Event.objects.create(
            actor=self.dan,
            action=Action.EDITED,
            project=self.project,
            item=item,
            data={},
        )
        for user in [self.ada, self.bob]:
            Notification.objects.create(user=user, event=event)

    def unread(self, user, item):
        return (
            lantern
            .notifications_for(user, unread=True)
            .filter(event__item=item)
            .count()
        )

    def assertReadFor(self, actor, item, others=()):
        self.assertEqual(self.unread(actor, item), 0, f"{actor} still has unread")
        for other in others:
            self.assertGreater(self.unread(other, item), 0, f"{other} read too")


def lantern_sees(user, item):
    from biwak.items.models import Item

    return Item.objects.visible_to(user).filter(pk=item.pk).exists()


class ActionsReadTest(ReadingTestCase):
    def check(self, item, run, *, actor=None):
        actor = actor or self.ada
        self.prime(item)
        other = self.secret if item != self.secret else self.todo
        self.prime(other)
        before = self.unread(actor, other)
        self.act(lambda: run(actor))
        self.assertEqual(self.unread(actor, item), 0)
        self.assertGreater(self.unread(self.bob, item), 0)
        self.assertEqual(self.unread(actor, other), before)
        self.assertGreater(before, 0)

    def test_complete(self):
        self.check(self.todo, lambda a: ops.complete(self.todo, actor=a))

    def test_reopen(self):
        ops.complete(self.todo, actor=self.dan)
        self.check(self.todo, lambda a: ops.reopen(self.todo, actor=a))

    def test_update_todo(self):
        for fields in [
            {"title": "New"},
            {"notes": "Notes"},
            {"due_on": dt.date(2027, 5, 1)},
            {"assignees": [self.bob]},
            {"recurrence": "FREQ=WEEKLY"},
        ]:
            with self.subTest(fields=fields):
                self.check(
                    self.todo,
                    lambda a, fields=fields: ops.update_todo(
                        self.todo, actor=a, **fields
                    ),
                )

    def test_tick_in_a_todo(self):
        self.act(lambda: ops.update_todo(self.todo, actor=self.dan, notes="- [ ] One"))
        from biwak import checklists

        self.check(
            self.todo,
            lambda a: ops.tick(
                self.todo, actor=a, index=0, version=checklists.text_hash("- [ ] One")
            ),
        )

    def test_tick_in_a_comment(self):
        comment = self.comment(self.todo, "- [ ] One", author=self.ada)
        from biwak import checklists

        self.check(
            self.todo,
            lambda a: ops.tick(
                self.todo,
                actor=a,
                index=0,
                version=checklists.text_hash(comment.content),
                comment=comment,
            ),
        )

    def test_tick_in_a_doc(self):
        from biwak import checklists

        doc = bare_doc(
            project=self.project, title="Notes", creator=self.ada, content="- [ ] One"
        )
        self.check(
            doc,
            lambda a: ops.tick(
                doc, actor=a, index=0, version=checklists.text_hash("- [ ] One")
            ),
        )

    def test_comment_on_every_kind(self):
        message = ops.create_message(
            project=self.project, title="News", content="", creator=self.ada
        )
        doc = ops.create_doc(project=self.project, title="Notes", creator=self.ada)
        (answer,) = check_in_answers(self.project, [self.dan])
        for item in [self.todo, message, doc, answer]:
            with self.subTest(item=item.kind):
                self.check(
                    item,
                    lambda a, item=item: ops.add_comment(
                        item, author=a, content="Mine"
                    ),
                )

    def test_react_to_the_item(self):
        self.check(self.todo, lambda a: add_reaction(a, "👍", item=self.todo))

    def test_toggle_reaction(self):
        self.check(self.todo, lambda a: toggle_reaction(a, "👍", item=self.todo))

    def test_react_to_a_comment(self):
        self.prime(self.todo)
        comment = Comment.objects.filter(item=self.todo).first()
        self.check(self.todo, lambda a: add_reaction(a, "👍", comment=comment))

    def test_answering_a_question(self):
        """The question's notifications and those of the person's answer"""
        from biwak.checkins.support import MONDAY_9, at

        question = checkin_ops.create_question(
            project=self.project,
            title="How is the camp?",
            creator=self.ada,
            people=[self.ada, self.bob],
            now=at("2027-03-19 12:00"),
            **MONDAY_9,
        )
        checkin_ops.run(now=at("2027-03-22 09:00"))
        answer = checkin_ops.answer(question, user=self.ada, content="Fine")
        self.prime(answer)
        self.act(lambda: checkin_ops.answer(question, user=self.ada, content="Fine!"))
        self.assertReadFor(self.ada, answer, others=[self.bob])
        # Somebody else's answer to the same question isn't read
        theirs = checkin_ops.answer(question, user=self.bob, content="Cold")
        self.prime(theirs)
        self.act(lambda: checkin_ops.answer(question, user=self.ada, content="Fine!!"))
        self.assertGreater(self.unread(self.ada, theirs), 0)

    def test_a_client_acting_reads_her_notifications(self):
        self.prime(self.todo)
        self.assertGreater(self.unread(self.cleo, self.todo), 0)
        self.act(lambda: ops.add_comment(self.todo, author=self.cleo, content="Hello"))
        self.assertEqual(self.unread(self.cleo, self.todo), 0)
        self.assertGreater(self.unread(self.bob, self.todo), 0)

    def test_an_internal_notification_of_the_client_stays(self):
        """A notification the client has about the todo from a time it was
        internal isn't hers to see, so acting doesn't read it"""
        self.prime(self.todo)
        internal = Notification.objects.create(
            user=self.cleo,
            event=self.comment_event(self.todo),
        )
        type(internal.event).objects.filter(pk=internal.event_id).update(
            is_client_visible=False
        )
        self.act(lambda: ops.add_comment(self.todo, author=self.cleo, content="Hello"))
        internal.refresh_from_db()
        self.assertIsNone(internal.read_at)

    def comment_event(self, item):
        from biwak.activity.models import Action, Event

        return Event.objects.create(
            actor=self.dan,
            action=Action.COMMENTED,
            project=self.project,
            item=item,
            data={},
        )


class NotSignalsTest(ReadingTestCase):
    def test_nothing_else_reads(self):
        self.prime(self.todo)
        self.prime(self.secret)
        other = ops.create_todo(todolist=self.shared, title="Other", creator=self.ada)
        before = self.unread(self.ada, self.todo)
        self.assertGreater(before, 0)
        remove_reaction(self.ada, "👍", item=self.todo)
        self.act(lambda: add_bookmark(self.ada, item=self.todo))
        self.act(lambda: subscribe(self.ada, self.todo))
        self.act(lambda: ops.move_todo(self.todo, todolist=self.shared, actor=self.ada))
        self.act(lambda: ops.set_visibility(self.shared, visible=False, actor=self.ada))
        self.act(lambda: ops.set_visibility(self.shared, visible=True, actor=self.ada))
        self.act(lambda: ops.update_list(self.shared, actor=self.ada, title="Renamed"))
        self.act(
            lambda: ops.update_todo(self.todo, actor=self.ada, title=self.todo.title)
        )
        self.act(lambda: ops.complete(other, actor=self.ada))
        self.assertEqual(self.unread(self.ada, self.todo), before)
        self.assertGreater(self.unread(self.ada, self.secret), 0)

    def test_completing_twice_changes_nothing_the_second_time(self):
        ops.complete(self.todo, actor=self.dan)
        self.prime(self.todo)
        self.act(lambda: ops.complete(self.todo, actor=self.ada))
        self.assertGreater(self.unread(self.ada, self.todo), 0)

    def test_the_importer_reads_nothing(self):
        self.prime(self.todo)
        before = self.unread(self.ada, self.todo)
        with importing():
            ops.update_todo(self.todo, actor=self.ada, title="Imported")
            ops.add_comment(self.todo, author=self.ada, content="Imported")
            ops.complete(self.todo, actor=self.ada)
            ops.reopen(self.todo, actor=self.ada)
        self.assertEqual(self.unread(self.ada, self.todo), before)

    def test_the_next_recurring_todo_reads_nothing(self):
        recurring = ops.create_todo(
            todolist=self.shared,
            title="Weekly",
            creator=self.ada,
            due_on=timezone.localdate(),
            recurrence="FREQ=WEEKLY",
        )
        ops.update_todo(recurring, actor=self.ada, assignees=[self.ada, self.bob])
        self.act(lambda: ops.complete(recurring, actor=self.bob))
        following = recurring.following.get().item
        # Bob acted: his notifications of the completed one are read;
        # the new one's (Ada's assignment) is untouched
        self.assertEqual(self.unread(self.bob, recurring), 0)
        self.assertGreater(self.unread(self.ada, following), 0)


class MailsTest(ReadingTestCase):
    def test_send_mails_skips_what_acting_read(self):
        self.prime(self.todo)
        self.prime(self.secret)
        self.act(lambda: ops.complete(self.todo, actor=self.bob))
        with self.captureOnCommitCallbacks(execute=True):
            send_mails(now=timezone.now() + dt.timedelta(minutes=11))
        from django.core import mail

        bobs = [m for m in mail.outbox if m.to == [self.bob.email]]
        self.assertEqual([m.subject for m in bobs], ["[Website] Budget"])
        self.assertTrue([m for m in mail.outbox if m.to == [self.ada.email]])


class EntryPointsTest(ReadingTestCase):
    """Pages and the API go through the operations, so they read alike"""

    def test_the_page_toggle(self):
        self.prime(self.todo)
        self.client.force_login(self.ada)
        self.act(
            lambda: self.client.post(
                reverse("todo_toggle", args=[self.todo.pk]), {"done": "1"}
            )
        )
        self.assertReadFor(self.ada, self.todo, others=[self.bob])

    def test_the_api(self):
        from biwak.accounts.models import APIToken

        self.prime(self.todo)
        _token, secret = APIToken.create_for(user=self.ada, title="T", access="write")
        headers = {"authorization": f"Bearer {secret}"}
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/api/v1/todos/{self.todo.pk}/complete/",
                content_type="application/json",
                headers=headers,
            )
        self.assertEqual(response.status_code, 200)
        self.assertReadFor(self.ada, self.todo, others=[self.bob])

    def test_viewing_the_page_reads_nothing(self):
        self.prime(self.todo)
        self.client.force_login(self.ada)
        self.assertEqual(self.client.get(self.todo.get_absolute_url()).status_code, 200)
        self.assertGreater(self.unread(self.ada, self.todo), 0)


class EditsTest(ReadingTestCase):
    """Editing reads like changing a to-do's fields: when something
    changed, for the editor only; saving the same values reads nothing"""

    def edits(self, item, change, same):
        self.prime(item)
        before = self.unread(self.ada, item)
        self.assertGreater(before, 0)
        self.act(lambda: same(self.ada))
        self.assertEqual(self.unread(self.ada, item), before, "unchanged read")
        self.act(lambda: change(self.ada))
        self.assertReadFor(self.ada, item, others=[self.bob])

    def test_message(self):
        for kwargs in [{"title": "New"}, {"content": "New"}]:
            with self.subTest(kwargs=kwargs):
                Notification.objects.all().delete()
                message = ops.create_message(
                    project=self.project, title="News", content="Text", creator=self.dan
                )
                self.edits(
                    message,
                    lambda a, message=message, kwargs=kwargs: file_ops.update_message(
                        message, actor=a, **kwargs
                    ),
                    lambda a, message=message: file_ops.update_message(
                        message, actor=a, title="News", content="Text"
                    ),
                )

    def test_upload(self):
        from django.core.files.base import ContentFile

        upload = ops.create_upload(
            project=self.project,
            file=ContentFile(b"%PDF-1.4", name="plan.pdf"),
            creator=self.dan,
            description="Plan",
        )
        self.edits(
            upload,
            lambda a: file_ops.update_upload(upload, actor=a, description="New"),
            lambda a: file_ops.update_upload(upload, actor=a, description="Plan"),
        )
        Notification.objects.all().delete()
        self.prime(upload)
        self.act(
            lambda: file_ops.replace_upload(
                upload, ContentFile(b"%PDF-1.5", name="plan.pdf"), actor=self.ada
            )
        )
        self.assertReadFor(self.ada, upload, others=[self.bob])

    def test_doc(self):
        doc = bare_doc(
            project=self.project, title="Notes", creator=self.dan, content="Text"
        )
        self.edits(
            doc,
            lambda a: file_ops.update_doc(doc, actor=a, content="New"),
            lambda a: file_ops.update_doc(doc, actor=a, content="Text"),
        )

    def test_doc_renamed(self):
        doc = ops.create_doc(
            project=self.project, title="Notes", creator=self.dan, content="Text"
        )
        self.edits(
            doc,
            # The title is the text's first line (specs/doc-titles.md)
            lambda a: file_ops.update_doc(doc, actor=a, content="# Minutes\n\nText"),
            lambda a: file_ops.update_doc(doc, actor=a, content="# Notes\n\nText"),
        )

    def test_doc_typed_live_and_saved(self):
        """What's typed in the editor is saved with its typists as authors
        (``save_live()``, no actor): each of them edited the doc"""
        from biwak.collab import live, ytext

        doc = ops.create_doc(
            project=self.project, title="Notes", creator=self.dan, content="Text"
        )
        self.prime(doc)
        live.prepare(doc.doc.pk)
        state = live.load(doc.doc.pk)
        live.append(doc.doc.pk, ytext.edit(state, "Text, typed"), self.ada)
        before = self.unread(self.ada, doc)
        self.assertGreater(before, 0)
        self.assertGreater(self.unread(self.bob, doc), 0)
        # Typing alone reads nothing, saving does
        self.assertEqual(self.unread(self.ada, doc), before)
        with self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(file_ops.save_live(doc.doc.pk))
        self.assertReadFor(self.ada, doc, others=[self.bob])
        # Nothing typed since: nothing to save, nothing read
        self.comment(doc, "Again", author=self.dan)
        with self.captureOnCommitCallbacks(execute=True):
            self.assertFalse(file_ops.save_live(doc.doc.pk))
        self.assertGreater(self.unread(self.ada, doc), 0)

    def test_saving_a_version_without_changes_reads_nothing(self):
        doc = ops.create_doc(
            project=self.project, title="Notes", creator=self.dan, content="Text"
        )
        self.prime(doc)
        before = self.unread(self.ada, doc)
        self.act(lambda: file_ops.save_version(doc, actor=self.ada))
        self.assertEqual(self.unread(self.ada, doc), before)

    def test_list(self):
        self.edits(
            self.shared,
            lambda a: ops.update_list(self.shared, actor=a, title="Renamed"),
            lambda a: ops.update_list(self.shared, actor=a, title="Shared"),
        )

    def test_answer_and_question(self):
        from biwak.checkins.support import MONDAY_9, at

        question = checkin_ops.create_question(
            project=self.project,
            title="How is the camp?",
            creator=self.ada,
            people=[self.ada, self.bob],
            now=at("2027-03-19 12:00"),
            **MONDAY_9,
        )
        checkin_ops.run(now=at("2027-03-22 09:00"))
        answer = checkin_ops.answer(question, user=self.ada, content="Fine")
        self.edits(
            answer,
            lambda a: checkin_ops.update_answer(answer.answer, "Better", actor=a),
            lambda a: checkin_ops.update_answer(answer.answer, "Fine", actor=a),
        )
        Notification.objects.all().delete()
        self.edits(
            question,
            lambda a: checkin_ops.update_question(question, actor=a, title="Camp?"),
            lambda a: checkin_ops.update_question(
                question, actor=a, title="How is the camp?"
            ),
        )

    def test_the_importer_reads_nothing(self):
        message = ops.create_message(
            project=self.project, title="News", content="Text", creator=self.dan
        )
        self.prime(message)
        before = self.unread(self.ada, message)
        with importing():
            file_ops.update_message(message, actor=self.ada, content="Imported")
        self.assertEqual(self.unread(self.ada, message), before)
