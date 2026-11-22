"""Templates through the API (specs/templates.md)"""

from django.test import TestCase

from biwak.accounts.models import APIToken
from biwak.activity.models import Action, Event
from biwak.items.models import Item, Kind
from biwak.projects.models import Project
from biwak.projects.test_templates import Fixture


class TemplatesAPITest(Fixture, TestCase):
    def api(self, method, path, user, data=None):
        _token, secret = APIToken.create_for(user=user, title="T", access="write")
        kwargs = {"headers": {"authorization": f"Bearer {secret}"}}
        if method != "get":
            kwargs["content_type"] = "application/json"
        return getattr(self.client, method)(f"/api/v1/{path}", data, **kwargs)

    def test_list(self):
        data = self.api("get", "projects/", self.bob, {"templates": "true"}).json()
        self.assertEqual([p["name"] for p in data], ["Web project"])
        self.assertTrue(data[0]["is_template"])
        data = self.api("get", "projects/", self.bob).json()
        self.assertNotIn("Web project", [p["name"] for p in data])
        for user in [self.cleo, self.pia]:
            data = self.api("get", "projects/", user, {"templates": "true"}).json()
            self.assertEqual(data, [])
            response = self.api("get", f"projects/{self.template.pk}/", user)
            self.assertEqual(response.status_code, 404)
            response = self.api("get", f"lists/{self.list.pk}/", user)
            self.assertEqual(response.status_code, 404)

    def test_create_template(self):
        response = self.api(
            "post", "projects/", self.bob, {"name": "Event", "is_template": True}
        )
        self.assertEqual(response.status_code, 201, response.content)
        template = Project.objects.get(name="Event")
        self.assertTrue(template.is_template)
        self.assertFalse(template.memberships.exists())
        response = self.api(
            "post", "projects/", self.pia, {"name": "X", "is_template": True}
        )
        self.assertEqual(response.status_code, 403)

    def test_create_from_template(self):
        response = self.api(
            "post",
            "projects/",
            self.ada,
            {
                "name": "Shop",
                "template": self.template.pk,
                "is_all_access": False,
                "member_ids": [self.bob.pk],
            },
        )
        self.assertEqual(response.status_code, 201, response.content)
        shop = Project.objects.get(pk=response.json()["id"])
        self.assertFalse(shop.is_template)
        kickoff = Item.objects.get(project=shop, title="Kick-off")
        self.assertEqual(list(kickoff.todo.assignees.all()), [self.bob])
        self.assertEqual(
            Event.objects.filter(project=shop, action=Action.CREATED).count(), 1
        )
        events = self.api("get", f"projects/{shop.pk}/feed/", self.ada).json()
        [event] = [e for e in events["results"] if e["action"] == "created"]
        self.assertEqual(event["data"]["template"], "Web project")

    def test_unknown_template(self):
        other = Project.objects.create(name="Not one")
        response = self.api(
            "post", "projects/", self.ada, {"name": "Shop", "template": other.pk}
        )
        self.assertEqual(response.status_code, 404)

    def test_no_members(self):
        response = self.api(
            "post",
            f"projects/{self.template.pk}/members/",
            self.ada,
            {"person_id": self.bob.pk},
        )
        self.assertEqual(response.status_code, 400)
        response = self.api(
            "patch", f"projects/{self.template.pk}/", self.ada, {"is_all_access": False}
        )
        self.assertEqual(response.status_code, 400)

    def test_search(self):
        """Never finds templates (decided 2026-11-22)"""
        data = self.api("get", "search/", self.ada, {"q": "Kick-off"}).json()
        self.assertEqual(data["results"], [])
        data = self.api(
            "get",
            "search/",
            self.ada,
            {"q": "Kick-off", "project_id": self.template.pk},
        ).json()
        self.assertEqual(data["results"], [])

    def test_list_from_template(self):
        """The copy endpoint, the other way round"""
        website = Project.objects.create(name="Website")
        response = self.api(
            "post",
            f"lists/{self.list.pk}/copy/",
            self.ada,
            {"project_id": website.pk, "title": "Onboarding Dan"},
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(
            Item.objects.filter(
                project=website, kind=Kind.LIST, title="Onboarding Dan"
            ).exists()
        )
