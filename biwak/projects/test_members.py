from django.core import mail
from django.test import TestCase

from biwak.accounts.models import APIToken, User
from biwak.activity.models import Action, Event, Subscription
from biwak.items import operations as ops
from biwak.projects.models import Membership
from biwak.test_utils import invite_data, person, project


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

    def test_add_offers_a_combobox_saying_who_people_are(self):
        # specs/ui.md, "Forms": the plain select without JavaScript,
        # data-combobox for combobox.js, the organization in the label and
        # the address to find people by
        dora = person("Dora", client=True)
        self.client.force_login(self.ada)
        response = self.client.get(self.add_url)
        self.assertContains(response, "data-combobox")
        self.assertContains(
            response,
            f'<option value="{dora.pk}" data-search="dora@example.org">'
            "Dora Example · Example Client Ltd</option>",
            html=True,
        )
        self.assertContains(response, "Bob Example · Our organization")

    def test_invite_client(self):
        self.client.force_login(self.ada)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                self.invite_url,
                invite_data(
                    [self.project],
                    {
                        "email": "Dora@Example.org",
                        "full_name": "Dora Example",
                        "organization": "Example Client Ltd",
                    },
                    notify="default",
                ),
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
                invite_data(
                    [self.project], {"email": "dora@example.org"}, notify="default"
                ),
            )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(
            User.objects.filter(email__iexact="dora@example.org").count(), 1
        )

    def test_only_admins_invite_staff(self):
        self.client.force_login(self.ada)
        # Staff can't even choose: the field isn't there, new people are clients
        self.assertNotContains(
            self.client.get(self.invite_url), 'name="person-0-is_client"'
        )
        self.client.post(
            self.invite_url,
            invite_data(
                [self.project],
                {"email": "eve@example.org", "is_client": ""},
                notify="default",
            ),
        )
        self.assertTrue(User.objects.get(email="eve@example.org").is_client)

        self.client.force_login(self.root)
        self.client.post(
            self.invite_url,
            invite_data(
                [self.project],
                {"email": "finn@example.org", "is_client": ""},
                notify="default",
            ),
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
            self.invite_url,
            invite_data([self.project], {"email": "x@example.org"}, notify="default"),
        )
        self.assertFalse(self.project.is_member(self.bob))
        self.assertFalse(User.objects.filter(email="x@example.org").exists())
        response = self.client.post(f"{self.url}{self.ada.pk}/remove/")
        self.assertEqual(response.status_code, 403)
        self.assertTrue(self.project.is_member(self.ada))
        # Nor themselves (decided 2026-11-22, specs/organizations.md)
        remove_self = f"{self.url}{self.cleo.pk}/remove/"
        self.assertEqual(self.client.get(remove_self).status_code, 403)
        self.assertEqual(self.client.post(remove_self).status_code, 403)
        self.assertTrue(self.project.is_member(self.cleo))
        response = self.client.get(self.url)
        self.assertNotContains(response, "/remove/")
        self.assertNotContains(response, "Leave")

    def test_partners_dont_remove_themselves(self):
        pia = person("Pia", organization="Example Agency")
        Membership.objects.create(project=self.project, user=pia)
        self.client.force_login(pia)
        response = self.client.post(f"{self.url}{pia.pk}/remove/")
        self.assertEqual(response.status_code, 403)
        self.assertTrue(self.project.is_member(pia))
        self.assertNotContains(self.client.get(self.url), "/remove/")

    def test_removing_asks_first(self):
        """GET is the question (a modal, or a page without JavaScript),
        POST removes"""
        self.client.force_login(self.ada)
        url = f"{self.url}{self.cleo.pk}/remove/"
        response = self.client.get(self.url)
        self.assertContains(
            response,
            f'<a class="dropdown-item" href="{url}" data-modal>'
            "Remove from the project…</a>",
            html=True,
        )
        response = self.client.get(url)
        self.assertContains(response, "Remove Cleo Example from Website?")
        self.assertContains(
            response, "won&#x27;t see the project or hear about it any more"
        )
        self.assertContains(response, "lose Cleo Example as assignee")
        self.assertTrue(self.project.is_member(self.cleo))
        response = self.client.get(url, headers={"HX-Modal": "true"})
        self.assertNotContains(response, "<html")
        self.assertContains(response, "Remove")
        response = self.client.post(url)
        self.assertRedirects(response, self.url)
        self.assertFalse(self.project.is_member(self.cleo))

    def test_removing_staff_from_an_all_access_project(self):
        Membership.objects.create(project=self.project, user=self.bob)
        self.client.force_login(self.ada)
        response = self.client.get(f"{self.url}{self.bob.pk}/remove/")
        self.assertContains(response, "still sees the project")
        self.assertNotContains(response, "won&#x27;t see")

    def test_staff_remove_themselves(self):
        self.client.force_login(self.ada)
        url = f"{self.url}{self.ada.pk}/remove/"
        response = self.client.get(url)
        self.assertContains(response, "Remove yourself from Website?")
        self.assertContains(response, "You still see it")
        self.assertRedirects(self.client.post(url), "/projects/")
        self.assertFalse(self.project.is_member(self.ada))
        limited = project("Salaries", members=[self.ada], all_access=False)
        url = f"/projects/{limited.pk}/people/{self.ada.pk}/remove/"
        response = self.client.get(url)
        self.assertContains(response, "You won&#x27;t see it any more")
        self.client.post(url)
        self.assertFalse(limited.is_member(self.ada))

    def test_removing_says_nothing_about_who_exists(self):
        """Non-members answer 404 like IDs nobody has, as in the API"""
        self.client.force_login(self.cleo)
        for pk in [self.bob.pk, 0]:
            response = self.client.post(f"{self.url}{pk}/remove/")
            self.assertEqual(response.status_code, 404, pk)

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
