"""Notified by default or only when tagged (specs/notifications.md): the
person's level for the project, chosen when adding and inviting"""

import json

from django.test import TestCase

from biwak import test_cli
from biwak.accounts.models import APIToken, NotificationLevel, User
from biwak.activity.models import LevelOverride, Notification
from biwak.items import operations as ops
from biwak.projects import operations as project_ops
from biwak.projects.models import Membership
from biwak.test_utils import (
    MODAL,
    assert_modal,
    assert_modal_redirect,
    invite_data,
    partner,
    person,
    project,
)


class Fixture:
    def setUp(self):
        super().setUp()
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.dan = person("Dan")
        self.cleo = person("Cleo", client=True)
        self.eve = person("Eve", client=True)
        self.root = person("Root", is_admin=True)
        self.project = project(members=[self.ada, self.cleo, self.eve])
        self.people_url = f"/projects/{self.project.pk}/people/"

    def level(self, user):
        override = LevelOverride.objects.filter(user=user, project=self.project)
        return override.get().level if override else None


class OperationsTest(Fixture, TestCase):
    def test_adding_stores_the_choice(self):
        project_ops.add_member(self.project, self.bob, actor=self.ada)
        project_ops.add_member(
            self.project, self.dan, actor=self.ada, notify=project_ops.NOTIFY_TAGGED
        )
        self.assertEqual(self.level(self.bob), NotificationLevel.EVERYTHING)
        self.assertEqual(self.level(self.dan), NotificationLevel.CONCERNS_ME)
        self.assertEqual(project_ops.notify_choice(self.bob, self.project), "default")
        self.assertEqual(project_ops.notify_choice(self.dan, self.project), "tagged")

    def test_adding_again_keeps_the_existing_override(self):
        project_ops.add_member(
            self.project, self.dan, actor=self.ada, notify=project_ops.NOTIFY_TAGGED
        )
        self.assertFalse(project_ops.add_member(self.project, self.dan, actor=self.ada))
        self.assertEqual(self.level(self.dan), NotificationLevel.CONCERNS_ME)
        # Also after leaving
        project_ops.remove_member(self.project, self.dan, actor=self.ada)
        project_ops.add_member(self.project, self.dan, actor=self.ada)
        self.assertEqual(self.level(self.dan), NotificationLevel.CONCERNS_ME)

    def test_inviting_takes_the_choice(self):
        user, _changed = project_ops.invite(
            self.project, email="new@example.org", actor=self.ada, notify="tagged"
        )
        self.assertEqual(self.level(user), NotificationLevel.CONCERNS_ME)

    def test_unknown_choice(self):
        with self.assertRaises(ValueError):
            project_ops.add_member(self.project, self.bob, actor=self.ada, notify="x")

    def test_clients_change_only_their_own(self):
        project_ops.set_notify_choice(
            self.project, self.cleo, "tagged", actor=self.cleo
        )
        self.assertEqual(self.level(self.cleo), NotificationLevel.CONCERNS_ME)
        with self.assertRaises(PermissionError):
            project_ops.set_notify_choice(
                self.project, self.eve, "tagged", actor=self.cleo
            )
        project_ops.set_notify_choice(self.project, self.eve, "tagged", actor=self.ada)


class PartnersTest(Fixture, TestCase):
    """Partners set their own choice, not others' (decided 2026-11-21 after
    a review): the operation, the page and the API"""

    def setUp(self):
        super().setUp()
        self.pia = partner()
        Membership.objects.create(project=self.project, user=self.pia)

    def call(self, method, path, data=None):
        _token, secret = APIToken.create_for(user=self.pia, title="T", access="write")
        return getattr(self.client, method)(
            f"/api/v1/projects/{self.project.pk}/members/{path}",
            json.dumps(data) if data is not None else None,
            content_type="application/json",
            headers={"authorization": f"Bearer {secret}"},
        )

    def test_operation(self):
        project_ops.set_notify_choice(self.project, self.pia, "tagged", actor=self.pia)
        self.assertEqual(self.level(self.pia), NotificationLevel.CONCERNS_ME)
        for other in [self.ada, self.cleo]:
            with self.assertRaises(PermissionError):
                project_ops.set_notify_choice(
                    self.project, other, "tagged", actor=self.pia
                )

    def test_page(self):
        self.client.force_login(self.pia)
        response = self.client.get(self.people_url)
        self.assertContains(response, f"people/{self.pia.pk}/notify/")
        self.assertNotContains(response, f"people/{self.ada.pk}/notify/")
        self.assertNotContains(response, f"people/{self.cleo.pk}/notify/")
        for other in [self.ada, self.cleo]:
            response = self.client.post(
                f"{self.people_url}{other.pk}/notify/", {"notify": "tagged"}
            )
            self.assertEqual(response.status_code, 403)
        self.assertIsNone(self.level(self.cleo))

    def test_api(self):
        members = {m["name"]: m for m in self.call("get", "").json()}
        self.assertEqual(members["Pia Example"]["notify"], "default")
        self.assertIsNone(members["Cleo Example"]["notify"])
        self.assertIsNone(members["Ada Example"]["notify"])
        response = self.call("patch", f"{self.cleo.pk}/", {"notify": "tagged"})
        self.assertEqual(response.status_code, 403)
        self.assertIsNone(self.level(self.cleo))


class MailsTest(Fixture, TestCase):
    """Only when tagged: posting to everybody tells the others, not them,
    unless they're mentioned"""

    def setUp(self):
        super().setUp()
        for user, notify in [(self.bob, "default"), (self.dan, "tagged")]:
            project_ops.add_member(self.project, user, actor=self.ada, notify=notify)

    def told(self, content):
        before = set(Notification.objects.values_list("pk", flat=True))
        with self.captureOnCommitCallbacks(execute=True):
            ops.create_message(
                project=self.project,
                title="News",
                content=content,
                creator=self.ada,
                visible=True,
            )
        return {
            n.user
            for n in Notification.objects.exclude(pk__in=before).select_related("user")
        }

    def test_posting(self):
        self.assertEqual(self.told("Hello"), {self.bob, self.cleo, self.eve})

    def test_but_a_mention_gets_through(self):
        told = self.told(f"[@Dan](person:{self.dan.pk})")
        self.assertEqual(told, {self.bob, self.cleo, self.eve, self.dan})


class PageTest(Fixture, TestCase):
    def setUp(self):
        super().setUp()
        project_ops.add_member(self.project, self.dan, actor=self.ada, notify="tagged")

    def test_staff_see_everybodys_choice(self):
        self.client.force_login(self.ada)
        response = self.client.get(self.people_url)
        self.assertContains(response, "Only when tagged")
        self.assertContains(response, "Notified by default")
        self.assertContains(response, f"people/{self.dan.pk}/notify/")
        self.assertContains(response, f"people/{self.cleo.pk}/notify/")

    def test_staff_change_others(self):
        self.client.force_login(self.ada)
        response = self.client.post(
            f"{self.people_url}{self.dan.pk}/notify/", {"notify": "default"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.level(self.dan), NotificationLevel.EVERYTHING)
        response = self.client.post(
            f"{self.people_url}{self.dan.pk}/notify/", {"notify": "x"}
        )
        # A bad value: the form again, with its error
        self.assertContains(response, "Select a valid choice")

    def test_a_modal_from_the_row_s_menu(self):
        """Decided 2026-11-22: a "…" menu on each row opens a modal, not a
        select with its own Save on every row"""
        self.client.force_login(self.ada)
        url = f"{self.people_url}{self.dan.pk}/notify/"
        page = self.client.get(self.people_url)
        self.assertNotContains(page, '<select name="notify"')
        self.assertContains(page, f'href="{url}"')
        self.assertContains(page, "Notifications…")
        response = self.client.get(url, headers=MODAL)
        assert_modal(self, response, title="Notifications of Dan Example")
        self.assertContains(
            response,
            'value="tagged" class="form-check-input" id="id_notify_1" required checked',
        )
        response = self.client.post(url, {"notify": "default"}, headers=MODAL)
        assert_modal_redirect(self, response, self.people_url)
        self.assertEqual(self.level(self.dan), NotificationLevel.EVERYTHING)
        # One's own
        response = self.client.get(f"{self.people_url}{self.ada.pk}/notify/")
        self.assertContains(response, "Your notifications")

    def test_invite_and_organizations_in_the_header(self):
        self.client.force_login(self.ada)
        html = self.client.get(self.people_url).content.decode()
        header = html.split('class="wb-page-header"', 1)[1].split("</h1>", 1)[1]
        header = header.split("data-people-group", 1)[0]
        for url in ["people/add/", "people/invite/", "/organizations/"]:
            self.assertIn(url, header)
        self.assertNotIn("btn-primary", header)

    def test_add_and_invite_forms_take_the_choice(self):
        self.client.force_login(self.ada)
        for name in ("add", "invite"):
            self.assertContains(
                self.client.get(f"{self.people_url}{name}/"), 'id="id_notify_1"'
            )
        self.client.post(
            f"{self.people_url}add/", {"user": self.bob.pk, "notify": "tagged"}
        )
        self.assertEqual(self.level(self.bob), NotificationLevel.CONCERNS_ME)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                f"{self.people_url}invite/",
                invite_data(
                    [self.project], {"email": "x@example.org"}, notify="tagged"
                ),
            )
        user = User.objects.get(email="x@example.org")
        self.assertEqual(self.level(user), NotificationLevel.CONCERNS_ME)

    def test_a_client_sees_and_changes_only_their_own(self):
        self.client.force_login(self.cleo)
        response = self.client.get(self.people_url)
        self.assertContains(response, f"people/{self.cleo.pk}/notify/")
        self.assertNotContains(response, f"people/{self.eve.pk}/notify/")
        self.assertNotContains(response, f"people/{self.dan.pk}/notify/")
        response = self.client.post(
            f"{self.people_url}{self.cleo.pk}/notify/", {"notify": "tagged"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.level(self.cleo), NotificationLevel.CONCERNS_ME)
        for other in [self.eve, self.dan, self.ada]:
            with self.subTest(other=other):
                response = self.client.post(
                    f"{self.people_url}{other.pk}/notify/", {"notify": "tagged"}
                )
                self.assertEqual(response.status_code, 403)
                response = self.client.get(f"{self.people_url}{other.pk}/notify/")
                self.assertEqual(response.status_code, 403)
        self.assertIsNone(self.level(self.eve))

    def test_outsiders_get_404(self):
        limited = project("Salaries", members=[self.ada], all_access=False)
        self.client.force_login(self.cleo)
        response = self.client.post(
            f"/projects/{limited.pk}/people/{self.ada.pk}/notify/",
            {"notify": "tagged"},
        )
        self.assertEqual(response.status_code, 404)
        # A person who isn't a member
        self.client.force_login(self.ada)
        response = self.client.post(
            f"{self.people_url}{self.bob.pk}/notify/", {"notify": "tagged"}
        )
        self.assertEqual(response.status_code, 404)

    def test_anonymous_is_sent_to_login(self):
        response = self.client.post(
            f"{self.people_url}{self.dan.pk}/notify/", {"notify": "tagged"}
        )
        self.assertNotEqual(response.status_code, 200)
        self.assertIsNone(self.level(self.cleo))


class APITest(Fixture, TestCase):
    def call(self, user, method, path, data=None):
        _token, secret = APIToken.create_for(user=user, title="T", access="write")
        return getattr(self.client, method)(
            f"/api/v1/projects/{self.project.pk}/members/{path}",
            json.dumps(data) if data is not None else None,
            content_type="application/json",
            headers={"authorization": f"Bearer {secret}"},
        )

    def test_list_shows_the_choice_to_staff(self):
        project_ops.add_member(self.project, self.dan, actor=self.ada, notify="tagged")
        members = {m["name"]: m for m in self.call(self.ada, "get", "").json()}
        self.assertEqual(members["Dan Example"]["notify"], "tagged")
        self.assertEqual(members["Cleo Example"]["notify"], "default")
        # A client sees only their own
        members = {m["name"]: m for m in self.call(self.cleo, "get", "").json()}
        self.assertEqual(members["Cleo Example"]["notify"], "default")
        self.assertIsNone(members["Eve Example"]["notify"])
        self.assertIsNone(members["Ada Example"]["notify"])

    def test_add(self):
        response = self.call(self.ada, "post", "", {"person_id": self.bob.pk})
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["notify"], "default")
        response = self.call(
            self.ada, "post", "", {"person_id": self.dan.pk, "notify": "tagged"}
        )
        self.assertEqual(response.json()["notify"], "tagged")
        self.assertEqual(self.level(self.dan), NotificationLevel.CONCERNS_ME)
        # Adding again changes nothing
        self.call(self.ada, "post", "", {"person_id": self.dan.pk, "notify": "default"})
        self.assertEqual(self.level(self.dan), NotificationLevel.CONCERNS_ME)
        self.assertEqual(
            self.call(self.ada, "post", "", {"person_id": 0}).status_code, 404
        )
        self.assertEqual(
            self.call(
                self.ada, "post", "", {"person_id": self.bob.pk, "notify": "x"}
            ).status_code,
            422,
        )

    def test_invite(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.call(
                self.ada,
                "post",
                "invite/",
                {"email": "new@example.org", "name": "New", "notify": "tagged"},
            )
        self.assertEqual(response.status_code, 201, response.content)
        user = User.objects.get(email="new@example.org")
        self.assertTrue(user.is_client)
        self.assertEqual(self.level(user), NotificationLevel.CONCERNS_ME)
        self.assertEqual(
            self.call(self.ada, "post", "invite/", {"email": "nope"}).status_code, 400
        )
        # Only admins create staff
        response = self.call(
            self.ada, "post", "invite/", {"email": "s@example.org", "is_client": False}
        )
        self.assertEqual(response.status_code, 400)

    def test_clients_can_neither_add_nor_invite(self):
        self.assertEqual(
            self.call(self.cleo, "post", "", {"person_id": self.bob.pk}).status_code,
            403,
        )
        self.assertEqual(
            self.call(
                self.cleo, "post", "invite/", {"email": "a@example.org"}
            ).status_code,
            403,
        )
        self.assertFalse(User.objects.filter(email="a@example.org").exists())

    def test_change(self):
        response = self.call(self.ada, "patch", f"{self.eve.pk}/", {"notify": "tagged"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["notify"], "tagged")
        self.assertEqual(self.level(self.eve), NotificationLevel.CONCERNS_ME)

    def test_clients_change_only_their_own(self):
        response = self.call(
            self.cleo, "patch", f"{self.cleo.pk}/", {"notify": "tagged"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.level(self.cleo), NotificationLevel.CONCERNS_ME)
        for other in [self.eve, self.ada]:
            response = self.call(
                self.cleo, "patch", f"{other.pk}/", {"notify": "tagged"}
            )
            self.assertEqual(response.status_code, 403)
        self.assertIsNone(self.level(self.eve))
        # Not a member: 404
        self.assertEqual(
            self.call(
                self.ada, "patch", f"{self.bob.pk}/", {"notify": "tagged"}
            ).status_code,
            404,
        )


class CLITest(Fixture, test_cli.CLITest):
    def setUp(self):
        # The CLI test case brings Ada and the project
        test_cli.CLITest.setUp(self)
        self.bob = person("Bob")
        self.dan = person("Dan")
        self.eve = person("Eve", client=True)
        Membership.objects.create(project=self.project, user=self.eve)

    def test_members_show_the_choice(self):
        project_ops.add_member(self.project, self.dan, actor=self.ada, notify="tagged")
        output = self.biwak("members", self.project.pk).output
        self.assertIn("only when tagged", output)
        self.assertIn("notified by default", output)
        data = json.loads(self.biwak("members", self.project.pk, "--json").stdout)
        self.assertEqual(
            {m["name"]: m["notify"] for m in data}["Dan Example"], "tagged"
        )

    def test_add_and_invite(self):
        result = self.biwak("member", "add", self.project.pk, self.bob.pk)
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(self.level(self.bob), NotificationLevel.EVERYTHING)
        result = self.biwak(
            "member", "add", self.project.pk, self.dan.pk, "--only-tagged"
        )
        self.assertIn("only when tagged", result.output)
        self.assertEqual(self.level(self.dan), NotificationLevel.CONCERNS_ME)
        with self.captureOnCommitCallbacks(execute=True):
            result = self.biwak(
                "member", "invite", self.project.pk, "new@example.org",
                "--name", "New", "--only-tagged", "--json",
            )  # fmt: skip
        self.assertEqual(result.exit_code, 0, result.output)
        user = User.objects.get(email="new@example.org")
        self.assertEqual(self.level(user), NotificationLevel.CONCERNS_ME)
