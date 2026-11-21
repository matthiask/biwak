"""Task lists: counts stored with the text, ticking through the operations
(specs/editor.md)"""

from importlib import import_module

from django.apps import apps
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.test import TestCase

from biwak import checklists
from biwak.activity.models import Action, Event
from biwak.audit.models import LoggedAction
from biwak.checkins import operations as checkin_ops
from biwak.items import operations as ops
from biwak.items.models import Doc, Kind, Message, Todo, Upload
from biwak.test_utils import check_in_answers, person, project


TEXT = "Packing\n\n- [ ] tent\n- [x] stove\n- [ ] rope\n"


class Fixture(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.cleo])
        self.shared = ops.create_list(
            project=self.project, title="Shared", creator=self.ada, visible=True
        )
        self.todo = ops.create_todo(
            todolist=self.shared, title="Pack", creator=self.ada, notes=TEXT
        )
        self.message = ops.create_message(
            project=self.project,
            title="Camp",
            creator=self.ada,
            content=TEXT,
            visible=True,
        )

    def version(self, item):
        return checklists.text_hash(ops.text_of(item))


class CountsTest(Fixture):
    def test_counted_when_saved(self):
        self.assertEqual(
            (self.todo.todo.checklist_done, self.todo.todo.checklist_total), (1, 3)
        )
        ops.update_todo(self.todo, actor=self.ada, notes="- [x] a\n- [x] b")
        todo = Todo.objects.get(pk=self.todo.pk)
        self.assertEqual((todo.checklist_done, todo.checklist_total), (2, 2))
        ops.update_todo(self.todo, actor=self.ada, notes="no list any more")
        todo = Todo.objects.get(pk=self.todo.pk)
        self.assertEqual((todo.checklist_done, todo.checklist_total), (0, 0))

    def test_every_kind(self):
        doc = ops.create_doc(
            project=self.project, title="Doc", creator=self.ada, content=TEXT
        )
        upload = ops.create_upload(
            project=self.project,
            file=ContentFile(b"x", name="a.txt"),
            creator=self.ada,
            description=TEXT,
        )
        for model, pk in [
            (Message, self.message.pk),
            (Doc, doc.pk),
            (Upload, upload.pk),
        ]:
            row = model.objects.get(pk=pk)
            self.assertEqual((row.checklist_done, row.checklist_total), (1, 3))

    def test_data_migration_counts_existing_texts(self):
        Todo.objects.update(checklist_done=0, checklist_total=0)
        Message.objects.update(checklist_done=0, checklist_total=0)
        import_module("biwak.items.migrations.0007_checklist_counts").count_existing(
            apps, None
        )
        todo = Todo.objects.get(pk=self.todo.pk)
        self.assertEqual((todo.checklist_done, todo.checklist_total), (1, 3))
        message = Message.objects.get(pk=self.message.pk)
        self.assertEqual((message.checklist_done, message.checklist_total), (1, 3))


class TickTest(Fixture):
    def tick(self, item, actor, index=0, **kwargs):
        return ops.tick(
            item, actor=actor, index=index, version=self.version(item), **kwargs
        )

    def test_staff_ticks_a_todo(self):
        Event.objects.all().delete()
        LoggedAction.objects.all().delete()
        self.tick(self.todo, self.ada)
        todo = Todo.objects.get(pk=self.todo.pk)
        self.assertEqual(todo.notes, TEXT.replace("[ ] tent", "[x] tent"))
        self.assertEqual((todo.checklist_done, todo.checklist_total), (2, 3))
        event = Event.objects.get()
        self.assertEqual((event.action, event.item_id), (Action.EDITED, self.todo.pk))
        self.assertTrue(LoggedAction.objects.exists())

    def test_ticks_merge_into_one_event(self):
        Event.objects.all().delete()
        self.tick(self.todo, self.ada, 0)
        self.todo = type(self.todo).objects.get(pk=self.todo.pk)
        self.tick(self.todo, self.ada, 2)
        self.assertEqual(Event.objects.count(), 1)

    def test_client_ticks_a_todo_somebody_else_made(self):
        self.tick(self.todo, self.cleo)
        self.assertIn("[x] tent", Todo.objects.get(pk=self.todo.pk).notes)

    def test_client_is_refused_on_somebody_elses_message(self):
        with self.assertRaises(PermissionDenied):
            self.tick(self.message, self.cleo)
        self.assertEqual(Message.objects.get(pk=self.message.pk).content, TEXT)

    def test_client_ticks_their_own_message(self):
        own = ops.create_message(
            project=self.project, title="Mine", creator=self.cleo, content=TEXT
        )
        self.tick(own, self.cleo)
        self.assertIn("[x] tent", Message.objects.get(pk=own.pk).content)

    def test_staff_ticks_a_message(self):
        self.tick(self.message, self.ada, 1)
        self.assertIn("[ ] stove", Message.objects.get(pk=self.message.pk).content)

    def test_changed_text_is_a_conflict(self):
        stale = self.version(self.todo)
        ops.update_todo(self.todo, actor=self.ada, notes="- [ ] new")
        with self.assertRaises(ops.ChecklistConflict):
            ops.tick(self.todo, actor=self.ada, index=0, version=stale)
        self.assertEqual(Todo.objects.get(pk=self.todo.pk).notes, "- [ ] new")

    def test_missing_checkbox(self):
        with self.assertRaises(checklists.NoCheckbox):
            self.tick(self.todo, self.ada, 7)

    def test_doc_and_file_and_answer(self):
        doc = ops.create_doc(
            project=self.project, title="Doc", creator=self.ada, content=TEXT
        )
        self.tick(doc, self.ada)
        self.assertIn("[x] tent", Doc.objects.get(pk=doc.pk).content)
        upload = ops.create_upload(
            project=self.project,
            file=ContentFile(b"x", name="a.txt"),
            creator=self.ada,
            description=TEXT,
        )
        self.tick(upload, self.ada)
        self.assertIn("[x] tent", Upload.objects.get(pk=upload.pk).description)
        # Clients can't change docs and files
        with self.assertRaises(PermissionDenied):
            self.tick(doc, self.cleo)
        (answer,) = check_in_answers(self.project, [self.ada], content=TEXT)
        self.tick(answer, self.ada)
        answer.refresh_from_db()
        self.assertIn("[x] tent", checkin_ops.Answer.objects.get(pk=answer.pk).content)

    def test_other_kinds_have_no_text(self):
        with self.assertRaises(checklists.NoCheckbox):
            ops.tick(self.shared, actor=self.ada, index=0, version="")
        self.assertEqual(self.shared.kind, Kind.LIST)

    def test_comments(self):
        comment = ops.add_comment(self.todo, author=self.ada, content="- [ ] one")
        version = checklists.text_hash(comment.content)
        with self.assertRaises(PermissionDenied):
            ops.tick(
                self.todo, actor=self.cleo, index=0, version=version, comment=comment
            )
        ops.tick(self.todo, actor=self.ada, index=0, version=version, comment=comment)
        comment.refresh_from_db()
        self.assertEqual(comment.content, "- [x] one")
        with self.assertRaises(ops.ChecklistConflict):
            ops.tick(
                self.todo, actor=self.ada, index=0, version=version, comment=comment
            )

    def test_client_ticks_their_own_comment(self):
        comment = ops.add_comment(self.todo, author=self.cleo, content="- [ ] one")
        ops.tick(
            self.todo,
            actor=self.cleo,
            index=0,
            version=checklists.text_hash(comment.content),
            comment=comment,
        )
        comment.refresh_from_db()
        self.assertEqual(comment.content, "- [x] one")
