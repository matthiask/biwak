"""Copying lists and moving to another project: the modals, the menus
(specs/lists-across-projects.md)"""

import datetime as dt

from django.core.files.base import ContentFile
from django.test import TestCase
from django.utils import timezone

from biwak.activity.models import Action, Event
from biwak.items import operations as ops
from biwak.items.models import Item, Kind
from biwak.projects.models import Membership
from biwak.test_utils import (
    MODAL,
    assert_modal,
    assert_modal_redirect,
    assert_page,
    external,
    person,
    project,
)


class Fixture:
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.dan = person("Dan", client=True, organization="Example Shop Ltd")
        self.pitch = project("Pitch", members=[self.ada, self.bob, self.cleo])
        self.website = project("Website", members=[self.ada, self.dan])
        self.secret = project("Secret", members=[self.bob], all_access=False)
        self.list = ops.create_list(
            project=self.pitch, title="Launch", creator=self.ada, visible=True
        )
        self.tent = ops.create_todo(
            todolist=self.list,
            title="Order the tent",
            creator=self.ada,
            due_on=dt.date(2026, 12, 1),
            assignees=[self.ada, self.cleo],
        )
        ops.add_comment(self.tent, author=self.cleo, content="Which size?")
        self.client.force_login(self.ada)


class CopyTest(Fixture, TestCase):
    def url(self, item=None):
        return f"/lists/{(item or self.list).pk}/copy/"

    def post(self, *, confirm=True, **data):
        """Confirmed unless ``confirm`` is False: Cleo, a client, isn't on
        an internal copy"""
        data = {"project": self.pitch.pk, "title": "Launch", "dates": "keep"} | data
        if confirm and "confirmed" not in data:
            data["confirmed"] = f"{data['project']}:{int('visible' in data)}"
        return self.client.post(self.url(), data, headers=MODAL)

    def test_the_modal_and_the_page(self):
        response = self.client.get(self.url(), headers=MODAL)
        assert_modal(self, response, title="Copy…")
        # The combobox of projects, this one chosen; projects the person
        # can't open aren't offered
        self.assertContains(response, "data-combobox")
        self.assertContains(
            response, f'<option value="{self.pitch.pk}" selected>Pitch</option>'
        )
        self.assertContains(response, f'<option value="{self.website.pk}">')
        self.assertNotContains(response, "Secret")
        self.assertContains(response, 'value="Launch"')
        # The days are there; the script shows them only with "Move by"
        self.assertContains(response, 'data-shown-for="dates=shift"')
        assert_page(self, self.client.get(self.url()), title="Copy…")

    def test_within_the_project(self):
        response = self.post()
        copy = Item.objects.get(project=self.pitch, title="Launch (copy)")
        assert_modal_redirect(self, response, copy.get_absolute_url())
        self.assertEqual(
            list(Item.objects.filter(parent=copy).values_list("title", flat=True)),
            ["Order the tent"],
        )
        # Internal unless asked for
        self.assertFalse(copy.is_client_visible)

    def test_asks_who_is_left_out(self):
        """Cleo isn't in Website: the modal says so first"""
        response = self.post(project=self.website.pk, confirm=False)
        assert_modal(self, response, title="Copy…")
        self.assertContains(
            response, "Cleo Example won&#x27;t see the copy: left unassigned."
        )
        self.assertFalse(Item.objects.filter(project=self.website).exists())
        self.assertContains(response, f'name="confirmed" value="{self.website.pk}:0"')
        response = self.post(project=self.website.pk, confirmed=f"{self.website.pk}:0")
        copy = Item.objects.get(project=self.website, kind=Kind.LIST)
        assert_modal_redirect(self, response, copy.get_absolute_url())
        todo = Item.objects.get(parent=copy)
        self.assertEqual(list(todo.todo.assignees.all()), [self.ada])

    def test_asks_before_showing_to_clients(self):
        Membership.objects.create(project=self.website, user=self.cleo)
        response = self.post(project=self.website.pk, visible="on", confirm=False)
        self.assertContains(
            response, "Makes the copy and 1 to-do visible to 2 clients."
        )
        self.assertContains(response, "btn-destructive")
        self.assertFalse(Item.objects.filter(project=self.website).exists())
        # Confirming another target doesn't count
        response = self.post(
            project=self.website.pk, visible="on", confirmed=f"{self.website.pk}:0"
        )
        self.assertFalse(Item.objects.filter(project=self.website).exists())
        self.post(
            project=self.website.pk, visible="on", confirmed=f"{self.website.pk}:1"
        )
        copy = Item.objects.get(project=self.website, kind=Kind.LIST)
        self.assertTrue(copy.is_client_visible)
        # Internal: nothing to ask
        Membership.objects.filter(project=self.website, user=self.cleo).delete()
        self.post(project=self.pitch.pk)
        self.assertTrue(Item.objects.filter(title="Launch (copy)").exists())

    def test_dates(self):
        response = self.post(dates="shift")
        self.assertContains(response, "By how many days?")
        self.post(dates="shift", days="-3")
        copy = Item.objects.get(title="Launch (copy)")
        self.assertEqual(
            Item.objects.get(parent=copy).todo.due_on, dt.date(2026, 11, 28)
        )
        self.post(dates="remove")
        copy = Item.objects.get(title="Launch (copy 2)")
        self.assertIsNone(Item.objects.get(parent=copy).todo.due_on)

    def test_staff_only(self):
        """Like creating lists; 404 for what clients don't see"""
        self.client.force_login(self.cleo)
        self.assertEqual(self.client.get(self.url()).status_code, 403)
        self.assertEqual(self.post().status_code, 403)
        internal = ops.create_list(project=self.pitch, title="Plans", creator=self.ada)
        self.assertEqual(self.client.get(self.url(internal)).status_code, 404)
        self.client.force_login(person("Eve"))
        hidden = ops.create_list(project=self.secret, title="Plans", creator=self.bob)
        self.assertEqual(self.client.get(self.url(hidden)).status_code, 404)

    def test_not_into_projects_the_person_cant_open(self):
        response = self.post(project=self.secret.pk)
        self.assertContains(response, "Select a valid choice")
        self.assertFalse(Item.objects.filter(project=self.secret).exists())
        self.website.archived_at = timezone.now()
        self.website.save()
        response = self.post(project=self.website.pk)
        self.assertContains(response, "Select a valid choice")

    def test_an_external(self):
        """Externals copy into their projects only"""
        pia = external()
        Membership.objects.create(project=self.pitch, user=pia)
        self.client.force_login(pia)
        response = self.client.get(self.url(), headers=MODAL)
        self.assertNotContains(response, "Website")
        response = self.post(project=self.website.pk)
        self.assertContains(response, "Select a valid choice")

    def test_the_menu(self):
        page = self.client.get(self.list.get_absolute_url())
        self.assertContains(page, f'href="{self.url()}" data-modal>Copy…</a>')
        self.client.force_login(self.cleo)
        page = self.client.get(self.list.get_absolute_url())
        self.assertNotContains(page, self.url())


class MoveListTest(Fixture, TestCase):
    def url(self, item=None):
        return f"/items/{(item or self.list).pk}/move-to-project/"

    def test_the_modal(self):
        response = self.client.get(self.url(), headers=MODAL)
        assert_modal(self, response, title="Move to…")
        self.assertContains(response, "data-combobox")
        self.assertContains(response, f'<option value="{self.website.pk}">Website')
        # Not its own project, not one the person can't open
        self.assertNotContains(response, f'<option value="{self.pitch.pk}"')
        self.assertNotContains(response, "Secret")
        assert_page(self, self.client.get(self.url()), title="Move to…")

    def test_asks_and_moves(self):
        response = self.client.post(
            self.url(), {"project": self.website.pk}, headers=MODAL
        )
        assert_modal(self, response, title="Move to…")
        self.assertContains(
            response,
            "Cleo Example won&#x27;t see it in Website: they&#x27;ll be"
            " unassigned and unsubscribed.",
        )
        self.assertContains(
            response,
            "Makes this list, 1 to-do and 1 comment visible to 1 client.",
        )
        self.list.refresh_from_db()
        self.assertEqual(self.list.project, self.pitch)
        response = self.client.post(
            self.url(),
            {"project": self.website.pk, "confirmed": self.website.pk},
            headers=MODAL,
        )
        assert_modal_redirect(self, response, self.list.get_absolute_url())
        self.list.refresh_from_db()
        self.assertEqual(self.list.project, self.website)
        self.assertEqual(list(self.tent.todo.assignees.all()), [self.ada])

    def test_nothing_to_ask(self):
        internal = ops.create_list(project=self.pitch, title="Plans", creator=self.ada)
        response = self.client.post(
            self.url(internal), {"project": self.website.pk}, headers=MODAL
        )
        assert_modal_redirect(self, response, internal.get_absolute_url())
        internal.refresh_from_db()
        self.assertEqual(internal.project, self.website)

    def test_who_may(self):
        # Clients move only what they created, and lists not at all
        self.client.force_login(self.cleo)
        self.assertEqual(self.client.get(self.url()).status_code, 403)
        own = ops.create_list(
            project=self.pitch, title="Wishes", creator=self.cleo, visible=True
        )
        response = self.client.get(self.url(own), headers=MODAL)
        self.assertNotContains(response, f'<option value="{self.website.pk}"')
        self.client.force_login(self.ada)
        self.assertEqual(self.client.get(self.url(self.tent)).status_code, 404)
        response = self.client.post(self.url(), {"project": self.secret.pk})
        self.assertContains(response, "Select a valid choice")

    def test_a_clients_message(self):
        """Clients create messages, so they move theirs into their
        projects"""
        Membership.objects.create(project=self.website, user=self.cleo)
        message = ops.create_message(
            project=self.pitch, title="Hello", creator=self.cleo, visible=True
        )
        self.client.force_login(self.cleo)
        page = self.client.get(message.get_absolute_url())
        self.assertContains(page, f'href="{self.url(message)}')
        response = self.client.post(
            self.url(message), {"project": self.website.pk}, headers=MODAL
        )
        # Dan doesn't see it yet: asked first
        self.assertContains(response, "visible to 1 client.")
        self.client.post(
            self.url(message),
            {"project": self.website.pk, "confirmed": self.website.pk},
        )
        message.refresh_from_db()
        self.assertEqual(message.project, self.website)

    def test_clients_dont_learn_about_others(self):
        """The names of people a client may not know aren't shown"""
        shop = project("Shop", members=[self.cleo, self.dan], all_access=False)
        eve = person("Eve")
        message = ops.create_message(
            project=self.pitch, title="Hello", creator=self.cleo, visible=True
        )
        from biwak.activity.operations import subscribe

        subscribe(eve, message)
        subscribe(self.bob, message)
        self.client.force_login(self.cleo)
        response = self.client.post(
            self.url(message), {"project": shop.pk}, headers=MODAL
        )
        self.assertContains(response, "Bob Example and 1 other person won")
        self.assertNotContains(response, "Eve")

    def test_the_menu(self):
        page = self.client.get(self.list.get_absolute_url())
        self.assertContains(page, f'href="{self.url()}" data-modal>Move to…</a>')
        # Without another project to go to, nothing
        self.client.force_login(self.bob)
        lone = project("Lone", members=[self.bob], all_access=False)
        Item.objects.all().update(project=lone)
        for p in [self.pitch, self.website, self.secret]:
            p.archived_at = timezone.now()
            p.save()
        page = self.client.get(self.list.get_absolute_url())
        self.assertNotContains(page, self.url())

    def test_feeds(self):
        self.client.post(
            self.url(), {"project": self.website.pk, "confirmed": self.website.pk}
        )
        pitch = self.client.get(f"/projects/{self.pitch.pk}/feed/")
        self.assertNotContains(pitch, "Order the tent")
        # A trace, without a link (decided 2026-11-22)
        self.assertContains(pitch, "moved Launch to Website")
        self.assertNotContains(pitch, self.list.get_absolute_url())
        # Not for clients
        self.client.force_login(self.cleo)
        pitch = self.client.get(f"/projects/{self.pitch.pk}/feed/")
        self.assertNotContains(pitch, "Launch")
        self.client.force_login(self.ada)
        website = self.client.get(f"/projects/{self.website.pk}/feed/")
        self.assertContains(website, "Order the tent")
        self.assertContains(website, "from Pitch to Website")
        # The feed across projects has it once, in Website
        feed = self.client.get("/feed/")
        self.assertContains(feed, "from Pitch to Website", count=1)
        # Dan sees it with what clients saw before, not where it came from
        self.client.force_login(self.dan)
        website = self.client.get(f"/projects/{self.website.pk}/feed/")
        self.assertContains(website, "Which size?")
        self.assertNotContains(website, "Pitch")
        self.assertContains(website, "to Website")


class MoveFilesTest(Fixture, TestCase):
    def setUp(self):
        super().setUp()
        self.folder = ops.create_folder(
            project=self.pitch, title="Maps", creator=self.ada
        )
        self.doc = ops.create_doc(
            project=self.pitch, title="Plan", creator=self.ada, parent=self.folder
        )

    def url(self, item):
        return f"/items/{item.pk}/move/"

    def test_folders_and_projects(self):
        response = self.client.get(self.url(self.folder), headers=MODAL)
        self.assertContains(response, "data-combobox")
        self.assertContains(response, '<optgroup label="Other projects">')
        self.assertContains(response, f'value="project:{self.website.pk}"')
        # In a folder: only the folders of its project
        response = self.client.get(self.url(self.doc), headers=MODAL)
        self.assertNotContains(response, "project:")
        self.assertNotContains(response, "data-combobox")

    def test_moves_with_what_is_in_it(self):
        response = self.client.post(
            self.url(self.folder),
            {"folder": f"project:{self.website.pk}"},
            headers=MODAL,
        )
        # Bob follows the doc and sees Website, all-access: nothing to ask
        assert_modal_redirect(self, response, self.folder.get_absolute_url())
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.project, self.website)
        self.assertEqual(self.doc.parent, self.folder)

    def test_a_doc_in_a_folder_cant(self):
        response = self.client.post(
            self.url(self.doc), {"folder": f"project:{self.website.pk}"}
        )
        self.assertContains(response, "Select a valid choice")
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.project, self.pitch)

    def test_asks_before_showing(self):
        file = ops.create_upload(
            project=self.pitch,
            file=ContentFile(b"x", name="a.txt"),
            creator=self.ada,
            visible=True,
        )
        response = self.client.post(
            self.url(file), {"folder": f"project:{self.website.pk}"}, headers=MODAL
        )
        self.assertContains(response, "data-new-clients")
        file.refresh_from_db()
        self.assertEqual(file.project, self.pitch)
        self.client.post(
            self.url(file),
            {"folder": f"project:{self.website.pk}", "confirmed": self.website.pk},
        )
        file.refresh_from_db()
        self.assertEqual(file.project, self.website)
        self.assertTrue(
            Event.objects.filter(
                item=file, action=Action.MOVED, project=self.website
            ).exists()
        )
