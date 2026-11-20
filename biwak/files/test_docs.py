import datetime as dt

import time_machine
from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from biwak.activity.models import Event
from biwak.files import operations
from biwak.items import operations as ops
from biwak.items.models import Item
from biwak.test_utils import person, project


POST_ONLY = {"doc_lock", "doc_version_restore", "item_move"}


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
        self.shared = ops.create_doc(
            project=self.project,
            title="Shared doc",
            content="Shared **text**",
            creator=self.ada,
            visible=True,
        )
        self.secret = ops.create_doc(
            project=self.project,
            title="Secret doc",
            content="Internal",
            creator=self.ada,
        )
        self.nested = ops.create_doc(
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
    def test_staff_and_clients_read_visible_docs(self):
        for user in [self.ada, self.cleo]:
            self.client.force_login(user)
            for doc in [self.shared, self.nested]:
                response = self.client.get(doc.get_absolute_url())
                self.assertContains(response, "Clients can see this")
                # Clients edit only docs they created
                edit = self.url("doc_edit", doc)
                if user.is_client:
                    self.assertNotContains(response, edit)
                else:
                    self.assertContains(response, edit)
        self.assertContains(
            self.client.get(self.shared.get_absolute_url()), "<strong>text</strong>"
        )

    def test_internal_docs_are_404_for_clients_through_every_entry(self):
        self.client.force_login(self.cleo)
        version = self.latest(self.secret)
        for name, args in [
            ("doc", []),
            ("doc_edit", []),
            ("doc_lock", []),
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
        moved = ops.create_doc(
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
    def url(self, folder=None):
        url = reverse("doc_new", args=[self.project.pk])
        return f"{url}?folder={folder.pk}" if folder else url

    def test_everybody_is_preselected(self):
        self.client.force_login(self.ada)
        form = self.client.get(self.url()).context["form"]
        self.assertEqual(form["notify"].value(), "everybody")

    def send(self, user, folder=None, **data):
        self.client.force_login(user)
        data = {"title": "Minutes", "content": "Text", "notify": "nobody"} | data
        return self.client.post(self.url(folder), data)

    def test_staff_creates_an_internal_doc(self):
        response = self.send(self.ada)
        doc = Item.objects.get(title="Minutes")
        self.assertRedirects(response, reverse("doc", args=[doc.pk]))
        self.assertFalse(doc.is_client_visible)
        self.assertEqual(doc.doc.versions.count(), 1)

    def test_in_a_folder_and_visibility(self):
        self.send(self.ada, folder=self.public)
        self.assertTrue(Item.objects.get(title="Minutes").is_client_visible)
        self.send(self.ada, title="Top", visible="on")
        self.assertTrue(Item.objects.get(title="Top").is_client_visible)

    def test_a_client_creates_visible_docs_where_it_can_see(self):
        self.send(self.cleo, folder=self.public)
        self.assertTrue(Item.objects.get(title="Minutes").is_client_visible)
        self.assertEqual(self.send(self.cleo, folder=self.private).status_code, 404)

    def test_whom_to_notify(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.send(self.ada, folder=self.public, notify="everybody")
        doc = Item.objects.get(title="Minutes")
        told = {n.user for n in Event.objects.get(item=doc).notifications.all()}
        self.assertEqual(told, {self.bob, self.cleo})
        self.assertEqual(self.client.get(self.url()).status_code, 200)

    def test_a_folder_of_another_project_is_404(self):
        other = project("Other", members=[self.ada])
        folder = ops.create_folder(project=other, title="Elsewhere", creator=self.ada)
        self.assertEqual(self.send(self.ada, folder=folder).status_code, 404)

    def test_the_form_asks_whom_to_notify(self):
        self.client.force_login(self.ada)
        response = self.client.post(self.url(), {"title": "x"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Item.objects.filter(title="x").exists())


class EditTest(Fixture, TestCase):
    def edit(self, user, doc=None, **data):
        doc = doc or self.shared
        self.client.force_login(user)
        base = self.latest(doc).pk
        data = {"title": doc.title, "content": "New", "base_version": base} | data
        return self.client.post(self.url("doc_edit", doc), data)

    def test_opening_the_form_takes_the_lock(self):
        self.client.force_login(self.ada)
        response = self.client.get(self.url("doc_edit", self.shared))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-doc-lock")
        self.assertContains(response, 'name="base_version"')
        self.shared.doc.refresh_from_db()
        self.assertEqual(operations.lock_holder(self.shared.doc), self.ada)

    def test_somebody_else_cannot_open_the_form_meanwhile(self):
        self.client.force_login(self.ada)
        self.client.get(self.url("doc_edit", self.shared))
        self.client.force_login(self.bob)
        response = self.client.get(self.url("doc_edit", self.shared), follow=True)
        self.assertRedirects(response, self.shared.get_absolute_url())
        self.assertContains(response, "Ada is editing")
        self.assertNotContains(response, f'href="{self.url("doc_edit", self.shared)}"')

    def test_after_the_lock_expired_others_can_edit(self):
        self.client.force_login(self.ada)
        self.client.get(self.url("doc_edit", self.shared))
        with time_machine.travel(timezone.now() + dt.timedelta(minutes=6)):
            self.client.force_login(self.bob)
            response = self.client.get(self.url("doc_edit", self.shared))
            self.assertEqual(response.status_code, 200)

    def test_saving(self):
        response = self.edit(self.ada, title="Renamed", content="Changed")
        self.assertRedirects(response, self.shared.get_absolute_url())
        self.shared.refresh_from_db()
        self.assertEqual(self.shared.title, "Renamed")
        self.assertEqual(self.shared.doc.content, "Changed")

    def test_clients_cannot_edit_or_lock_docs_staff_created(self):
        """Clients change only what they created (specs/access.md)"""
        self.client.force_login(self.cleo)
        response = self.client.get(self.url("doc_edit", self.shared))
        self.assertEqual(response.status_code, 403)
        response = self.edit(self.cleo, content="Scope doubled, same price")
        self.assertEqual(response.status_code, 403)
        response = self.client.post(self.url("doc_lock", self.shared))
        self.assertEqual(response.status_code, 403)
        self.shared.doc.refresh_from_db()
        self.assertEqual(self.shared.doc.content, "Shared **text**")
        self.assertIsNone(operations.lock_holder(self.shared.doc))
        response = self.client.get(self.shared.get_absolute_url())
        self.assertNotContains(response, self.url("doc_edit", self.shared))

    def test_clients_edit_docs_they_created(self):
        doc = ops.create_doc(
            project=self.project,
            title="Notes",
            content="Ours",
            creator=self.cleo,
            visible=True,
        )
        self.edit(self.cleo, doc, content="By a client")
        doc.doc.refresh_from_db()
        self.assertEqual(doc.doc.content, "By a client")
        self.assertEqual(self.latest(doc).created_by, self.cleo)

    def test_save_as_a_version(self):
        self.edit(self.ada, content="One")
        self.edit(self.ada, content="Two", new_version="1")
        # The first save by the author within ten minutes updated the
        # creation's version, the second one started a new one
        self.assertEqual(
            [v.content for v in self.shared.doc.versions.all()], ["Two", "One"]
        )

    def test_the_lock_is_given_up_when_saving(self):
        self.client.force_login(self.ada)
        self.client.get(self.url("doc_edit", self.shared))
        self.client.post(
            self.url("doc_edit", self.shared),
            {
                "title": "Shared doc",
                "content": "Done",
                "base_version": self.latest(self.shared).pk,
            },
        )
        self.shared.doc.refresh_from_db()
        self.assertIsNone(operations.lock_holder(self.shared.doc))

    def test_a_save_over_a_newer_version_by_somebody_else_is_refused(self):
        self.client.force_login(self.ada)
        base = self.latest(self.shared).pk
        operations.update_doc(self.shared, actor=self.bob, content="Bob's")
        response = self.client.post(
            self.url("doc_edit", self.shared),
            {"title": "Shared doc", "content": "Ada's", "base_version": base},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bob saved a newer version")
        self.assertContains(response, "Ada&#x27;s")  # her text stays in the form
        newer = self.latest(self.shared)
        self.assertContains(response, self.url("doc_version", self.shared, newer.pk))
        self.shared.doc.refresh_from_db()
        self.assertEqual(self.shared.doc.content, "Bob's")

    def test_clients_get_no_link_to_the_versions(self):
        doc = ops.create_doc(
            project=self.project, title="Shared doc", creator=self.cleo, visible=True
        )
        self.client.force_login(self.cleo)
        base = self.latest(doc).pk
        operations.update_doc(doc, actor=self.bob, content="Bob's")
        response = self.client.post(
            self.url("doc_edit", doc),
            {"title": "Shared doc", "content": "Cleo's", "base_version": base},
        )
        self.assertContains(response, "Bob saved a newer version")
        self.assertNotContains(response, "/versions/")

    def test_a_save_while_somebody_else_holds_the_lock_is_refused(self):
        operations.lock_doc(self.shared, self.bob)
        response = self.edit(self.ada, content="Ada's")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bob is editing")
        self.shared.doc.refresh_from_db()
        self.assertEqual(self.shared.doc.content, "Shared **text**")

    def test_mentions_in_docs_notify(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.edit(self.ada, content=f"Hi [@Bob](person:{self.bob.pk})")
        event = Event.objects.filter(item=self.shared, action="edited").get()
        self.assertEqual(event.data["mentioned"], [self.bob.pk])
        self.assertEqual({n.user for n in event.notifications.all()}, {self.bob})

    def test_cancelling_gives_up_the_lock(self):
        self.client.force_login(self.ada)
        self.client.get(self.url("doc_edit", self.shared))
        response = self.client.post(self.url("doc_lock", self.shared), {"release": "1"})
        self.assertRedirects(response, self.shared.get_absolute_url())
        self.shared.doc.refresh_from_db()
        self.assertIsNone(operations.lock_holder(self.shared.doc))

    def test_internal_docs_cannot_be_saved_by_clients(self):
        self.client.force_login(self.cleo)
        response = self.client.post(
            self.url("doc_edit", self.secret), {"title": "x", "content": "Hacked"}
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.latest(self.secret).content, "Internal")


class LockEndpointTest(Fixture, TestCase):
    def test_taking_and_renewing(self):
        self.client.force_login(self.ada)
        url = self.url("doc_lock", self.shared)
        self.assertEqual(self.client.post(url).status_code, 204)
        first = Item.objects.get(pk=self.shared.pk).doc.locked_at
        with time_machine.travel(timezone.now() + dt.timedelta(minutes=1)):
            self.assertEqual(self.client.post(url).status_code, 204)
        self.assertGreater(Item.objects.get(pk=self.shared.pk).doc.locked_at, first)

    def test_somebody_else_holds_it(self):
        operations.lock_doc(self.shared, self.ada)
        self.client.force_login(self.bob)
        response = self.client.post(self.url("doc_lock", self.shared))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {"locked_by": "Ada"})

    def test_it_expires_five_minutes_after_the_last_renewal(self):
        operations.lock_doc(self.shared, self.ada)
        self.client.force_login(self.bob)
        with time_machine.travel(timezone.now() + dt.timedelta(minutes=4)):
            self.assertEqual(
                self.client.post(self.url("doc_lock", self.shared)).status_code, 409
            )
        with time_machine.travel(timezone.now() + dt.timedelta(minutes=6)):
            self.assertEqual(
                self.client.post(self.url("doc_lock", self.shared)).status_code, 204
            )

    def test_get_is_not_allowed(self):
        self.client.force_login(self.ada)
        self.assertEqual(
            self.client.get(self.url("doc_lock", self.shared)).status_code, 405
        )


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
        self.assertContains(response, "bg-success-subtle")  # what changed
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
        other = ops.create_doc(
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

    def test_restoring_while_somebody_edits(self):
        operations.lock_doc(self.shared, self.bob)
        self.client.force_login(self.ada)
        self.client.post(
            self.url("doc_version_restore", self.shared, self.versions[-1].pk)
        )
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
