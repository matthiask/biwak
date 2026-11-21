from django.core import mail
from django.test import TestCase

from biwak.accounts.models import APIToken, User
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
        self.add_url = f"{self.url}add/"
        self.invite_url = f"{self.url}invite/"

    def test_add_existing_person(self):
        self.client.force_login(self.ada)
        response = self.client.get(self.add_url)
        self.assertContains(response, "Bob Example")  # offered
        self.client.post(self.add_url, {"notify": "default", "user": self.bob.pk})
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
                self.invite_url,
                {
                    "notify": "default",
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
            self.client.post(
                self.invite_url,
                {"notify": "default", "email": "dora@example.org"},
            )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            User.objects.filter(email__iexact="dora@example.org").count(), 1
        )

    def test_only_admins_invite_staff(self):
        self.client.force_login(self.ada)
        # Staff can't even choose: the field isn't there, new people are clients
        self.assertNotContains(self.client.get(self.invite_url), 'name="is_client"')
        self.client.post(
            self.invite_url,
            {
                "notify": "default",
                "email": "eve@example.org",
                "is_client": "",
            },
        )
        self.assertTrue(User.objects.get(email="eve@example.org").is_client)

        self.client.force_login(self.root)
        self.client.post(
            self.invite_url,
            {
                "notify": "default",
                "email": "finn@example.org",
                "is_client": "",
            },
        )
        self.assertFalse(User.objects.get(email="finn@example.org").is_client)

    def test_clients_dont_manage(self):
        self.client.force_login(self.cleo)
        response = self.client.get(self.url)
        self.assertContains(response, "Ada Example")
        self.assertNotContains(response, "ada@example.org")
        self.assertNotContains(response, 'value="invite"')
        self.client.post(self.add_url, {"notify": "default", "user": self.bob.pk})
        self.client.post(
            self.invite_url, {"notify": "default", "email": "x@example.org"}
        )
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
        self.client.post(f"{url}add/", {"notify": "default", "user": self.bob.pk})
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(limited.get_absolute_url()).status_code, 200)


class LimitingTest(TestCase):
    """Making a project limited takes access from staff who aren't members:
    their subscriptions go, as when they're removed (``update_project()``)"""

    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.project = project(members=[self.ada])
        self.list = ops.create_list(project=self.project, title="L", creator=self.ada)
        self.todo = ops.create_todo(todolist=self.list, title="T", creator=self.bob)

    def subscribers(self):
        return set(
            Subscription.objects.filter(item__project=self.project).values_list(
                "user__full_name", flat=True
            )
        )

    def test_web(self):
        self.assertEqual(self.subscribers(), {"Ada Example", "Bob Example"})
        self.client.force_login(self.ada)
        response = self.client.post(
            f"/projects/{self.project.pk}/edit/",
            {"name": "Website", "description": "", "is_all_access": ""},
        )
        self.assertRedirects(response, self.project.get_absolute_url())
        self.assertEqual(self.subscribers(), {"Ada Example"})
        self.assertEqual(Event.objects.filter(action=Action.EDITED_PROJECT).count(), 1)

    def test_api(self):
        _token, secret = APIToken.create_for(user=self.ada, title="T", access="write")
        response = self.client.patch(
            f"/api/v1/projects/{self.project.pk}/",
            {"is_all_access": False},
            content_type="application/json",
            headers={"authorization": f"Bearer {secret}"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.subscribers(), {"Ada Example"})

    def test_an_unchanged_form_records_nothing(self):
        self.client.force_login(self.ada)
        self.client.post(
            f"/projects/{self.project.pk}/edit/",
            {"name": "Website", "description": "", "is_all_access": "1"},
        )
        self.assertFalse(Event.objects.filter(action=Action.EDITED_PROJECT).exists())
        self.assertEqual(self.subscribers(), {"Ada Example", "Bob Example"})


class MemberModalsTest(TestCase):
    """Adding, inviting, creating and editing projects as modals"""

    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.project = project(members=[self.ada])
        self.client.force_login(self.ada)
        self.headers = {"HTTP_HX_MODAL": "true"}

    def test_forms_render_without_the_page(self):
        for url in (
            f"/projects/{self.project.pk}/people/add/",
            f"/projects/{self.project.pk}/people/invite/",
            f"/projects/{self.project.pk}/edit/",
            "/projects/new/",
        ):
            with self.subTest(url=url):
                page = self.client.get(url)
                self.assertContains(page, "<nav")
                response = self.client.get(url, **self.headers)
                self.assertContains(response, 'id="modal-title"')
                self.assertContains(response, "data-modal-close")
                self.assertNotContains(response, "<nav")

    def test_saving_redirects_through_htmx(self):
        response = self.client.post(
            f"/projects/{self.project.pk}/people/add/",
            {"notify": "default", "user": self.bob.pk},
            **self.headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["HX-Redirect"], f"/projects/{self.project.pk}/people/"
        )
        self.assertTrue(self.project.is_member(self.bob))

    def test_errors_stay_in_the_dialog(self):
        response = self.client.post(
            f"/projects/{self.project.pk}/people/invite/",
            {"notify": "default", "email": "nope"},
            **self.headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("HX-Redirect", response)
        self.assertContains(response, "wb-form-title")
        response = self.client.post("/projects/new/", {"name": ""}, **self.headers)
        self.assertContains(response, "invalid-feedback")

    def test_create_as_a_modal(self):
        response = self.client.post(
            "/projects/new/", {"name": "Fresh", "color": ""}, **self.headers
        )
        self.assertIn("HX-Redirect", response)

    def test_clients_get_no_forms(self):
        cleo = person("Cleo", client=True)
        Membership.objects.create(project=self.project, user=cleo)
        self.client.force_login(cleo)
        for url in (
            f"/projects/{self.project.pk}/people/add/",
            f"/projects/{self.project.pk}/edit/",
            "/projects/new/",
        ):
            self.assertEqual(self.client.get(url, **self.headers).status_code, 403)
