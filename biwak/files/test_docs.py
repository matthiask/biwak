import datetime as dt

import time_machine
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from biwak.activity.models import Action, Event, Notification
from biwak.activity.operations import subscribe
from biwak.collab import live
from biwak.files import operations
from biwak.items import operations as ops
from biwak.items.models import Item
from biwak.test_utils import (
    assert_modal,
    assert_modal_redirect,
    bare_doc,
    person,
    project,
)


POST_ONLY = {"doc_read_only", "doc_version_restore", "item_move"}


class Fixture:
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.bob, self.cleo])
        self.public = ops.create_folder(
            project=self.project, title="Public", creator=self.ada, visible=True
        )
        self.private = ops.create_folder(
            project=self.project, title="Private", creator=self.ada
        )
        self.shared = bare_doc(
            project=self.project,
            title="Shared doc",
            content="Shared **text**",
            creator=self.ada,
            visible=True,
        )
        self.secret = bare_doc(
            project=self.project,
            title="Secret doc",
            content="Internal",
            creator=self.ada,
        )
        self.nested = bare_doc(
            project=self.project,
            title="Nested",
            content="In a folder",
            creator=self.ada,
            parent=self.public,
        )

    def url(self, name, item, *args):
        return reverse(name, args=[item.pk, *args])

    def latest(self, item):
        return item.doc.versions.first()


class DocPageTest(Fixture, TestCase):
    def test_the_content_is_in_a_card(self):
        self.client.force_login(self.ada)
        html = self.client.get(self.shared.get_absolute_url()).content.decode()
        card = html.index('<div class="card mb-4">')
        self.assertLess(card, html.index('id="live-text"'))
        self.assertLess(
            html.index("<strong>text</strong>"), html.index("</div>", card) + 200
        )

    def test_staff_and_clients_read_visible_docs(self):
        for user in [self.ada, self.cleo]:
            self.client.force_login(user)
            for doc in [self.shared, self.nested]:
                response = self.client.get(doc.get_absolute_url())
                self.assertContains(response, "Clients can see this")
                # Clients edit only docs they created, and watch the others
                self.assertContains(response, self.url("doc_edit", doc))
                if user.is_client:
                    self.assertContains(response, "Watch live")
                    self.assertNotContains(response, "Make read-only")
                else:
                    self.assertContains(response, "Edit")
                    self.assertContains(response, "Make read-only")
        self.assertContains(
            self.client.get(self.shared.get_absolute_url()), "<strong>text</strong>"
        )

    def test_internal_docs_are_404_for_clients_through_every_entry(self):
        self.client.force_login(self.cleo)
        version = self.latest(self.secret)
        for name, args in [
            ("doc", []),
            ("doc_edit", []),
            ("doc_read_only", []),
            ("doc_versions", []),
            ("doc_version", [version.pk]),
            ("doc_version_restore", [version.pk]),
            ("item_move", []),
        ]:
            url = self.url(name, self.secret, *args)
            with self.subTest(name=name):
                if name not in POST_ONLY:
                    self.assertEqual(self.client.get(url).status_code, 404)
                self.assertEqual(self.client.post(url, {"title": "x"}).status_code, 404)
        self.assertEqual(self.latest(self.secret).content, "Internal")

    def test_a_visible_doc_in_an_internal_folder_is_not_possible_but_moving_works(self):
        moved = bare_doc(
            project=self.project, title="Moved", creator=self.ada, parent=self.private
        )
        self.client.force_login(self.cleo)
        self.assertEqual(self.client.get(moved.get_absolute_url()).status_code, 404)
        ops.move_item(moved, parent=self.public, actor=self.ada)
        self.assertEqual(self.client.get(moved.get_absolute_url()).status_code, 200)
        ops.move_item(moved, parent=self.private, actor=self.ada)
        self.assertEqual(self.client.get(moved.get_absolute_url()).status_code, 404)

    def test_hiding_a_doc_hides_it_from_clients(self):
        ops.set_visibility(self.shared, visible=False, actor=self.ada)
        self.client.force_login(self.cleo)
        self.assertEqual(
            self.client.get(self.shared.get_absolute_url()).status_code, 404
        )

    def test_comments(self):
        self.client.force_login(self.cleo)
        self.client.post(
            self.shared.get_absolute_url(), {"form": "comment", "content": "Nice doc"}
        )
        self.assertContains(self.client.get(self.shared.get_absolute_url()), "Nice doc")
        self.client.force_login(self.ada)
        self.assertEqual(self.shared.comments.count(), 1)

    def test_non_members_get_404(self):
        self.client.force_login(person("Dan", client=True))
        self.assertEqual(
            self.client.get(self.shared.get_absolute_url()).status_code, 404
        )

    def test_the_trash(self):
        self.client.force_login(self.ada)
        self.client.post(reverse("item_trash", args=[self.secret.pk]))
        self.assertEqual(
            self.client.get(self.secret.get_absolute_url()).status_code, 404
        )

    def test_moving(self):
        self.client.force_login(self.ada)
        response = self.client.post(
            reverse("item_move", args=[self.secret.pk]), {"folder": self.public.pk}
        )
        self.assertRedirects(response, self.secret.get_absolute_url())
        self.secret.refresh_from_db()
        self.assertTrue(self.secret.is_client_visible)


class NewDocTest(Fixture, TestCase):
    """New docs are drafts opening the editor at once, nobody's business
    until they have text (specs/files.md, "Docs")"""

    def new_url(self, folder=None):
        url = reverse("doc_new", args=[self.project.pk])
        return f"{url}?folder={folder.pk}" if folder else url

    def new(self, user=None, folder=None):
        self.client.force_login(user or self.ada)
        response = self.client.get(self.new_url(folder))
        self.assertEqual(response.status_code, 200)
        return response, Item.objects.filter(is_draft=True).latest("pk")

    def type(self, item, text, user=None):
        with self.captureOnCommitCallbacks(execute=True):
            live.apply_text(item.doc, text, user=user or self.ada)
            operations.save_live(item.pk)
        item.refresh_from_db()
        return item

    def test_the_editor_opens_with_a_draft(self):
        response, draft = self.new(folder=self.private)
        self.assertEqual(draft.doc.content, "# ")
        self.assertEqual(draft.parent, self.private)
        self.assertContains(response, f'data-collab="/ws/docs/{draft.pk}"')
        self.assertContains(
            response, f'data-collab-draft="{self.url("doc_edit", draft)}"'
        )
        # "Done" asks whom to tell
        self.assertContains(response, f'href="{self.url("doc_tell", draft)}"')
        self.assertEqual(live.access(self.ada, draft.pk), live.WRITE)
        # No event, no version; its creator the only subscriber
        self.assertFalse(Event.objects.filter(item=draft).exists())
        self.assertEqual(draft.doc.versions.count(), 0)
        self.assertEqual([s.user for s in draft.subscriptions.all()], [self.ada])
        # Every visit is a new one
        _response, other = self.new(folder=self.private)
        self.assertNotEqual(other, draft)

    def test_a_draft_is_nobodys_business(self):
        _response, draft = self.new(folder=self.public)
        self.assertTrue(draft.is_client_visible)  # as the folder says
        for user in [self.ada, self.bob, self.cleo]:
            with self.subTest(user=user):
                self.client.force_login(user)
                for url in [
                    self.public.get_absolute_url(),
                    reverse("project", args=[self.project.pk]),
                    reverse("feed"),
                    reverse("search") + "?q=Untitled",
                ]:
                    self.assertNotContains(self.client.get(url), f"/docs/{draft.pk}/")
                self.assertNotIn(
                    draft.pk,
                    [
                        e["id"]
                        for e in self.client.get(
                            f"/api/v1/projects/{self.project.pk}/files/",
                            {"folder_id": self.public.pk},
                        ).json()["entries"]
                    ],
                )
        # Others don't get it at all, its creator only its editor
        for user in [self.bob, self.cleo]:
            self.client.force_login(user)
            for name in ["doc", "doc_edit", "doc_tell", "item_subscribers"]:
                self.assertEqual(
                    self.client.get(self.url(name, draft)).status_code, 404, name
                )
            self.assertIsNone(live.access(user, draft.pk))
        self.client.force_login(self.ada)
        self.assertEqual(self.client.get(f"/api/v1/docs/{draft.pk}/").status_code, 404)
        # "Done" before writing: back to the folder
        self.assertRedirects(
            self.client.get(draft.get_absolute_url()),
            self.public.get_absolute_url(),
        )

    def test_it_becomes_a_doc_with_text(self):
        subscribe(self.bob, self.private)
        _response, draft = self.new(folder=self.private)
        draft = self.type(draft, "#  \n")
        self.assertTrue(draft.is_draft)
        self.assertFalse(Event.objects.filter(item=draft).exists())
        before = draft.created_at
        draft = self.type(draft, "# Minutes\n\nWe met, @Bob too")
        self.assertFalse(draft.is_draft)
        self.assertEqual(draft.title, "Minutes")
        self.assertGreater(draft.created_at, before)
        self.assertEqual(draft.doc.versions.count(), 1)
        event = Event.objects.get(item=draft)
        self.assertEqual(event.action, Action.CREATED)
        # Quiet: the folder's subscribers aren't told
        self.assertFalse(Notification.objects.filter(event=event).exists())
        self.client.force_login(self.bob)
        self.assertContains(self.client.get(self.private.get_absolute_url()), "Minutes")

    def test_mentions_in_the_first_text_tell(self):
        _response, draft = self.new()
        draft = self.type(draft, f"# Minutes\n\n[@Bob](person:{self.bob.pk})")
        event = Event.objects.get(item=draft)
        self.assertEqual(
            [n.user for n in Notification.objects.filter(event=event)], [self.bob]
        )

    def test_clients_dont_create_docs(self):
        """Clients create to-dos, comments and messages (specs/access.md)"""
        self.client.force_login(self.cleo)
        self.assertEqual(self.client.get(self.new_url()).status_code, 403)
        self.assertEqual(self.client.get(self.new_url(self.public)).status_code, 403)
        # Internal folders stay 404
        self.assertEqual(self.client.get(self.new_url(self.private)).status_code, 404)
        self.assertFalse(Item.objects.filter(is_draft=True).exists())

    def test_a_folder_of_another_project_is_404(self):
        other = project("Other", members=[self.ada])
        folder = ops.create_folder(project=other, title="Elsewhere", creator=self.ada)
        self.client.force_login(self.ada)
        self.assertEqual(self.client.get(self.new_url(folder)).status_code, 404)

    def test_empty_drafts_go_after_a_day(self):
        _response, empty = self.new()
        _response, written = self.new()
        _response, fresh = self.new()
        Item.objects.filter(pk__in=[empty.pk, written.pk]).update(
            created_at=timezone.now() - dt.timedelta(days=2)
        )
        # Typed, not saved yet (the server stopped): saved first, a doc
        live.apply_text(written.doc, "# Notes", user=self.ada)
        call_command("fairy_tasks")
        self.assertFalse(Item.objects.filter(pk=empty.pk).exists())
        self.assertTrue(Item.objects.filter(pk=fresh.pk, is_draft=True).exists())
        written.refresh_from_db()
        self.assertFalse(written.is_draft)
        self.assertEqual(written.title, "Notes")


class TellTest(Fixture, TestCase):
    """Telling people about a new doc, asked once at the first "Done"
    (specs/files.md, "Docs")"""

    def setUp(self):
        super().setUp()
        self.client.force_login(self.ada)
        self.client.get(reverse("doc_new", args=[self.project.pk]))
        self.doc = Item.objects.get(is_draft=True)
        self.tell = self.url("doc_tell", self.doc)

    def write(self):
        with self.captureOnCommitCallbacks(execute=True):
            live.apply_text(self.doc.doc, "# Plan\n\nText", user=self.ada)

    def test_done_on_an_empty_draft_goes_back(self):
        response = self.client.get(self.tell, headers={"HX-Modal": "true"})
        assert_modal_redirect(
            self, response, reverse("project_files", args=[self.project.pk])
        )

    def test_not_now(self):
        self.write()
        # What was typed is saved first
        response = self.client.get(self.tell, headers={"HX-Modal": "true"})
        assert_modal(self, response, title="Tell people about it?")
        self.assertContains(response, "Not now")
        self.assertContains(response, "Tell them")
        response = self.client.post(
            self.tell, {"not_now": "1"}, headers={"HX-Modal": "true"}
        )
        assert_modal_redirect(self, response, self.doc.get_absolute_url())
        self.doc.refresh_from_db()
        self.assertFalse(self.doc.doc.tell_pending)
        # Never again
        response = self.client.get(self.url("doc_edit", self.doc))
        self.assertNotContains(response, self.tell)
        self.assertRedirects(self.client.get(self.tell), self.doc.get_absolute_url())
        self.assertFalse(Event.objects.filter(action=Action.SHARED).exists())

    def test_tell_them(self):
        self.write()
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                self.tell, {"people": [self.bob.pk], "note": "Have a look"}
            )
        self.assertRedirects(response, self.doc.get_absolute_url())
        event = Event.objects.get(item=self.doc, action=Action.SHARED)
        self.assertEqual(event.data["note"], "Have a look")
        self.assertEqual(
            [n.user for n in Notification.objects.filter(event=event)], [self.bob]
        )
        self.doc.refresh_from_db()
        self.assertFalse(self.doc.doc.tell_pending)
        # Somebody to tell is needed
        self.doc.doc.tell_pending = True
        self.doc.doc.save()
        response = self.client.post(self.tell, {"note": "x"})
        self.assertContains(response, "Pick at least one person.")

    def test_only_its_creator_is_asked(self):
        self.write()
        self.client.get(self.tell)  # saves
        self.client.force_login(self.bob)
        response = self.client.get(self.url("doc_edit", self.doc))
        self.assertNotContains(response, self.tell)
        self.assertRedirects(self.client.get(self.tell), self.doc.get_absolute_url())
        self.doc.refresh_from_db()
        self.assertTrue(self.doc.doc.tell_pending)

    def test_docs_made_otherwise_dont_ask(self):
        self.client.force_login(self.ada)
        response = self.client.get(self.url("doc_edit", self.shared))
        self.assertNotContains(response, self.url("doc_tell", self.shared))


class EditTest(Fixture, TestCase):
    """The editor page; what's typed goes through the websocket
    (biwak/collab/test_consumers.py)"""

    def test_staff_edit_live(self):
        self.client.force_login(self.ada)
        response = self.client.get(self.url("doc_edit", self.shared))
        self.assertContains(response, f'data-collab="/ws/docs/{self.shared.pk}"')
        self.assertContains(response, "data-attachments=")
        self.assertContains(response, "Save as a version")
        self.assertContains(response, "Clients can see this")

    def test_no_title_form_and_no_title_next_to_the_text(self):
        """The title is the text's first line (specs/doc-titles.md)"""
        self.client.force_login(self.ada)
        response = self.client.get(self.url("doc_edit", self.shared))
        self.assertNotContains(response, "Rename")
        self.assertNotContains(response, 'name="title"')
        self.assertNotContains(response, "<h1")
        self.assertContains(response, "Shared doc", html=False)  # crumbs, <title>
        response = self.client.get(self.shared.get_absolute_url())
        self.assertNotContains(response, "<h1")

    def test_save_as_a_version_sets_the_title_from_the_typed_text(self):
        live.apply_text(self.shared.doc, "# Renamed\n\nText", user=self.bob)
        self.client.force_login(self.bob)
        response = self.client.post(
            self.url("doc_edit", self.shared), {"new_version": "1"}
        )
        self.assertRedirects(response, self.url("doc_edit", self.shared))
        self.shared.refresh_from_db()
        self.assertEqual(self.shared.title, "Renamed")
        latest = self.latest(self.shared)
        self.assertEqual((latest.title, latest.created_by), ("Renamed", self.bob))
        self.assertTrue(
            Event.objects.filter(item=self.shared, actor=self.bob, action="edited")
        )

    def test_save_as_a_version(self):
        live.apply_text(self.shared.doc, "Typed", user=self.ada)
        self.client.force_login(self.ada)
        response = self.client.post(
            self.url("doc_edit", self.shared), {"new_version": "1"}, follow=True
        )
        self.assertContains(response, "Saved as a version.")
        self.assertEqual(
            [v.content for v in self.shared.doc.versions.all()],
            ["Typed", "Shared **text**"],
        )

    def test_clients_watch_docs_staff_created(self):
        """Clients change only what they created (specs/access.md); the
        others they watch (decided 2026-11-20)"""
        self.client.force_login(self.cleo)
        response = self.client.get(self.url("doc_edit", self.shared))
        self.assertContains(response, f'data-collab="/ws/docs/{self.shared.pk}"')
        self.assertNotContains(response, "Save as a version")
        self.assertNotContains(response, "data-attachments=")
        for data in [{"title": "Scope doubled"}, {"new_version": "1"}]:
            response = self.client.post(self.url("doc_edit", self.shared), data)
            self.assertEqual(response.status_code, 403)
        self.shared.refresh_from_db()
        self.assertEqual(self.shared.title, "Shared doc")
        self.assertEqual(self.shared.doc.versions.count(), 1)

    def test_clients_edit_docs_they_created(self):
        doc = bare_doc(
            project=self.project,
            title="Notes",
            content="Ours",
            creator=self.cleo,
            visible=True,
        )
        self.client.force_login(self.cleo)
        self.assertContains(
            self.client.get(self.url("doc_edit", doc)), "Save as a version"
        )
        self.client.post(self.url("doc_edit", doc), {"new_version": "1"})
        self.assertEqual(self.latest(doc).created_by, self.cleo)

    def test_read_only_docs_are_watched_by_everybody(self):
        operations.set_read_only(self.shared, read_only=True, actor=self.ada)
        self.client.force_login(self.ada)
        response = self.client.get(self.shared.get_absolute_url())
        self.assertContains(response, "This doc is read-only.")
        self.assertContains(response, "Watch live")
        response = self.client.get(self.url("doc_edit", self.shared))
        self.assertNotContains(response, "Save as a version")
        response = self.client.post(
            self.url("doc_edit", self.shared), {"new_version": "1"}
        )
        self.assertEqual(response.status_code, 403)

    def test_mentions_in_docs_notify(self):
        with self.captureOnCommitCallbacks(execute=True):
            operations.update_doc(
                self.shared, actor=self.ada, content=f"Hi [@Bob](person:{self.bob.pk})"
            )
        event = Event.objects.filter(item=self.shared, action="edited").get()
        self.assertEqual(event.data["mentioned"], [self.bob.pk])
        self.assertEqual({n.user for n in event.notifications.all()}, {self.bob})

    def test_internal_docs_cannot_be_saved_by_clients(self):
        self.client.force_login(self.cleo)
        response = self.client.post(self.url("doc_edit", self.secret), {"title": "x"})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.latest(self.secret).title, "Secret doc")


class ReadOnlyTest(Fixture, TestCase):
    def test_staff_switch_it(self):
        self.client.force_login(self.bob)
        url = self.url("doc_read_only", self.shared)
        response = self.client.post(url, {"read_only": "1"})
        self.assertRedirects(response, self.shared.get_absolute_url())
        self.assertTrue(Item.objects.get(pk=self.shared.pk).doc.read_only)
        self.assertContains(self.client.get(response.url), "Make editable")
        self.client.post(url)
        self.assertFalse(Item.objects.get(pk=self.shared.pk).doc.read_only)

    def test_clients_dont(self):
        doc = bare_doc(
            project=self.project, title="Notes", creator=self.cleo, visible=True
        )
        self.client.force_login(self.cleo)
        for item in [self.shared, doc]:
            response = self.client.post(
                self.url("doc_read_only", item), {"read_only": "1"}
            )
            self.assertEqual(response.status_code, 403)
            self.assertFalse(Item.objects.get(pk=item.pk).doc.read_only)

    def test_get_is_not_allowed(self):
        self.client.force_login(self.ada)
        url = self.url("doc_read_only", self.shared)
        self.assertEqual(self.client.get(url).status_code, 405)


class VersionsTest(Fixture, TestCase):
    def setUp(self):
        super().setUp()
        operations.update_doc(self.shared, actor=self.bob, content="Two")
        operations.update_doc(self.shared, actor=self.ada, content="Three")
        self.versions = list(self.shared.doc.versions.all())  # newest first

    def test_staff_see_the_list_and_the_versions(self):
        self.client.force_login(self.ada)
        response = self.client.get(self.url("doc_versions", self.shared))
        self.assertContains(response, "current")
        self.assertEqual(len(response.context["versions"]), 3)
        oldest = self.versions[-1]
        response = self.client.get(self.url("doc_version", self.shared, oldest.pk))
        self.assertContains(response, "<strong>text</strong>")
        self.assertContains(response, "The first version")
        middle = self.versions[1]
        response = self.client.get(self.url("doc_version", self.shared, middle.pk))
        self.assertContains(response, "wb-diff-add")  # what changed
        self.assertContains(response, "Restore this version")
        latest = self.client.get(
            self.url("doc_version", self.shared, self.versions[0].pk)
        )
        self.assertNotContains(latest, "Restore this version")

    def test_clients_may_not_read_older_versions(self):
        """Older versions can hold what was internal before the doc was shown"""
        self.client.force_login(self.cleo)
        self.assertEqual(
            self.client.get(self.url("doc_versions", self.shared)).status_code, 403
        )
        url = self.url("doc_version", self.shared, self.versions[-1].pk)
        self.assertEqual(self.client.get(url).status_code, 403)
        restore = self.url("doc_version_restore", self.shared, self.versions[-1].pk)
        self.assertEqual(self.client.post(restore).status_code, 403)
        self.assertNotContains(
            self.client.get(self.shared.get_absolute_url()), "Versions"
        )

    def test_a_version_of_another_doc_is_404(self):
        other = bare_doc(
            project=self.project, title="Other", creator=self.ada, visible=True
        )
        self.client.force_login(self.ada)
        url = self.url("doc_version", self.shared, other.doc.versions.get().pk)
        self.assertEqual(self.client.get(url).status_code, 404)
        url = self.url("doc_version_restore", self.shared, other.doc.versions.get().pk)
        self.assertEqual(self.client.post(url).status_code, 404)

    def test_restoring_saves_the_old_content_as_a_new_version(self):
        self.client.force_login(self.ada)
        oldest = self.versions[-1]
        response = self.client.post(
            self.url("doc_version_restore", self.shared, oldest.pk)
        )
        self.assertRedirects(response, self.shared.get_absolute_url())
        self.shared.doc.refresh_from_db()
        self.assertEqual(self.shared.doc.content, "Shared **text**")
        self.assertEqual(
            [v.content for v in self.shared.doc.versions.all()],
            ["Shared **text**", "Three", "Two", "Shared **text**"],
        )

    def test_restoring_a_read_only_doc_is_refused(self):
        operations.set_read_only(self.shared, read_only=True, actor=self.ada)
        self.client.force_login(self.ada)
        response = self.client.post(
            self.url("doc_version_restore", self.shared, self.versions[-1].pk),
            follow=True,
        )
        self.assertContains(response, "The doc is read-only.")
        self.shared.doc.refresh_from_db()
        self.assertEqual(self.shared.doc.content, "Three")

    def test_internal_docs_versions_are_staff_only_and_404_for_clients(self):
        self.client.force_login(self.bob)
        self.assertEqual(
            self.client.get(self.url("doc_versions", self.secret)).status_code, 200
        )


class HistoryTest(Fixture, TestCase):
    def test_the_history_of_docs_messages_and_files_is_for_staff(self):
        message = ops.create_message(
            project=self.project, title="Hi", creator=self.ada, visible=True
        )
        upload = ops.create_upload(
            project=self.project,
            file=ContentFile(b"x", name="a.txt"),
            creator=self.ada,
            visible=True,
        )
        operations.update_doc(self.shared, actor=self.ada, content="Two")
        operations.update_upload(upload, actor=self.ada, description="About it")
        for item in [self.shared, message, upload]:
            url = reverse("item_history", args=[item.pk])
            self.client.force_login(self.ada)
            self.assertEqual(self.client.get(url).status_code, 200)
            self.client.force_login(self.cleo)
            self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.ada)
        response = self.client.get(reverse("item_history", args=[self.shared.pk]))
        self.assertContains(response, "Two")
        response = self.client.get(reverse("item_history", args=[upload.pk]))
        self.assertContains(response, "About it")

    def test_a_client_gets_404_for_internal_items_first(self):
        self.client.force_login(self.cleo)
        url = reverse("item_history", args=[self.secret.pk])
        self.assertEqual(self.client.get(url).status_code, 404)


class BookmarkTest(Fixture, TestCase):
    def test_bookmarks_follow_visibility_for_the_new_kinds(self):
        message = ops.create_message(
            project=self.project, title="Hi", creator=self.ada, visible=True
        )
        upload = ops.create_upload(
            project=self.project,
            file=ContentFile(b"x", name="a.txt"),
            creator=self.ada,
            visible=True,
        )
        items = [self.shared, message, upload, self.public]
        self.client.force_login(self.cleo)
        for item in items:
            self.client.post(
                reverse("item_bookmark", args=[item.pk]), {"bookmark": "1"}
            )
        response = self.client.get(reverse("bookmarks"))
        for item in items:
            self.assertContains(response, item.get_absolute_url())
        # Internal items cannot be bookmarked by a client
        response = self.client.post(
            reverse("item_bookmark", args=[self.secret.pk]), {"bookmark": "1"}
        )
        self.assertEqual(response.status_code, 404)
        # What is hidden again disappears from their bookmarks
        ops.set_visibility(self.shared, visible=False, actor=self.ada)
        response = self.client.get(reverse("bookmarks"))
        self.assertNotContains(response, self.shared.get_absolute_url())
        self.assertContains(response, message.get_absolute_url())


class UpdatedAtTest(Fixture, TestCase):
    def test_editing_the_text_counts_as_a_change(self):
        later = timezone.now() + dt.timedelta(hours=1)
        with time_machine.travel(later, tick=False):
            operations.update_doc(self.shared, actor=self.bob, content="New text")
        self.shared.refresh_from_db()
        self.assertEqual(self.shared.updated_at, later)
