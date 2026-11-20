from django.core import mail
from django.test import TestCase

from biwak.accounts.models import User
from biwak.activity.models import Action, Event, Subscription
from biwak.items import operations as ops
from biwak.projects.models import Membership
from biwak.test_utils import person, project


class MembersTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.root = person("Root", is_admin=True)
        self.project = project(members=[self.ada, self.cleo])
        self.url = f"/projects/{self.project.pk}/people/"

    def test_add_existing_person(self):
        self.client.force_login(self.ada)
        response = self.client.get(self.url)
        self.assertContains(response, "Bob Example")  # offered
        self.client.post(self.url, {"form": "add", "user": self.bob.pk})
        self.assertTrue(self.project.is_member(self.bob))
        event = Event.objects.get(action=Action.ADDED)
        self.assertEqual(event.data["name"], "Bob Example")
        self.assertFalse(Subscription.objects.filter(user=self.bob).exists())
        self.assertContains(
            self.client.get(self.project.get_absolute_url()), "Bob Example"
        )

    def test_invite_client(self):
        self.client.force_login(self.ada)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                self.url,
                {
                    "form": "invite",
                    "email": "Dora@Example.org",
                    "full_name": "Dora Example",
                    "organization": "Example Client Ltd",
                },
            )
        dora = User.objects.get(email__iexact="dora@example.org")
        self.assertTrue(dora.is_client)
        self.assertTrue(self.project.is_member(dora))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.project.get_absolute_url(), mail.outbox[0].body)
        self.assertEqual(mail.outbox[0].to, [dora.email])
        # Inviting again adds nothing and mails nobody
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(self.url, {"form": "invite", "email": "dora@example.org"})
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            User.objects.filter(email__iexact="dora@example.org").count(), 1
        )

    def test_only_admins_invite_staff(self):
        self.client.force_login(self.ada)
        # Staff can't even choose: the field isn't there, new people are clients
        self.assertNotContains(self.client.get(self.url), 'name="is_client"')
        self.client.post(
            self.url, {"form": "invite", "email": "eve@example.org", "is_client": ""}
        )
        self.assertTrue(User.objects.get(email="eve@example.org").is_client)

        self.client.force_login(self.root)
        self.client.post(
            self.url, {"form": "invite", "email": "finn@example.org", "is_client": ""}
        )
        self.assertFalse(User.objects.get(email="finn@example.org").is_client)

    def test_clients_dont_manage(self):
        self.client.force_login(self.cleo)
        response = self.client.get(self.url)
        self.assertContains(response, "Ada Example")
        self.assertNotContains(response, "ada@example.org")
        self.assertNotContains(response, 'value="invite"')
        self.client.post(self.url, {"form": "add", "user": self.bob.pk})
        self.client.post(self.url, {"form": "invite", "email": "x@example.org"})
        self.assertFalse(self.project.is_member(self.bob))
        self.assertFalse(User.objects.filter(email="x@example.org").exists())
        response = self.client.post(f"{self.url}{self.ada.pk}/remove/")
        self.assertEqual(response.status_code, 403)
        self.assertTrue(self.project.is_member(self.ada))
        # But they can leave
        self.client.post(f"{self.url}{self.cleo.pk}/remove/")
        self.assertFalse(self.project.is_member(self.cleo))
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_removing_drops_subscriptions_without_access(self):
        visible = ops.create_list(
            project=self.project, title="Shared", creator=self.ada, visible=True
        )
        todo = ops.create_todo(todolist=visible, title="Visible", creator=self.ada)
        ops.assign(todo, [self.cleo], actor=self.ada)
        self.assertTrue(Subscription.objects.filter(user=self.cleo).exists())
        self.client.force_login(self.ada)
        self.client.post(f"{self.url}{self.cleo.pk}/remove/")
        self.assertFalse(self.project.is_member(self.cleo))
        self.assertFalse(Subscription.objects.filter(user=self.cleo).exists())
        self.assertTrue(
            Event.objects.filter(
                action=Action.REMOVED, data__name__icontains="cleo"
            ).exists()
        )

    def test_staff_keep_subscriptions_in_all_access_projects(self):
        visible = ops.create_list(project=self.project, title="L", creator=self.ada)
        todo = ops.create_todo(todolist=visible, title="T", creator=self.ada)
        ops.assign(todo, [self.ada], actor=self.ada)
        Membership.objects.create(project=self.project, user=self.bob)
        self.client.force_login(self.bob)
        self.client.post(f"{self.url}{self.ada.pk}/remove/")
        self.assertTrue(Subscription.objects.filter(user=self.ada).exists())

    def test_limited_project_hidden(self):
        limited = project("Salaries", members=[self.ada], all_access=False)
        self.client.force_login(self.bob)
        url = f"/projects/{limited.pk}/people/"
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.ada)
        self.client.post(url, {"form": "add", "user": self.bob.pk})
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(limited.get_absolute_url()).status_code, 200)
