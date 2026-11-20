from django.test import TestCase

from biwak.activity.models import Action, Event, Subscription
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

    def test_login_required(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/code/", response["Location"])
        self.assertEqual(self.client.get("/accounts/login/code/").status_code, 200)

    def test_staff_pages(self):
        self.client.force_login(self.ada)
        self.assertContains(self.client.get("/"), "Website")
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

    def test_limited_project(self):
        limited = project("Salaries", members=[self.ada], all_access=False)
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(limited.get_absolute_url()).status_code, 404)
        self.assertNotContains(self.client.get("/"), "Salaries")
        admin = person("Root", is_admin=True)
        self.client.force_login(admin)
        self.assertContains(self.client.get("/"), "Salaries")
        self.assertEqual(self.client.get(limited.get_absolute_url()).status_code, 404)
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
        self.client.post(f"/todos/{new.pk}/toggle/")
        new.refresh_from_db()
        self.assertEqual(new.todo.completed_by, self.cleo)

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
        response = self.client.get(self.internal.get_absolute_url())
        self.assertContains(response, "1 to-do and 1 comments")
        self.client.post(f"/items/{self.internal.pk}/switch/", {"visible": "1"})
        self.assertIn(self.secret_todo, Item.objects.visible_to(self.cleo))

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

    def test_client_creates_visible_list(self):
        self.client.force_login(self.cleo)
        self.client.post(self.project.get_absolute_url(), {"title": "Our wishes"})
        self.assertTrue(Item.objects.get(title="Our wishes").is_client_visible)
