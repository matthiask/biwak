"""The shared state of docs edited live and its storing
(specs/collaboration.md); the websocket is in test_consumers.py"""

import datetime as dt
from io import StringIO
from unittest.mock import patch

import time_machine
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.db import connection
from django.test import TestCase
from django.utils import timezone

from biwak.accounts.middleware import set_user_name
from biwak.activity.models import Event, Subscription
from biwak.audit.models import LoggedAction
from biwak.collab import live, ytext
from biwak.collab.models import LiveState, LiveUpdate
from biwak.files import attachments, operations
from biwak.items.models import Item
from biwak.projects.models import Project
from biwak.search.queries import search
from biwak.test_utils import bare_doc, person, project


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

    def test_line_breaks_are_one_character(self):
        """Browsers send a textarea's line breaks as CR LF; the editor
        (CodeMirror) counts a line break as one character, Yjs counted two,
        so every edit landed one character off per line break before it"""
        doc = ytext.ydoc(ytext.initial_state("One\r\ntwo\rthree"))
        self.assertEqual(ytext.text(doc), "One\ntwo\nthree")
        ytext.edit(doc, "One\r\n2\r\nthree")
        self.assertEqual(ytext.text(doc), "One\n2\nthree")

    def test_docs_and_forms_store_one_character_line_breaks(self):
        from django import forms

        from biwak.forms import Form
        from biwak.items import operations as ops

        ada = person("Ada")
        doc = ops.create_doc(
            project=project(members=[ada]), title="Notes", content="a\r\nb", creator=ada
        )
        # After the heading with the title (specs/doc-titles.md)
        self.assertEqual(doc.doc.content, "# Notes\n\na\nb")

        class TextForm(Form):
            text = forms.CharField(widget=forms.Textarea)

        form = TextForm({"text": "a\r\nb"})
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["text"], "a\nb")

    def test_validity(self):
        self.assertTrue(ytext.is_valid(ytext.initial_state("x")))
        self.assertFalse(ytext.is_valid(b"\x05broken"))


class LiveTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.cleo])
        self.item = bare_doc(
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

    def test_the_reading_view_shows_what_was_typed(self):
        """ "Done" leads to the reading view while the editor's connection is
        still closing: the page saves what was typed first, not after a
        reload"""
        self.type(self.ada, "Agenda and minutes")
        self.client.force_login(self.ada)
        response = self.client.get(self.item.get_absolute_url())
        self.assertContains(response, "Agenda and minutes")
        self.assertFalse(LiveUpdate.objects.filter(doc=self.doc).exists())

    def test_access(self):
        visible = bare_doc(
            project=self.project, title="Shared", creator=self.ada, visible=True
        )
        own = bare_doc(
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

    def test_saving_sets_the_title_from_the_first_line(self):
        self.type(self.bob, "# Budget meeting\n\nAgenda")
        operations.save_live(self.doc.pk)
        self.item.refresh_from_db()
        self.assertEqual(self.item.title, "Budget meeting")
        self.assertEqual(self.doc.versions.first().title, "Budget meeting")

    def test_saving_merges_and_records(self):
        self.type(self.bob, "Agenda\n- Budget")
        self.assertTrue(operations.save_live(self.doc.pk))
        self.refresh()
        # (a list after a paragraph: a blank line between them, like the
        # editor writes it)
        self.assertEqual(self.doc.content, "Agenda\n\n- Budget")
        self.assertFalse(LiveUpdate.objects.exists())
        self.assertEqual(ytext.text(live.load(self.doc.pk)), "Agenda\n\n- Budget")
        event = Event.objects.get(item=self.item, action="edited")
        self.assertEqual(event.actor, self.bob)
        self.assertEqual(
            [(v.content, v.created_by) for v in self.doc.versions.all()],
            [("Agenda\n\n- Budget", self.bob), ("Agenda", self.ada)],
        )
        # Nothing new: nothing happens
        self.assertFalse(operations.save_live(self.doc.pk))

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

    def test_clients_mention_members_only_also_when_typing_with_others(self):
        """Bob is staff and sees the doc, but isn't a member: Cleo's mention
        of him doesn't count, Ada's does; saved again with Ada as the first
        author, Cleo's stays rejected (it was in the text before)"""
        doc = bare_doc(
            project=self.project, title="Ours", creator=self.cleo, visible=True
        )
        self.item, self.doc = doc, doc.doc
        bob = f"[@Bob](person:{self.bob.pk})"
        self.type(self.cleo, f"Hi {bob}")
        self.type(self.ada, f"Hi {bob}, and Ada")
        with self.captureOnCommitCallbacks(execute=True):
            operations.save_live(self.doc.pk)
        self.assertFalse(Event.objects.filter(data__has_key="mentioned").exists())
        self.assertFalse(Subscription.objects.filter(user=self.bob).exists())

        self.type(self.ada, f"Hi {bob}, and Ada. Hi {bob}")
        with self.captureOnCommitCallbacks(execute=True):
            operations.save_live(self.doc.pk)
        self.assertFalse(Event.objects.filter(data__has_key="mentioned").exists())

        self.type(self.ada, "Hi")
        operations.save_live(self.doc.pk)
        self.type(self.ada, f"Hi {bob}")
        with self.captureOnCommitCallbacks(execute=True):
            operations.save_live(self.doc.pk)
        event = Event.objects.get(data__has_key="mentioned")
        self.assertEqual(
            (event.actor, event.data["mentioned"]), (self.ada, [self.bob.pk])
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

    def test_fairy_tasks_save_before_deleting_unlinked_files(self):
        # Typing left over for more than a day (offline, a lost connection)
        # links its file before the cleanup looks at it
        with time_machine.travel(timezone.now() - dt.timedelta(days=2)):
            photo = attachments.upload(
                project=self.project,
                file=ContentFile(b"x", name="photo.png"),
                uploaded_by=self.ada,
            )
        self.type(self.ada, f"Agenda\n\n{photo.markdown}")
        call_command("fairy_tasks", stdout=StringIO())
        photo.refresh_from_db()
        self.assertEqual(photo.item_id, self.item.pk)

    def test_deleted_docs_are_skipped(self):
        self.assertFalse(operations.save_live(0))


class AuditNameTest(TestCase):
    """The audit log names who typed what a save merges, not who caused it
    (decided 2026-11-28, specs/auditing.md)"""

    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.bob, self.cleo])
        self.item = bare_doc(
            project=self.project,
            title="Minutes",
            content="Agenda",
            creator=self.ada,
            visible=True,
        )
        live.prepare(self.item.pk)
        LoggedAction.objects.all().delete()

    def type(self, user, text):
        live.append(self.item.pk, ytext.edit(live.load(self.item.pk), text), user)

    def names(self):
        return set(
            LoggedAction.objects.filter(table_name="items_doc").values_list(
                "user_name", flat=True
            )
        )

    def test_a_client_opening_the_page(self):
        self.type(self.bob, "Agenda by Bob")
        self.client.force_login(self.cleo)
        self.assertContains(self.client.get(self.item.get_absolute_url()), "by Bob")
        self.assertEqual(self.names(), {f"user-{self.bob.pk}-Bob"})

    def test_several_people_typing(self):
        self.type(self.bob, "Agenda by Bob")
        self.type(self.ada, "Agenda by Bob and Ada")
        operations.save_live(self.item.pk)
        self.assertEqual(self.names(), {"Bob, Ada"})

    def test_the_job_keeps_its_name(self):
        set_user_name("Fairy tasks")
        self.type(self.bob, "Agenda by Bob")
        operations.save_pending()
        self.assertEqual(self.names(), {f"user-{self.bob.pk}-Bob"})
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('application_name')")
            self.assertEqual(cursor.fetchone()[0], "Fairy tasks")
