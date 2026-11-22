"""Public links (specs/public-links.md): the API"""

import datetime as dt
import json

from django.conf import settings
from django.test import TestCase
from django.utils import timezone

from biwak.items import operations as ops
from biwak.public_links.models import PublicLink
from biwak.public_links.test_operations import Fixture


class APITest(Fixture, TestCase):
    def test_create_show_stop(self):
        url = f"/api/v1/items/{self.todo.pk}/public-link/"
        self.assertEqual(self.client.get(url).status_code, 404)
        response = self.client.post(
            url, json.dumps({"days": 3}), content_type="application/json"
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        link = PublicLink.objects.get()
        self.assertEqual(data["url"], f"{settings.BASE_URL}/p/{link.token}/")
        self.assertEqual(data["item"]["id"], self.todo.pk)
        self.assertEqual(data["created_by"]["name"], "Ada Example")
        self.assertEqual(self.client.get(url).json()["url"], data["url"])
        listed = self.client.get("/api/v1/public-links/").json()
        self.assertEqual([entry["url"] for entry in listed], [data["url"]])
        response = self.client.delete(url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(PublicLink.objects.exists())
        self.assertEqual(self.client.delete(url).status_code, 404)

    def test_only_the_days_offered(self):
        url = f"/api/v1/items/{self.todo.pk}/public-link/"
        for days in (2, 31):
            response = self.client.post(
                url, json.dumps({"days": days}), content_type="application/json"
            )
            self.assertEqual(response.status_code, 422)
        response = self.client.post(url, "{}", content_type="application/json")
        self.assertEqual(response.status_code, 201)
        self.assertGreater(
            PublicLink.objects.get().expires_at,
            timezone.now() + dt.timedelta(days=6),
        )

    def test_containers(self):
        url = f"/api/v1/items/{self.todolist.pk}/public-link/"
        response = self.client.post(url, "{}", content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_clients(self):
        visible = ops.create_message(
            project=self.project, title="Hello", creator=self.ada, visible=True
        )
        self.share(visible)
        self.client.force_login(self.cleo)
        for item, status in [(visible, 403), (self.todo, 404)]:
            url = f"/api/v1/items/{item.pk}/public-link/"
            with self.subTest(item.title):
                self.assertEqual(self.client.get(url).status_code, status)
                response = self.client.post(url, "{}", content_type="application/json")
                self.assertEqual(response.status_code, status)
                self.assertEqual(self.client.delete(url).status_code, status)
        self.assertEqual(self.client.get("/api/v1/public-links/").status_code, 403)
        self.assertEqual(PublicLink.objects.count(), 1)
