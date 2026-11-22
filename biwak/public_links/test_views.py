"""Public links (specs/public-links.md): the "Share…" modal, the page of
all public links and the public page"""

import datetime as dt

from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from biwak.activity.models import Action, Event
from biwak.files.test_attachments import PNG, upload
from biwak.files.test_library import png
from biwak.items import operations as ops
from biwak.palette.test_actions import palette_data
from biwak.projects import operations as project_ops
from biwak.public_links import operations as link_ops
from biwak.public_links.models import PublicLink
from biwak.public_links.test_operations import Fixture
from biwak.test_utils import (
    MODAL,
    assert_modal,
    assert_page,
    check_in_answers,
    person,
    project,
)


class ShareModalTest(Fixture, TestCase):
    def url(self, item=None):
        return reverse("item_share", args=[(item or self.todo).pk])

    def test_modal_and_page(self):
        response = self.client.get(self.url(), headers=MODAL)
        assert_modal(self, response, title="Share “Pitch the tent”")
        # The own link first, with Copy as the primary button
        own = f"http://testserver/todos/{self.todo.pk}/"
        self.assertContains(response, f'value="{own}"')
        self.assertContains(
            response, 'class="btn btn-primary" data-copy="#own-link"', html=False
        )
        self.assertContains(response, "btn-destructive")
        self.assertContains(response, "Create public link")
        self.assertContains(response, '<option value="7" selected>7 days</option>')
        self.assertNotContains(response, 'id="public-link"')
        assert_page(self, self.client.get(self.url()), title="Share “Pitch the tent”")

    def test_create_in_the_modal_shows_the_link(self):
        response = self.client.post(self.url(), {"days": "3"}, headers=MODAL)
        link = PublicLink.objects.get()
        assert_modal(self, response, title="Share “Pitch the tent”")
        self.assertContains(response, f"http://testserver/p/{link.token}/")
        self.assertContains(response, "Stop sharing")
        self.assertContains(response, "A new public link replaces this one.")

    def test_create_on_the_page_redirects_to_it(self):
        response = self.client.post(self.url(), {"days": "30"})
        self.assertRedirects(response, self.url(), fetch_redirect_response=False)
        link = PublicLink.objects.get()
        self.assertGreater(link.expires_at, timezone.now() + dt.timedelta(days=29))
        self.assertContains(self.client.get(self.url()), link.token)

    def test_only_the_days_offered(self):
        response = self.client.post(self.url(), {"days": "365"}, headers=MODAL)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "invalid-feedback")
        self.assertFalse(PublicLink.objects.exists())

    def test_stop_sharing(self):
        self.share()
        response = self.client.post(self.url(), {"stop": "1"}, headers=MODAL)
        assert_modal(self, response, title="Share “Pitch the tent”")
        self.assertNotContains(response, 'id="public-link"')
        self.assertFalse(PublicLink.objects.exists())
        self.assertEqual(Event.objects.filter(action=Action.STOPPED_SHARING).count(), 1)

    def test_clients_and_containers(self):
        self.client.force_login(self.cleo)
        visible = ops.create_message(
            project=self.project, title="Hello", creator=self.ada, visible=True
        )
        self.assertEqual(self.client.get(self.url(visible)).status_code, 403)
        self.assertEqual(self.client.post(self.url(visible)).status_code, 403)
        # Internal: as if it didn't exist
        self.assertEqual(self.client.get(self.url()).status_code, 404)
        self.client.force_login(self.ada)
        self.assertEqual(self.client.get(self.url(self.todolist)).status_code, 404)

    def test_more_menu_and_palette(self):
        share = f'href="{self.url()}"'
        self.assertContains(self.client.get(self.todo.get_absolute_url()), share)
        data = palette_data(self.client.get(self.todo.get_absolute_url()))
        labels = {a["label"]: a for a in data["actions"]}
        self.assertEqual(labels["Share…"]["url"], self.url())
        self.assertEqual(labels["Public links"]["url"], "/public-links/")
        # Not on a list
        self.assertNotContains(
            self.client.get(self.todolist.get_absolute_url()), "Share…"
        )

    def test_clients_see_no_share(self):
        visible = ops.create_message(
            project=self.project, title="Hello", creator=self.ada, visible=True
        )
        self.client.force_login(self.cleo)
        response = self.client.get(visible.get_absolute_url())
        self.assertNotContains(response, "Share…")
        self.assertNotContains(response, "/public-links/")
        data = palette_data(self.client.get(visible.get_absolute_url()))
        labels = {a["label"] for a in data["actions"]}
        self.assertNotIn("Share…", labels)
        self.assertNotIn("Public links", labels)

    def test_not_check_in_answers(self):
        """Decided 2026-11-22: answers can't be shared"""
        answer = check_in_answers(self.project, [self.ada])[0]
        response = self.client.get(answer.parent.get_absolute_url())
        self.assertNotContains(response, "Share…")
        self.assertEqual(self.client.get(self.url(answer)).status_code, 404)

    def test_the_feed_says_it(self):
        self.share()
        link_ops.stop_public_link(self.todo, actor=self.ada)
        response = self.client.get(reverse("project_feed", args=[self.project.pk]))
        self.assertContains(response, "publicly")
        self.assertContains(response, "stopped sharing")


class AllPublicLinksTest(Fixture, TestCase):
    def setUp(self):
        super().setUp()
        self.limited = project("Limited", members=[self.bob], all_access=False)
        self.hidden = ops.create_message(
            project=self.limited, title="Members only", creator=self.bob
        )

    def test_lists_the_live_links_in_projects_one_can_open(self):
        message = ops.create_message(
            project=self.project, title="Soon", creator=self.ada
        )
        later = self.share(days=30)
        sooner = self.share(message, days=1)
        self.share(self.hidden, actor=self.bob)
        expired = self.share(
            ops.create_message(project=self.project, title="Old", creator=self.ada)
        )
        PublicLink.objects.filter(pk=expired.pk).update(expires_at=timezone.now())
        response = self.client.get(reverse("public_links"))
        self.assertEqual(
            [link.pk for link, _url in response.context["links"]],
            [sooner.pk, later.pk],
        )
        self.assertContains(response, later.token)
        self.assertNotContains(response, "Members only")

    def test_admins_see_all(self):
        self.share(self.hidden, actor=self.bob)
        admin = person("Ida", is_admin=True)
        self.client.force_login(admin)
        response = self.client.get(reverse("public_links"))
        self.assertContains(response, "Members only")

    def test_empty(self):
        response = self.client.get(reverse("public_links"))
        self.assertContains(response, "Nothing is shared publicly.")

    def test_stop_in_place(self):
        link = self.share()
        response = self.client.post(reverse("public_link_stop", args=[link.pk]))
        self.assertRedirects(response, reverse("public_links"))
        self.assertFalse(PublicLink.objects.exists())

    def test_others_cant_stop(self):
        link = self.share(self.hidden, actor=self.bob)
        response = self.client.post(reverse("public_link_stop", args=[link.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(PublicLink.objects.exists())

    def test_clients_get_404(self):
        link = self.share()
        self.client.force_login(self.cleo)
        self.assertEqual(self.client.get(reverse("public_links")).status_code, 404)
        response = self.client.post(reverse("public_link_stop", args=[link.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(PublicLink.objects.exists())

    def test_account_menu(self):
        self.assertContains(self.client.get("/"), 'href="/public-links/"')
        self.client.force_login(self.cleo)
        self.assertNotContains(self.client.get("/"), 'href="/public-links/"')


class PublicPageTest(Fixture, TestCase):
    def setUp(self):
        super().setUp()
        self.client.logout()

    def test_shows_the_item_without_a_session(self):
        ops.add_comment(self.todo, author=self.bob, content="A secret comment")
        link = self.share()
        response = self.client.get(f"/p/{link.token}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pitch the tent")
        self.assertContains(response, "Ada Example")
        # Ticked off, but not tickable
        self.assertContains(response, "checked disabled")
        self.assertNotContains(response, "A secret comment")
        self.assertNotContains(response, "Website")  # The project
        self.assertNotContains(response, "Internal")  # The list
        self.assertNotContains(response, "wb-navbar")
        self.assertNotContains(response, "<a ")
        self.assertContains(
            response, '<meta name="robots" content="noindex, nofollow">'
        )
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")

    def test_signed_in_is_the_same(self):
        link = self.share()
        self.client.force_login(self.ada)
        response = self.client.get(f"/p/{link.token}/")
        self.assertNotContains(response, "wb-navbar")
        self.assertNotContains(response, "data-live-socket")

    def test_mentions_stay_as_written(self):
        ops.update_todo(
            self.todo, actor=self.ada, notes=f"Ask [@Bobby](person:{self.bob.pk})"
        )
        link = self.share()
        response = self.client.get(f"/p/{link.token}/")
        self.assertContains(response, "@Bobby")
        self.assertNotContains(response, "Bob Example")
        self.assertNotContains(response, f"/people/{self.bob.pk}/")

    def test_gone_is_404(self):
        self.assertEqual(self.client.get("/p/made-up-token/").status_code, 404)
        link = self.share()
        PublicLink.objects.update(expires_at=timezone.now())
        self.assertEqual(self.client.get(f"/p/{link.token}/").status_code, 404)
        link = self.share()
        link_ops.stop_public_link(self.todo, actor=self.ada)
        self.assertEqual(self.client.get(f"/p/{link.token}/").status_code, 404)
        link = self.share()
        project_ops.archive_project(self.project, actor=self.ada)
        self.assertEqual(self.client.get(f"/p/{link.token}/").status_code, 404)

    def test_checks_the_status_on_every_request(self):
        """Whatever the operations missed: a row changed behind their back"""
        from biwak.items.models import Item, Status
        from biwak.projects.models import Project

        link = self.share()
        Item.objects.filter(pk=self.todo.pk).update(status=Status.TRASHED)
        self.assertEqual(self.client.get(f"/p/{link.token}/").status_code, 404)
        Item.objects.filter(pk=self.todo.pk).update(status=Status.ACTIVE)
        Project.objects.update(archived_at=timezone.now())
        self.assertEqual(self.client.get(f"/p/{link.token}/").status_code, 404)

    def test_attachments_through_the_token(self):
        own = upload(self.project, self.ada)
        other_item = ops.create_message(
            project=self.project,
            title="Other",
            creator=self.ada,
            content="",
        )
        other = upload(self.project, self.ada, name="other.png")
        ops.update_todo(self.todo, actor=self.ada, notes=own.markdown)
        from biwak.files import attachments

        attachments.link(other_item, other.markdown, actor=self.ada)
        link = self.share()
        response = self.client.get(f"/p/{link.token}/")
        url = f"/p/{link.token}/attachments/{own.key}/sketch.png"
        self.assertContains(response, f'src="{url}"')
        self.assertNotContains(response, f'"{own.get_absolute_url()}"')
        download = self.client.get(url)
        self.assertEqual(download.status_code, 200)
        self.assertEqual(b"".join(download.streaming_content), PNG)
        # The app's own URL needs a session
        self.assertEqual(self.client.get(own.get_absolute_url()).status_code, 302)
        # Another item's attachment isn't reachable through the token
        other_url = f"/p/{link.token}/attachments/{other.key}/other.png"
        self.assertEqual(self.client.get(other_url).status_code, 404)
        link_ops.stop_public_link(self.todo, actor=self.ada)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_file_download_and_preview(self):
        item = ops.create_upload(
            project=self.project,
            file=ContentFile(png(), name="map.png"),
            creator=self.ada,
            description="The *map*",
        )
        link = self.share(item)
        response = self.client.get(f"/p/{link.token}/")
        self.assertContains(response, f"/p/{link.token}/download/")
        self.assertContains(response, f"/p/{link.token}/preview/")
        self.assertContains(response, "<em>map</em>")
        download = self.client.get(f"/p/{link.token}/download/")
        self.assertEqual(download.status_code, 200)
        self.assertEqual(b"".join(download.streaming_content), png())
        self.assertEqual(download["Referrer-Policy"], "no-referrer")
        preview = self.client.get(f"/p/{link.token}/preview/")
        self.assertEqual(preview.status_code, 200)
        # Not for other kinds
        todo = self.share()
        self.assertEqual(self.client.get(f"/p/{todo.token}/download/").status_code, 404)
        ops.trash(item, actor=self.ada)
        self.assertEqual(self.client.get(f"/p/{link.token}/download/").status_code, 404)

    def test_doc_and_message(self):
        doc = ops.create_doc(
            project=self.project,
            title="Packing list",
            creator=self.ada,
            content="Boots",
        )
        message = ops.create_message(
            project=self.project, title="News", creator=self.ada, content="Hello"
        )
        for item, text in [(doc, "Boots"), (message, "Hello")]:
            with self.subTest(item.kind):
                response = self.client.get(f"/p/{self.share(item).token}/")
                self.assertContains(response, item.title)
                self.assertContains(response, text)

    def test_the_date_of_the_last_change(self):
        """Decided 2026-11-22: when it was last changed, not created"""
        from biwak.items.models import Item

        Item.objects.filter(pk=self.todo.pk).update(
            created_at=timezone.make_aware(dt.datetime(2026, 1, 5, 12)),
            updated_at=timezone.make_aware(dt.datetime(2026, 3, 9, 12)),
        )
        response = self.client.get(f"/p/{self.share().token}/")
        self.assertContains(response, "9. Mar 2026")
        self.assertNotContains(response, "5. Jan 2026")

    def test_a_client_never_reaches_anything_else(self):
        """A client with a token gets the item and nothing pointing elsewhere"""
        link = self.share()
        self.client.force_login(self.cleo)
        self.assertEqual(self.client.get(f"/p/{link.token}/").status_code, 200)
        # Still nothing internal through the app
        self.assertEqual(self.client.get(self.todo.get_absolute_url()).status_code, 404)
