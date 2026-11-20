"""The shared state of docs edited live and its storing
(specs/collaboration.md); the websocket is in test_consumers.py"""

import datetime as dt
from unittest.mock import patch

import time_machine
from django.core.files.base import ContentFile
from django.test import TestCase
from django.utils import timezone

from biwak.activity.models import Event, Subscription
from biwak.collab import live, ytext
from biwak.collab.models import LiveState, LiveUpdate
from biwak.files import attachments, operations
from biwak.items import operations as ops
from biwak.items.models import Item
from biwak.projects.models import Project
from biwak.search.queries import search
from biwak.test_utils import person, project


class YTextTest(TestCase):
    def test_edits_are_minimal_and_count_characters(self):
        state = ytext.initial_state("Grüße 😀 und mehr")
        doc = ytext.ydoc(state)
        update = ytext.edit(doc, "Grüße 😀😀 and more!")
        self.assertEqual(ytext.text(doc), "Grüße 😀😀 and more!")
        self.assertEqual(
            ytext.text(ytext.ydoc(state, [update])), "Grüße 😀😀 and more!"
        )
        self.assertEqual(ytext.edit(doc, "Grüße 😀😀 and more!"), b"")

    def test_concurrent_edits_merge(self):
        state = ytext.initial_state("One two three")
        mine = ytext.edit(ytext.ydoc(state), "One 2 three")
        theirs = ytext.edit(ytext.ydoc(state), "One two three four")
        merged = ytext.ydoc(state, [mine, theirs])
        self.assertEqual(ytext.text(merged), "One 2 three four")

    def test_validity(self):
        self.assertTrue(ytext.is_valid(ytext.initial_state("x")))
        self.assertFalse(ytext.is_valid(b"\x05broken"))


class LiveTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.cleo])
        self.item = ops.create_doc(
            project=self.project, title="Minutes", content="Agenda", creator=self.ada
        )
        self.doc = self.item.doc

    def type(self, user, text):
        """What somebody types, as the browser sends it"""
        y = live.load(self.doc.pk) if LiveState.objects.filter(doc=self.doc) else None
        if y is None:
            live.prepare(self.doc.pk)
            y = live.load(self.doc.pk)
        live.append(self.doc.pk, ytext.edit(y, text), user)

    def refresh(self):
        self.item = Item.objects.select_related("doc").get(pk=self.item.pk)
        self.doc = self.item.doc

    def test_access(self):
        visible = ops.create_doc(
            project=self.project, title="Shared", creator=self.ada, visible=True
        )
        own = ops.create_doc(
            project=self.project, title="Ours", creator=self.cleo, visible=True
        )
        dan = person("Dan", client=True)
        for user, item, expected in [
            (self.ada, self.item, live.WRITE),
            (self.bob, self.item, live.WRITE),  # all-access
            (self.cleo, self.item, None),  # internal
            (self.cleo, visible, live.READ),
            (self.cleo, own, live.WRITE),
            (dan, visible, None),
        ]:
            with self.subTest(user=user, item=item):
                self.assertEqual(live.access(user, item.pk), expected)
        operations.set_read_only(own, read_only=True, actor=self.ada)
        self.assertEqual(live.access(self.cleo, own.pk), live.READ)
        self.assertEqual(live.access(self.ada, own.pk), live.READ)
        self.assertIsNone(live.access(self.ada, own.pk, session_key="gone"))

    def test_the_state_starts_from_the_content_once(self):
        live.prepare(self.doc.pk)
        state = LiveState.objects.get(doc=self.doc).state
        live.prepare(self.doc.pk)
        self.assertEqual(LiveState.objects.get(doc=self.doc).state, state)
        self.assertEqual(ytext.text(live.load(self.doc.pk)), "Agenda")

    def test_a_state_behind_the_content_follows_it(self):
        live.prepare(self.doc.pk)
        type(self.doc).objects.filter(pk=self.doc.pk).update(content="Changed")
        live.prepare(self.doc.pk)
        self.assertEqual(ytext.text(live.load(self.doc.pk)), "Changed")

    def test_saving_merges_and_records(self):
        self.type(self.bob, "Agenda\n- Budget")
        self.assertTrue(operations.save_live(self.doc.pk, self.bob))
        self.refresh()
        self.assertEqual(self.doc.content, "Agenda\n- Budget")
        self.assertFalse(LiveUpdate.objects.exists())
        self.assertEqual(ytext.text(live.load(self.doc.pk)), "Agenda\n- Budget")
        event = Event.objects.get(item=self.item, action="edited")
        self.assertEqual(event.actor, self.bob)
        self.assertEqual(
            [(v.content, v.created_by) for v in self.doc.versions.all()],
            [("Agenda\n- Budget", self.bob), ("Agenda", self.ada)],
        )
        # Nothing new: nothing happens
        self.assertFalse(operations.save_live(self.doc.pk, self.bob))

    def test_one_event_per_person_and_session_and_a_version_per_ten_minutes(self):
        start = timezone.now()
        for minutes, text in [(1, "Agenda 1"), (5, "Agenda 12"), (20, "Agenda 123")]:
            with time_machine.travel(start + dt.timedelta(minutes=minutes)):
                self.type(self.ada, text)
                operations.save_live(self.doc.pk)
        self.assertEqual(
            Event.objects.filter(item=self.item, action="edited").count(), 2
        )
        self.assertEqual(
            [v.content for v in self.doc.versions.all()], ["Agenda 123", "Agenda 12"]
        )

    def test_several_authors_at_once(self):
        self.type(self.ada, "Agenda by Ada")
        self.type(self.bob, "Bob's Agenda by Ada")
        operations.save_live(self.doc.pk)
        self.refresh()
        self.assertEqual(self.doc.content, "Bob's Agenda by Ada")
        actors = {
            e.actor for e in Event.objects.filter(item=self.item, action="edited")
        }
        self.assertEqual(actors, {self.ada, self.bob})
        # The creation's version is Ada's, within ten minutes: updated
        self.assertEqual(self.doc.versions.get().created_by, self.ada)

    def test_mentions_and_attachments(self):
        attachment = attachments.upload(
            project=self.project,
            file=ContentFile(b"x", name="plan.pdf"),
            uploaded_by=self.bob,
        )
        self.type(
            self.bob,
            f"Agenda [@Ada](person:{self.ada.pk}) [plan](attachment:{attachment.key})",
        )
        with self.captureOnCommitCallbacks(execute=True):
            operations.save_live(self.doc.pk)
        attachment.refresh_from_db()
        self.assertEqual(attachment.item_id, self.item.pk)
        event = Event.objects.get(item=self.item, action="edited")
        self.assertEqual(event.actor, self.bob)
        self.assertEqual(event.data["mentioned"], [self.ada.pk])

    def test_mentions_are_credited_to_who_typed_them(self):
        self.type(self.ada, f"Agenda [@Bob](person:{self.bob.pk})")
        self.type(
            self.bob,
            f"Agenda [@Bob](person:{self.bob.pk}) [@Ada](person:{self.ada.pk})",
        )
        with self.captureOnCommitCallbacks(execute=True):
            operations.save_live(self.doc.pk)
        mentioned = {
            event.actor: event.data.get("mentioned")
            for event in Event.objects.filter(item=self.item, action="edited")
        }
        self.assertEqual(mentioned, {self.ada: [self.bob.pk], self.bob: [self.ada.pk]})
        self.assertEqual(
            Subscription.objects.get(item=self.item, user=self.bob).added_by, self.ada
        )

    def test_what_people_who_lost_access_typed_is_dropped(self):
        """Bob is staff, not a member: the project made limited before the
        save, what he typed is gone (and so are his event and mentions)"""
        self.type(self.ada, "Agenda by Ada")
        self.type(self.bob, f"Agenda by Ada, [@Cleo](person:{self.cleo.pk}) and Bob")
        Project.objects.filter(pk=self.project.pk).update(is_all_access=False)
        operations.save_live(self.doc.pk)
        self.refresh()
        self.assertEqual(self.doc.content, "Agenda by Ada")
        self.assertEqual(ytext.text(live.load(self.doc.pk)), "Agenda by Ada")
        self.assertEqual(
            [e.actor for e in Event.objects.filter(item=self.item, action="edited")],
            [self.ada],
        )
        self.assertFalse(LiveUpdate.objects.exists())

    def test_what_others_built_on_stays_but_isnt_credited(self):
        """Dropping Bob's text would leave out Ada's typed after it (Yjs
        keeps her updates pending without his): it stays, but Bob is no
        author"""
        self.type(self.bob, f"Agenda [@Ada](person:{self.ada.pk}) by Bob")
        self.type(self.ada, f"Agenda [@Ada](person:{self.ada.pk}) by Bob, approved")
        Project.objects.filter(pk=self.project.pk).update(is_all_access=False)
        with self.captureOnCommitCallbacks(execute=True):
            operations.save_live(self.doc.pk)
        self.refresh()
        self.assertEqual(
            self.doc.content, f"Agenda [@Ada](person:{self.ada.pk}) by Bob, approved"
        )
        (event,) = Event.objects.filter(item=self.item, action="edited")
        self.assertEqual(event.actor, self.ada)
        self.assertNotIn("mentioned", event.data)

    def test_search_finds_what_was_typed_and_clients_still_dont(self):
        self.type(self.ada, "Agenda zeppelin")
        operations.save_live(self.doc.pk)
        self.assertEqual(list(search(self.ada, "zeppelin")), [self.item])
        self.assertEqual(list(search(self.cleo, "zeppelin")), [])
        # The events of an internal doc stay internal
        self.assertFalse(Event.objects.visible_to(self.cleo).filter(item=self.item))

    def test_api_edits_merge_with_what_is_typed(self):
        self.type(self.bob, "Agenda, typed")
        operations.update_doc(self.item, actor=self.ada, content="The agenda")
        self.refresh()
        self.assertEqual(self.doc.content, "The agenda, typed")
        self.assertEqual(
            {e.actor for e in Event.objects.filter(item=self.item, action="edited")},
            {self.ada, self.bob},
        )

    def test_api_edits_are_sent_to_the_editors(self):
        live.prepare(self.doc.pk)
        state = LiveState.objects.get(doc=self.doc).state
        sent = []
        with (
            patch.object(live, "send_update", lambda pk, u: sent.append((pk, u))),
            self.captureOnCommitCallbacks(execute=True),
        ):
            operations.update_doc(self.item, actor=self.ada, content="Agenda!")
        ((pk, update),) = sent
        self.assertEqual(pk, self.doc.pk)
        doc = ytext.ydoc(state, [update])
        self.assertEqual(ytext.text(doc), "Agenda!")

    def test_restoring_is_an_edit_too(self):
        operations.update_doc(self.item, actor=self.bob, content="Two")
        first = self.doc.versions.last()
        self.type(self.ada, "Two, typed")
        operations.restore_doc_version(self.item, first, actor=self.ada)
        self.refresh()
        self.assertEqual(self.doc.content, "Agenda, typed")
        self.assertEqual(ytext.text(live.load(self.doc.pk)), "Agenda, typed")

    def test_fairy_tasks_save_what_was_left(self):
        self.type(self.bob, "Agenda, left over")
        self.assertEqual(list(live.pending()), [self.doc])
        self.assertEqual(operations.save_pending(), 1)
        self.refresh()
        self.assertEqual(self.doc.content, "Agenda, left over")
        self.assertEqual(list(live.pending()), [])

    def test_deleted_docs_are_skipped(self):
        self.assertFalse(operations.save_live(0))
