"""Creating, joining and leaving projects through the API: what the web
does (specs/api-cli.md, "Closing the gaps to the web")"""

from django.test import TestCase
from django.utils import timezone

from biwak.accounts.models import APIToken
from biwak.activity.models import Action, Event
from biwak.projects.models import Membership, Project
from biwak.test_utils import person, project


class ProjectGapsAPITest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.bob = person("Bob")
        self.cleo = person("Cleo", client=True)
        self.root = person("Root", is_admin=True)
        self.limited = project("HR", members=[self.bob], all_access=False)
        self.open = project("Team", members=[self.bob])

    def api(self, method, path, user, data=None):
        _token, secret = APIToken.create_for(user=user, title="T", access="write")
        return getattr(self.client, method)(
            f"/api/v1/{path}",
            data,
            content_type="application/json",
            headers={"authorization": f"Bearer {secret}"},
        )

    def test_create(self):
        response = self.api(
            "post", "projects/", self.ada, {"name": "New", "is_all_access": False}
        )
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()
        self.assertFalse(data["is_all_access"])
        self.assertTrue(data["is_member"])
        created = Project.objects.get(pk=data["id"])
        self.assertTrue(created.is_member(self.ada))
        # Limited: Bob doesn't see it
        self.assertEqual(
            self.api("get", f"projects/{created.pk}/", self.bob).status_code, 404
        )

    def test_create_defaults_to_all_access(self):
        response = self.api("post", "projects/", self.ada, {"name": "New"})
        self.assertTrue(response.json()["is_all_access"])

    def test_create_validates(self):
        response = self.api("post", "projects/", self.ada, {"name": "  "})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Project.objects.count(), 2)

    def test_update_validates_and_strips(self):
        """A name too long for the model was a 500; update didn't strip"""
        path = f"projects/{self.open.pk}/"
        response = self.api("patch", path, self.bob, {"name": "x" * 201})
        self.assertEqual(response.status_code, 400)
        self.assertIn("detail", response.json())
        response = self.api("patch", path, self.bob, {"name": "  Renamed  "})
        self.assertEqual(response.json()["name"], "Renamed")

    def test_clients_dont_create(self):
        response = self.api("post", "projects/", self.cleo, {"name": "New"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Project.objects.count(), 2)

    def test_joinable_for_admins_only(self):
        for user, expected in [
            (self.root, [self.limited.pk]),
            (self.ada, []),
            (self.cleo, []),
            (self.bob, []),
        ]:
            with self.subTest(user=user):
                response = self.api("get", "projects/joinable/", user)
                self.assertEqual([p["id"] for p in response.json()], expected)
        # Not the project the admin is in, not archived ones
        Membership.objects.create(project=self.limited, user=self.root)
        self.assertEqual(self.api("get", "projects/joinable/", self.root).json(), [])

    def test_admin_joins_limited(self):
        self.assertEqual(
            self.api("get", f"projects/{self.limited.pk}/", self.root).status_code, 404
        )
        response = self.api("post", f"projects/{self.limited.pk}/join/", self.root)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["is_member"])
        self.assertTrue(self.limited.is_member(self.root))
        self.assertEqual(Event.objects.filter(action=Action.JOINED).count(), 1)
        # Again: nothing changes
        self.api("post", f"projects/{self.limited.pk}/join/", self.root)
        self.assertEqual(Event.objects.filter(action=Action.JOINED).count(), 1)

    def test_admins_dont_join_archived_limited(self):
        """Like the web: only what ``joinable_projects()`` lists"""
        self.limited.archived_at = timezone.now()
        self.limited.save()
        response = self.api("post", f"projects/{self.limited.pk}/join/", self.root)
        self.assertEqual(response.status_code, 404)
        self.assertFalse(self.limited.is_member(self.root))

    def test_staff_join_all_access_not_limited(self):
        self.assertEqual(
            self.api("post", f"projects/{self.open.pk}/join/", self.ada).status_code,
            200,
        )
        self.assertTrue(self.open.is_member(self.ada))
        # A limited project doesn't exist for staff who aren't admins
        response = self.api("post", f"projects/{self.limited.pk}/join/", self.ada)
        self.assertEqual(response.status_code, 404)
        self.assertFalse(self.limited.is_member(self.ada))

    def test_clients_dont_join(self):
        for target in [self.open, self.limited]:
            response = self.api("post", f"projects/{target.pk}/join/", self.cleo)
            self.assertEqual(response.status_code, 403)
        self.assertFalse(Membership.objects.filter(user=self.cleo).exists())

    def test_staff_remove_members(self):
        Membership.objects.create(project=self.open, user=self.cleo)
        response = self.api(
            "delete", f"projects/{self.open.pk}/members/{self.cleo.pk}/", self.ada
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["id"], self.cleo.pk)
        self.assertFalse(self.open.is_member(self.cleo))
        event = Event.objects.get(action=Action.REMOVED)
        self.assertEqual(event.data["name"], "Cleo Example, Example Client Ltd")
        # Not a member (any more)
        response = self.api(
            "delete", f"projects/{self.open.pk}/members/{self.cleo.pk}/", self.ada
        )
        self.assertEqual(response.status_code, 404)

    def test_everybody_leaves(self):
        Membership.objects.create(project=self.open, user=self.cleo)
        response = self.api(
            "delete", f"projects/{self.open.pk}/members/{self.cleo.pk}/", self.cleo
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(self.open.is_member(self.cleo))
        self.assertTrue(Event.objects.filter(action=Action.LEFT).exists())
        # Staff too
        response = self.api(
            "delete", f"projects/{self.open.pk}/members/{self.bob.pk}/", self.bob
        )
        self.assertEqual(response.status_code, 200)

    def test_clients_dont_remove_others(self):
        Membership.objects.create(project=self.open, user=self.cleo)
        response = self.api(
            "delete", f"projects/{self.open.pk}/members/{self.bob.pk}/", self.cleo
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(self.open.is_member(self.bob))

    def test_no_access_no_removal(self):
        # Ada and the admin can't open the limited project: 404, not 403
        for user in [self.ada, self.root]:
            with self.subTest(user=user):
                response = self.api(
                    "delete",
                    f"projects/{self.limited.pk}/members/{self.bob.pk}/",
                    user,
                )
                self.assertEqual(response.status_code, 404)
        self.assertTrue(self.limited.is_member(self.bob))

    def test_read_only_tokens_write_nothing(self):
        _token, secret = APIToken.create_for(user=self.ada, title="T", access="read")
        headers = {"authorization": f"Bearer {secret}"}
        for method, path in [
            ("post", "projects/"),
            ("post", f"projects/{self.open.pk}/join/"),
            ("delete", f"projects/{self.open.pk}/members/{self.bob.pk}/"),
        ]:
            response = getattr(self.client, method)(
                f"/api/v1/{path}",
                {"name": "x"} if path == "projects/" else None,
                content_type="application/json",
                headers=headers,
            )
            self.assertEqual(response.status_code, 403, path)
