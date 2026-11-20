"""Notification settings, overrides and the @ list through the pages and the
API, as staff, as a client and as a person without access
(specs/notifications.md)"""

from django.test import TestCase

from biwak.accounts.models import APIToken, MailDelivery, NotificationLevel
from biwak.activity import mentions
from biwak.activity.models import LevelOverride
from biwak.activity.operations import set_level_override
from biwak.items import operations as ops
from biwak.test_utils import person, project


class SettingsBase(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        # Staff, but not a member of the limited project
        self.dora = person("Dora")
        # A client of another project
        self.eve = person("Eve", client=True)
        self.project = project(
            members=[self.ada, self.bob, self.cleo], all_access=False
        )
        self.other = project("Other", members=[self.eve])
        self.shared = ops.create_list(
            project=self.project, title="Shared", creator=self.ada, visible=True
        )
        self.internal = ops.create_list(
            project=self.project, title="Internal", creator=self.ada
        )
        self.todo = ops.create_todo(
            todolist=self.shared, title="Order the tent", creator=self.ada
        )
        self.secret = ops.create_todo(
            todolist=self.internal, title="Secret plan", creator=self.ada
        )


class SettingsPagesTest(SettingsBase):
    def test_login_required(self):
        response = self.client.get("/accounts/notifications/")
        self.assertEqual(response.status_code, 302)
        response = self.client.get(f"/items/{self.todo.pk}/mentionable/")
        self.assertEqual(response.status_code, 302)

    def test_settings_page(self):
        for user in [self.ada, self.cleo]:
            with self.subTest(user=user):
                self.client.force_login(user)
                response = self.client.get("/accounts/notifications/")
                self.assertContains(response, "Only what concerns me")
                self.assertContains(response, "A daily digest")
                response = self.client.post(
                    "/accounts/notifications/",
                    {"notification_level": "concerns_me", "mail_delivery": "digest"},
                )
                self.assertRedirects(response, "/accounts/notifications/")
                user.refresh_from_db()
                self.assertEqual(user.notification_level, NotificationLevel.CONCERNS_ME)
                self.assertEqual(user.mail_delivery, MailDelivery.DIGEST)
                # Invalid values change nothing
                response = self.client.post(
                    "/accounts/notifications/",
                    {"notification_level": "always", "mail_delivery": "each"},
                )
                self.assertEqual(response.status_code, 200)
                user.refresh_from_db()
                self.assertEqual(user.mail_delivery, MailDelivery.DIGEST)

    def test_settings_page_lists_visible_overrides_only(self):
        set_level_override(self.cleo, "nothing", project=self.project)
        set_level_override(self.cleo, "everything", item=self.todo)
        # Set while it was visible, e.g.; never shown now
        set_level_override(self.cleo, "everything", item=self.secret)
        self.client.force_login(self.cleo)
        response = self.client.get("/accounts/notifications/")
        self.assertContains(response, "Website")
        self.assertContains(response, "Order the tent")
        self.assertNotContains(response, "Secret plan")

    def test_project_override(self):
        url = f"/projects/{self.project.pk}/notifications/"
        for user in [self.ada, self.cleo]:
            with self.subTest(user=user):
                self.client.force_login(user)
                self.assertContains(self.client.get(url), "As usual (Everything)")
                response = self.client.post(url, {"level": "nothing"})
                self.assertRedirects(response, self.project.get_absolute_url())
                self.assertEqual(
                    LevelOverride.objects.get(user=user, project=self.project).level,
                    NotificationLevel.NOTHING,
                )
                self.client.post(url, {"level": ""})
                self.assertFalse(LevelOverride.objects.filter(user=user).exists())
                self.assertEqual(
                    self.client.post(url, {"level": "always"}).status_code, 404
                )
        # Linked from the project page's More menu, for everybody
        self.assertContains(self.client.get(self.project.get_absolute_url()), url)

    def test_project_override_without_access(self):
        url = f"/projects/{self.project.pk}/notifications/"
        for user in [self.dora, self.eve]:
            with self.subTest(user=user):
                self.client.force_login(user)
                self.assertEqual(self.client.get(url).status_code, 404)
                self.assertEqual(
                    self.client.post(url, {"level": "nothing"}).status_code, 404
                )
        self.assertFalse(LevelOverride.objects.exists())

    def test_item_override(self):
        url = f"/items/{self.todo.pk}/notifications/"
        for user in [self.ada, self.cleo]:
            with self.subTest(user=user):
                self.client.force_login(user)
                # Next to the subscribe button
                self.assertContains(self.client.get(self.todo.get_absolute_url()), url)
                response = self.client.post(url, {"level": "concerns_me"})
                self.assertRedirects(response, self.todo.get_absolute_url())
                self.assertEqual(
                    LevelOverride.objects.get(user=user, item=self.todo).level,
                    NotificationLevel.CONCERNS_ME,
                )
                self.client.post(url, {"level": ""})
                self.assertFalse(LevelOverride.objects.filter(user=user).exists())

    def test_list_override_on_the_list_page(self):
        url = f"/items/{self.shared.pk}/notifications/"
        for user in [self.ada, self.cleo]:
            with self.subTest(user=user):
                self.client.force_login(user)
                self.assertContains(
                    self.client.get(self.shared.get_absolute_url()), url
                )
                response = self.client.post(url, {"level": "nothing"})
                self.assertRedirects(response, self.shared.get_absolute_url())
                self.assertEqual(
                    LevelOverride.objects.get(user=user, item=self.shared).level,
                    NotificationLevel.NOTHING,
                )
                self.client.post(url, {"level": ""})
                self.assertFalse(LevelOverride.objects.filter(user=user).exists())

    def test_item_override_of_internal_items(self):
        url = f"/items/{self.secret.pk}/notifications/"
        for user in [self.cleo, self.dora, self.eve]:
            with self.subTest(user=user):
                self.client.force_login(user)
                self.assertEqual(
                    self.client.post(url, {"level": "nothing"}).status_code, 404
                )
        self.assertFalse(LevelOverride.objects.exists())

    def test_user_menu_links_the_settings(self):
        self.client.force_login(self.cleo)
        self.assertContains(self.client.get("/"), 'href="/accounts/notifications/"')


class MentionableTest(SettingsBase):
    def names(self, response):
        return {p["name"]: (p["available"], p["reason"]) for p in response.json()}

    def test_only_who_can_see_is_available(self):
        self.client.force_login(self.ada)
        # The internal to-do: the client listed, but not available
        found = self.names(
            self.client.get(f"/items/{self.secret.pk}/mentionable/", {"q": "ex"})
        )
        self.assertEqual(
            found,
            {
                "Ada Example": (True, ""),
                "Bob Example": (True, ""),
                "Cleo Example": (False, "can't see internal items"),
                "Dora Example": (False, "not a member of this project"),
            },
        )
        # The visible to-do: the client too; Eve is nobody's business here
        found = self.names(
            self.client.get(f"/items/{self.todo.pk}/mentionable/", {"q": "ex"})
        )
        self.assertEqual(found["Cleo Example"], (True, ""))
        self.assertNotIn("Eve Example", found)
        # To-dos not created yet: who can see the list
        found = self.names(
            self.client.get(f"/lists/{self.internal.pk}/mentionable/", {"q": "cleo"})
        )
        self.assertEqual(found, {"Cleo Example": (False, "can't see internal items")})
        self.assertEqual(
            self.client.get(f"/lists/{self.todo.pk}/mentionable/").status_code, 404
        )

    def test_clients(self):
        self.client.force_login(self.cleo)
        result = self.client.get(f"/items/{self.todo.pk}/mentionable/").json()
        self.assertEqual(
            {p["name"] for p in result}, {"Ada Example", "Bob Example", "Cleo Example"}
        )
        # Clients don't see addresses
        self.assertEqual({p["email"] for p in result}, {""})
        for url in [
            f"/items/{self.secret.pk}/mentionable/",
            f"/lists/{self.internal.pk}/mentionable/",
        ]:
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_without_access(self):
        for user in [self.dora, self.eve]:
            self.client.force_login(user)
            self.assertEqual(
                self.client.get(f"/items/{self.todo.pk}/mentionable/").status_code,
                404,
            )

    def test_fields_have_the_list(self):
        self.client.force_login(self.cleo)
        response = self.client.get(self.todo.get_absolute_url())
        self.assertContains(
            response, f'data-mentions="/items/{self.todo.pk}/mentionable/"'
        )
        response = self.client.get(self.shared.get_absolute_url())
        self.assertContains(
            response, f'data-mentions="/lists/{self.shared.pk}/mentionable/"'
        )


class SettingsAPITest(SettingsBase):
    def headers(self, user, access="write"):
        _token, secret = APIToken.create_for(user=user, title="T", access=access)
        return {"authorization": f"Bearer {secret}"}

    def call(self, method, user, path, data=None, access="write"):
        return getattr(self.client, method)(
            f"/api/v1/{path}",
            data,
            content_type="application/json",
            headers=self.headers(user, access),
        )

    def test_me(self):
        for user in [self.ada, self.cleo]:
            with self.subTest(user=user):
                response = self.call("get", user, "me/notifications/")
                self.assertEqual(
                    response.json(), {"level": "everything", "delivery": "each"}
                )
                response = self.call(
                    "put", user, "me/notifications/", {"delivery": "digest"}
                )
                self.assertEqual(
                    response.json(), {"level": "everything", "delivery": "digest"}
                )
                response = self.call(
                    "put", user, "me/notifications/", {"level": "nothing"}
                )
                self.assertEqual(
                    response.json(), {"level": "nothing", "delivery": "digest"}
                )
                response = self.call(
                    "put", user, "me/notifications/", {"level": "always"}
                )
                self.assertEqual(response.status_code, 422)
        # Read-only tokens only read
        response = self.call(
            "put", self.ada, "me/notifications/", {"level": "everything"}, "read"
        )
        self.assertEqual(response.status_code, 403)

    def test_project_override(self):
        path = f"projects/{self.project.pk}/notifications/"
        for user in [self.ada, self.cleo]:
            with self.subTest(user=user):
                self.assertEqual(
                    self.call("get", user, path).json(),
                    {"project_id": self.project.pk, "level": None},
                )
                response = self.call("put", user, path, {"level": "concerns_me"})
                self.assertEqual(response.json()["level"], "concerns_me")
                self.assertEqual(
                    self.call("get", user, path).json()["level"], "concerns_me"
                )
                self.assertIsNone(self.call("delete", user, path).json()["level"])
                self.assertFalse(LevelOverride.objects.filter(user=user).exists())

    def test_project_override_without_access(self):
        path = f"projects/{self.project.pk}/notifications/"
        for user in [self.dora, self.eve]:
            with self.subTest(user=user):
                self.assertEqual(self.call("get", user, path).status_code, 404)
                self.assertEqual(
                    self.call("put", user, path, {"level": "nothing"}).status_code,
                    404,
                )
                self.assertEqual(self.call("delete", user, path).status_code, 404)
        self.assertFalse(LevelOverride.objects.exists())

    def test_item_override(self):
        path = f"items/{self.todo.pk}/notifications/"
        for user in [self.ada, self.cleo]:
            with self.subTest(user=user):
                response = self.call("put", user, path, {"level": "nothing"})
                self.assertEqual(
                    response.json(), {"item_id": self.todo.pk, "level": "nothing"}
                )
                self.assertEqual(
                    self.call("get", user, path).json()["level"], "nothing"
                )
                self.call("delete", user, path)
                self.assertFalse(LevelOverride.objects.filter(user=user).exists())

    def test_item_override_of_internal_items(self):
        path = f"items/{self.secret.pk}/notifications/"
        self.assertEqual(self.call("get", self.ada, path).status_code, 200)
        for user in [self.cleo, self.dora, self.eve]:
            with self.subTest(user=user):
                self.assertEqual(self.call("get", user, path).status_code, 404)
                self.assertEqual(
                    self.call("put", user, path, {"level": "nothing"}).status_code,
                    404,
                )
                self.assertEqual(self.call("delete", user, path).status_code, 404)
        self.assertFalse(LevelOverride.objects.exists())

    def test_mentionable(self):
        response = self.call(
            "get", self.ada, f"items/{self.secret.pk}/mentionable/?q=cleo"
        )
        self.assertEqual(
            response.json(),
            [
                {
                    "id": self.cleo.pk,
                    "name": "Cleo Example",
                    "short_name": "Cleo",
                    "email": "cleo@example.org",
                    "available": False,
                    "reason": "can't see internal items",
                }
            ],
        )
        for user in [self.cleo, self.dora, self.eve]:
            with self.subTest(user=user):
                response = self.call(
                    "get", user, f"items/{self.secret.pk}/mentionable/"
                )
                self.assertEqual(response.status_code, 404)

    def test_mentions_written_through_the_api(self):
        """``@email`` and an unambiguous ``@Name`` become mentions, only of
        people who can see the item"""
        response = self.call(
            "post",
            self.ada,
            f"items/{self.secret.pk}/comments/",
            {"content": "@bob@example.org and @Cleo, look"},
        )
        self.assertEqual(response.status_code, 201)
        content = response.json()["content"]
        self.assertIn(mentions.syntax(self.bob), content)
        # Cleo can't see the internal to-do
        self.assertIn("@Cleo, look", content)
        self.assertNotIn(f"person:{self.cleo.pk}", content)
