import re

from django.contrib.staticfiles import finders
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from biwak.activity.models import Action, Event, Subscription
from biwak.activity.operations import subscribe
from biwak.items import operations as ops
from biwak.items.models import Comment, Item
from biwak.projects.models import Membership
from biwak.test_utils import person, project


class ViewsTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.cleo])
        self.internal = ops.create_list(
            project=self.project, title="Internal", creator=self.ada
        )
        self.shared = ops.create_list(
            project=self.project, title="Shared", creator=self.ada, visible=True
        )
        self.secret_todo = ops.create_todo(
            todolist=self.internal, title="Secret", creator=self.ada
        )
        self.todo = ops.create_todo(
            todolist=self.shared, title="Visible", creator=self.ada
        )

    def test_staff_pages(self):
        self.client.force_login(self.ada)
        self.assertContains(self.client.get(reverse("projects")), "Website")
        response = self.client.get(self.project.get_absolute_url())
        self.assertContains(response, "Internal")
        self.assertContains(response, "wb-client-badge")
        response = self.client.get(self.shared.get_absolute_url())
        self.assertContains(response, "Clients can see this.")
        self.assertContains(response, "Visible")
        response = self.client.get(self.internal.get_absolute_url())
        self.assertNotContains(response, "Clients can see this.")
        self.assertContains(response, "Show to clients")
        self.assertContains(self.client.get(self.todo.get_absolute_url()), "Visible")

    def test_client_sees_only_visible(self):
        self.client.force_login(self.cleo)
        response = self.client.get(self.project.get_absolute_url())
        self.assertContains(response, "Shared")
        self.assertNotContains(response, "Internal")
        self.assertNotContains(response, "Secret")
        for url in [
            self.internal.get_absolute_url(),
            self.secret_todo.get_absolute_url(),
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(
            self.client.post(f"/todos/{self.secret_todo.pk}/toggle/").status_code, 404
        )
        # No switch for clients
        response = self.client.get(self.shared.get_absolute_url())
        self.assertNotContains(response, "Hide from clients")
        self.assertEqual(
            self.client.post(f"/items/{self.shared.pk}/switch/").status_code, 403
        )
        # Moving a visible to-do into an internal list isn't possible
        response = self.client.post(
            f"/todos/{self.todo.pk}/move/", {"list": self.internal.pk, "index": 0}
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(Item.objects.get(pk=self.todo.pk).parent, self.shared)

    def test_a_client_on_a_visible_list(self):
        """The badge and the banner, none of staff's controls"""
        ops.create_group(todolist=self.shared.todolist, title="Soon")
        self.client.force_login(self.ada)
        response = self.client.get(self.shared.get_absolute_url())
        self.assertContains(response, "Hide from clients")
        self.assertContains(response, "data-group-handle", count=1)
        for present in ['<span class="wb-label">Edit</span>', "New group"]:
            self.assertContains(response, present)
        self.assertContains(response, "wb-group-menu")
        self.client.force_login(self.cleo)
        response = self.client.get(self.shared.get_absolute_url())
        self.assertContains(response, "wb-client-badge")
        self.assertContains(response, "Clients can see this.")
        for absent in [
            "Hide from clients",
            "Show to clients",
            '<span class="wb-label">Edit</span>',
            "data-group-handle",
            "New group",
            "wb-group-menu",
        ]:
            with self.subTest(absent=absent):
                self.assertNotContains(response, absent)
        # Their own to-do's page too
        own = ops.create_todo(todolist=self.shared, title="Mine", creator=self.cleo)
        response = self.client.get(own.get_absolute_url())
        self.assertContains(response, "wb-client-badge")
        self.assertContains(response, "Clients can see this")
        self.assertNotContains(response, "Show to clients")

    def test_limited_project(self):
        limited = project("Salaries", members=[self.ada], all_access=False)
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(limited.get_absolute_url()).status_code, 404)
        self.assertNotContains(self.client.get(reverse("projects")), "Salaries")
        admin = person("Root", is_admin=True)
        self.client.force_login(admin)
        self.assertContains(self.client.get(reverse("projects")), "Salaries")
        self.assertEqual(self.client.get(limited.get_absolute_url()).status_code, 404)
        # Not archived ones, which the list leaves out
        limited.archived_at = timezone.now()
        limited.save()
        self.assertEqual(
            self.client.post(f"/projects/{limited.pk}/join/").status_code, 404
        )
        limited.archived_at = None
        limited.save()
        self.client.post(f"/projects/{limited.pk}/join/")
        self.assertEqual(self.client.get(limited.get_absolute_url()).status_code, 200)
        self.assertTrue(
            Event.objects.filter(project=limited, action=Action.JOINED).exists()
        )

    def test_create_and_complete(self):
        self.client.force_login(self.cleo)
        self.client.post(self.shared.get_absolute_url(), {"title": "From client"})
        new = Item.objects.get(title="From client")
        self.assertTrue(new.is_client_visible)
        self.client.post(f"/todos/{new.pk}/toggle/", {"done": "1"})
        new.refresh_from_db()
        self.assertEqual(new.todo.completed_by, self.cleo)

    def test_completing_does_what_the_button_said(self):
        # A page from before someone else completed the to-do still says
        # "Complete": it doesn't reopen it, and the same for "Reopen"
        self.client.force_login(self.ada)
        url = f"/todos/{self.todo.pk}/toggle/"
        ops.complete(self.todo, actor=self.cleo)
        self.client.post(url, {"done": "1"})
        self.todo.todo.refresh_from_db()
        self.assertEqual(self.todo.todo.completed_by, self.cleo)
        self.client.post(url, {"done": "0"})
        self.todo.todo.refresh_from_db()
        self.assertIsNone(self.todo.todo.completed_at)
        self.client.post(url, {"done": "0"})
        self.todo.todo.refresh_from_db()
        self.assertIsNone(self.todo.todo.completed_at)
        self.assertEqual(
            Event.objects.filter(item=self.todo, action=Action.REOPENED).count(), 1
        )
        # Without saying which, nothing
        self.assertEqual(self.client.post(url).status_code, 400)
        self.assertEqual(self.client.post(url, {"done": "x"}).status_code, 400)
        self.todo.todo.refresh_from_db()
        self.assertIsNone(self.todo.todo.completed_at)
        # Every form posting there says it
        for page in [self.todo.get_absolute_url(), self.shared.get_absolute_url()]:
            with self.subTest(page=page):
                self.assertContains(
                    self.client.get(page), '<input type="hidden" name="done" value="1">'
                )

    def test_todo_detail_and_comments(self):
        self.client.force_login(self.ada)
        url = self.todo.get_absolute_url()
        response = self.client.post(
            url,
            {
                "form": "todo",
                "title": "Visible, renamed",
                "notes": "**Soon**",
                "due_on": "2026-12-01",
                "assignees": [self.cleo.pk, self.ada.pk],
            },
        )
        self.assertRedirects(response, url)
        self.todo.refresh_from_db()
        self.assertEqual(self.todo.title, "Visible, renamed")
        self.assertEqual(set(self.todo.todo.assignees.all()), {self.cleo, self.ada})
        self.assertTrue(
            Subscription.objects.filter(user=self.cleo, item=self.todo).exists()
        )
        self.client.post(url, {"form": "comment", "content": "Looks *good*"})
        self.assertEqual(Comment.objects.get().content, "Looks *good*")
        self.assertContains(self.client.get(url), "<em>good</em>")

        # Clients can't be assigned to internal to-dos: not offered
        response = self.client.get(self.secret_todo.get_absolute_url())
        self.assertNotContains(response, "Cleo")

    def test_moving_and_groups(self):
        self.client.force_login(self.ada)
        url = self.shared.get_absolute_url()
        self.client.post(f"/lists/{self.shared.pk}/groups/", {"title": "Later"})
        group = self.shared.todolist.groups.get()
        response = self.client.post(
            f"/todos/{self.todo.pk}/move/",
            {"list": self.shared.pk, "group": group.pk, "index": 0, "quiet": "1"},
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(Item.objects.get(pk=self.todo.pk).todo.group, group)
        response = self.client.get(url + "?view=board")
        self.assertContains(response, "is-board")
        self.client.post(f"/groups/{group.pk}/delete/")
        self.assertIsNone(Item.objects.get(pk=self.todo.pk).todo.group)

    def test_switch(self):
        self.client.force_login(self.ada)
        ops.add_comment(self.secret_todo, author=self.ada, content="Internal note")
        url = f"/items/{self.internal.pk}/switch/"
        # The page offers the question, it doesn't say what happens
        response = self.client.get(self.internal.get_absolute_url())
        self.assertContains(response, f'href="{url}"')
        self.assertContains(response, "data-modal")
        # The question says what becomes visible, as a page and as a modal
        response = self.client.get(url)
        self.assertContains(response, "Show this list to clients?")
        self.assertContains(response, "Makes this list, 1 to-do and 1 comments")
        self.assertContains(response, "visible to 1 client.")
        self.assertContains(response, "Show to clients")
        self.assertContains(response, "btn-destructive")
        self.assertContains(response, 'name="visible"')
        self.assertContains(response, "<html")
        modal = self.client.get(url, headers={"HX-Modal": "true"})
        self.assertContains(modal, "Show this list to clients?")
        self.assertNotContains(modal, "<html")
        # Asking changes nothing
        self.assertIn(self.secret_todo, Item.objects.visible_to(self.ada))
        self.assertNotIn(self.secret_todo, Item.objects.visible_to(self.cleo))
        Membership.objects.create(
            project=self.project, user=person("Dora", client=True)
        )
        self.assertContains(self.client.get(url), "visible to 2 clients.")
        response = self.client.post(url, {"visible": "1"})
        self.assertRedirects(
            response, self.internal.get_absolute_url(), fetch_redirect_response=False
        )
        self.assertIn(self.secret_todo, Item.objects.visible_to(self.cleo))

    def test_hiding_needs_no_question(self):
        self.client.force_login(self.ada)
        response = self.client.get(self.shared.get_absolute_url())
        self.assertContains(response, "Hide from clients")
        self.assertNotContains(response, "Show to clients")
        # Nothing to ask for what's visible already
        url = f"/items/{self.shared.pk}/switch/"
        self.assertRedirects(
            self.client.get(url),
            self.shared.get_absolute_url(),
            fetch_redirect_response=False,
        )
        self.client.post(url)
        self.assertNotIn(self.todo, Item.objects.visible_to(self.cleo))

    def test_the_question_is_for_staff_only(self):
        self.client.force_login(self.cleo)
        for item in [self.internal, self.shared]:
            self.assertEqual(
                self.client.get(f"/items/{item.pk}/switch/").status_code, 403
            )
        self.assertEqual(
            self.client.post(
                f"/items/{self.shared.pk}/switch/", {"visible": "1"}
            ).status_code,
            403,
        )
        self.client.force_login(self.ada)
        self.assertEqual(
            self.client.get(f"/items/{self.todo.pk}/switch/").status_code, 400
        )

    def test_switch_only_where_there_is_one(self):
        self.client.force_login(self.ada)
        response = self.client.post(f"/items/{self.todo.pk}/switch/", {"visible": "1"})
        self.assertEqual(response.status_code, 400)

    def test_subscribe_without_participating(self):
        Membership.objects.create(project=self.project, user=self.bob)
        self.client.force_login(self.bob)
        self.client.post(f"/items/{self.todo.pk}/subscription/", {"subscribe": "1"})
        self.assertTrue(
            Subscription.objects.filter(user=self.bob, item=self.todo).exists()
        )
        self.client.post(f"/items/{self.todo.pk}/subscription/")
        self.assertFalse(
            Subscription.objects.filter(user=self.bob, item=self.todo).exists()
        )

    def test_joining_subscribes_to_nothing(self):
        self.client.force_login(self.bob)
        self.client.post(f"/projects/{self.project.pk}/join/")
        self.assertTrue(self.project.is_member(self.bob))
        self.assertFalse(Subscription.objects.filter(user=self.bob).exists())

    def test_clients_see_only_members_among_subscribers(self):
        """Bob is staff in an all-access project, not a member: clients
        don't learn about him (like the members list)"""
        message = ops.create_message(
            project=self.project, title="News", creator=self.ada, visible=True
        )
        folder = ops.create_folder(
            project=self.project, title="Shared files", creator=self.ada, visible=True
        )
        for item in [self.todo, message, folder]:
            subscribe(self.bob, item)
            subscribe(self.cleo, item)
            with self.subTest(kind=item.kind):
                self.client.force_login(self.cleo)
                response = self.client.get(item.get_absolute_url())
                self.assertContains(response, "Cleo")
                self.assertNotContains(response, "Bob")
                self.client.force_login(self.ada)
                self.assertContains(self.client.get(item.get_absolute_url()), "Bob")

    def test_clients_dont_create_lists(self):
        """Clients create to-dos, comments and messages, not lists
        (specs/access.md)"""
        self.client.force_login(self.cleo)
        url = self.project.get_absolute_url()
        response = self.client.post(url + "lists/new/", {"title": "Our wishes"})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Item.objects.filter(title="Our wishes").exists())
        self.assertNotContains(self.client.get(url), "New list")
        self.client.force_login(self.ada)
        self.assertContains(self.client.get(url), "New list")

    def test_allauth_pages(self):
        # Rendered with our elements (biwak/templates/allauth/)
        response = self.client.get("/accounts/login/")
        self.assertContains(response, "form-control")
        self.assertNotContains(response, "/accounts/signup/")

    def test_login_code_leads_back_to_the_item(self):
        # The link in a notification mail: through the login, back to the item
        url = self.todo.get_absolute_url()
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        # The code goes out once the request's transaction commits
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                response["Location"], {"email": "ada@example.org"}
            )
        code = re.search(r"\b([A-Z0-9]{4}-[A-Z0-9]{4})\b", mail.outbox[-1].body)[1]
        response = self.client.post(response["Location"], {"code": code})
        self.assertRedirects(response, url, fetch_redirect_response=False)
        # The passkey offer comes first (biwak/accounts/passkeys.py), then on
        # to the item
        response = self.client.get(url)
        self.assertRedirects(
            response,
            f"/accounts/passkey-offer/?next={url}",
            fetch_redirect_response=False,
        )
        response = self.client.post(response["Location"])
        self.assertRedirects(response, url, fetch_redirect_response=False)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_no_passwords(self):
        # Login is by code and passkeys; allauth's password pages are off
        self.client.force_login(self.ada)
        for url in [
            "/accounts/password/set/",
            "/accounts/password/change/",
            "/accounts/password/reset/",
            "/accounts/password/reset/done/",
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)
                self.assertEqual(self.client.post(url, {}).status_code, 404)
        self.ada.refresh_from_db()
        self.assertFalse(self.ada.has_usable_password())

    def test_add_todo_inline(self):
        self.client.force_login(self.ada)
        url = self.shared.get_absolute_url()
        response = self.client.get(url)
        self.assertContains(response, "data-add-todo-form", count=1)
        self.assertRegex(
            response.content.decode(), rf'<option\s+value="{self.cleo.pk}"'
        )
        response = self.client.post(
            url,
            {
                "title": "Inline",
                "notes": "With *notes*",
                "assignees": [self.cleo.pk],
                "due_on": "2026-12-24",
            },
            headers={"X-Biwak-Fragment": "1"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertContains(response, "Inline", status_code=201)
        self.assertNotContains(response, "<html", status_code=201)
        new = Item.objects.get(title="Inline")
        self.assertEqual(new.todo.notes, "With *notes*")
        self.assertEqual(list(new.todo.assignees.all()), [self.cleo])
        self.assertEqual(str(new.todo.due_on), "2026-12-24")
        # Errors as text for the form
        response = self.client.post(
            url, {"title": ""}, headers={"X-Biwak-Fragment": "1"}
        )
        self.assertEqual(response.status_code, 422)

    def test_add_todo_no_clients_on_internal_lists(self):
        self.client.force_login(self.ada)
        url = self.internal.get_absolute_url()
        self.assertNotRegex(
            self.client.get(url).content.decode(),
            rf'name="assignees"\s+value="{self.cleo.pk}"',
        )
        response = self.client.post(
            url,
            {"title": "Sneaky", "assignees": [self.cleo.pk]},
            headers={"X-Biwak-Fragment": "1"},
        )
        self.assertEqual(response.status_code, 422)
        self.assertFalse(Item.objects.filter(title="Sneaky").exists())


class ManifestTest(TestCase):
    def test_manifest_is_public(self):
        response = self.client.get("/manifest.webmanifest")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/manifest+json")
        data = response.json()
        self.assertEqual(data["name"], "Biwak")
        self.assertEqual(data["short_name"], "Biwak")
        self.assertEqual(data["start_url"], "/")
        self.assertEqual(data["scope"], "/")
        self.assertEqual(data["display"], "standalone")
        self.assertEqual(data["theme_color"], "#5b37b0")
        self.assertEqual(
            [(i["sizes"], i["purpose"]) for i in data["icons"]],
            [("192x192", "any"), ("512x512", "any"), ("512x512", "maskable")],
        )
        for icon in data["icons"]:
            name = icon["src"].removeprefix("/static/")
            self.assertTrue(finders.find(name), name)

    def test_tags_in_base(self):
        content = self.client.get("/accounts/login/code/").content.decode()
        for needle in [
            '<link rel="manifest" href="/manifest.webmanifest">',
            'name="theme-color" content="#5b37b0" media="(prefers-color-scheme: light)"',
            'name="theme-color" content="#3a2378" media="(prefers-color-scheme: dark)"',
            'rel="apple-touch-icon"',
            "apple-touch-icon.png",
            'name="apple-mobile-web-app-capable" content="yes"',
            'name="apple-mobile-web-app-title" content="Biwak"',
        ]:
            self.assertIn(needle, content)
