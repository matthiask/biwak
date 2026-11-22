"""Devices getting push notifications (specs/web-push.md): the settings'
section, subscribing and removing, the service worker, the API"""

import json

from django.test import Client, TestCase, override_settings

from biwak.accounts.models import APIToken, PushSubscription
from biwak.activity.test_push import KEYS, subscribe_device
from biwak.audit.models import LoggedAction
from biwak.test_utils import person


SUBSCRIPTION = {
    "endpoint": "https://push.example.org/send/abc",
    "expirationTime": None,
    "keys": {"p256dh": "BKeyOfTheDevice", "auth": "secret"},
}
FIREFOX = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"


@override_settings(**KEYS)
class DevicesTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.cleo = person("Cleo", client=True)

    def post(self, data, method="post", **kwargs):
        return getattr(self.client, method)(
            "/accounts/push/",
            json.dumps(data),
            content_type="application/json",
            headers={"user-agent": FIREFOX},
            **kwargs,
        )

    def test_the_settings_offer_it(self):
        for user in [self.ada, self.cleo]:
            with self.subTest(user=user):
                self.client.force_login(user)
                response = self.client.get("/accounts/settings/")
                self.assertContains(response, 'id="devices"')
                self.assertContains(
                    response, f'data-push="{KEYS["WEBPUSH_VAPID_PUBLIC_KEY"]}"'
                )
                self.assertContains(response, "Notify me on this device")
                self.assertContains(
                    response,
                    "Add Biwak to your home screen to get notifications on this iPhone.",
                )
                self.assertNotContains(response, 'id="push-devices"')

    def test_not_without_keys(self):
        self.client.force_login(self.ada)
        with override_settings(WEBPUSH_VAPID_PUBLIC_KEY=""):
            response = self.client.get("/accounts/settings/")
            self.assertNotContains(response, 'id="devices"')
            self.assertEqual(self.post(SUBSCRIPTION).status_code, 404)
        self.assertFalse(PushSubscription.objects.exists())

    def test_subscribing_and_the_list(self):
        self.client.force_login(self.cleo)
        self.assertEqual(self.post(SUBSCRIPTION).status_code, 204)
        device = PushSubscription.objects.get()
        self.assertEqual(
            (device.user, device.endpoint, device.p256dh, device.auth),
            (self.cleo, SUBSCRIPTION["endpoint"], "BKeyOfTheDevice", "secret"),
        )
        self.assertEqual(device.user_agent, FIREFOX)
        # Again: the same device
        self.assertEqual(self.post(SUBSCRIPTION).status_code, 204)
        self.assertEqual(PushSubscription.objects.count(), 1)
        response = self.client.get("/accounts/settings/")
        self.assertContains(response, 'id="push-devices"')
        self.assertContains(response, "Firefox on Linux")
        self.assertContains(response, f'data-push-endpoint="{device.endpoint}"')
        self.assertContains(response, f"/accounts/push/{device.pk}/remove/")

    def test_somebody_elses_device_becomes_mine(self):
        """A browser has one subscription: whoever subscribed last gets the
        pushes, and nothing of before"""
        old = subscribe_device(self.cleo)
        self.client.force_login(self.ada)
        self.post(SUBSCRIPTION | {"endpoint": old.endpoint})
        device = PushSubscription.objects.get()
        self.assertEqual(device.user, self.ada)
        self.assertGreater(device.created_at, old.created_at)

    def test_unsubscribing(self):
        mine = subscribe_device(self.ada)
        theirs = subscribe_device(self.cleo)
        self.client.force_login(self.ada)
        self.assertEqual(
            self.post(
                SUBSCRIPTION | {"endpoint": theirs.endpoint}, "delete"
            ).status_code,
            204,
        )
        self.assertEqual(
            self.post(SUBSCRIPTION | {"endpoint": mine.endpoint}, "delete").status_code,
            204,
        )
        self.assertEqual(list(PushSubscription.objects.all()), [theirs])

    def test_only_subscriptions(self):
        self.client.force_login(self.ada)
        for data in [
            {},
            [],
            "nope",
            {"endpoint": "https://push.example.org/x"},
            SUBSCRIPTION | {"endpoint": "http://push.example.org/x"},
            SUBSCRIPTION | {"endpoint": "javascript:alert(1)"},
            SUBSCRIPTION | {"keys": {"p256dh": "", "auth": "x"}},
            SUBSCRIPTION | {"keys": {"p256dh": 1, "auth": "x"}},
            SUBSCRIPTION | {"keys": {"p256dh": "x" * 201, "auth": "x"}},
        ]:
            with self.subTest(data=data):
                self.assertEqual(self.post(data).status_code, 400)
        response = self.client.post(
            "/accounts/push/", "{nope", content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get("/accounts/push/").status_code, 405)
        self.assertFalse(PushSubscription.objects.exists())

    def test_csrf_and_login(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.ada)
        response = client.post(
            "/accounts/push/", json.dumps(SUBSCRIPTION), content_type="application/json"
        )
        self.assertEqual(response.status_code, 403)
        response = Client().post(
            "/accounts/push/", json.dumps(SUBSCRIPTION), content_type="application/json"
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(PushSubscription.objects.exists())

    def test_removing_in_the_list(self):
        mine = subscribe_device(self.ada)
        theirs = subscribe_device(self.cleo)
        self.client.force_login(self.ada)
        response = self.client.post(f"/accounts/push/{theirs.pk}/remove/")
        self.assertEqual(response.status_code, 404)
        response = self.client.post(f"/accounts/push/{mine.pk}/remove/")
        self.assertRedirects(response, "/accounts/settings/#devices")
        self.assertEqual(list(PushSubscription.objects.all()), [theirs])

    def test_in_the_audit_log_without_the_keys(self):
        LoggedAction.objects.all().delete()
        self.client.force_login(self.ada)
        self.post(SUBSCRIPTION)
        change = LoggedAction.objects.get(table_name="accounts_pushsubscription")
        self.assertEqual(change.action, "I")
        self.assertEqual(change.row_data["endpoint"], SUBSCRIPTION["endpoint"])
        self.assertNotIn("auth", change.row_data)
        self.assertNotIn("p256dh", change.row_data)


class ServiceWorkerTest(TestCase):
    def test_served_at_the_root_without_login(self):
        response = Client().get("/sw.js")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/javascript; charset=utf-8")
        self.assertEqual(response["Cache-Control"], "no-cache")
        body = response.content.decode()
        self.assertIn('addEventListener("push"', body)
        self.assertIn('addEventListener("notificationclick"', body)
        # Nothing cached (specs/pwa.md)
        self.assertNotIn('addEventListener("fetch"', body)


class APITest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.cleo = person("Cleo", client=True)

    def headers(self, user, access="write"):
        _token, secret = APIToken.create_for(user=user, title="Test", access=access)
        return {"authorization": f"Bearer {secret}"}

    def test_own_devices(self):
        mine = subscribe_device(self.cleo)
        subscribe_device(self.ada)
        headers = self.headers(self.cleo)
        response = self.client.get("/api/v1/me/push-subscriptions/", headers=headers)
        self.assertEqual(response.status_code, 200)
        (device,) = response.json()
        self.assertEqual(device["id"], mine.pk)
        self.assertEqual(device["device"], "Safari on iPhone")
        self.assertIsNone(device["last_success_at"])
        self.assertNotIn("endpoint", device)
        self.assertNotIn("auth", device)

    def test_removing(self):
        mine = subscribe_device(self.cleo)
        theirs = subscribe_device(self.ada)
        headers = self.headers(self.cleo)
        url = "/api/v1/me/push-subscriptions/{}/"
        response = self.client.delete(url.format(theirs.pk), headers=headers)
        self.assertEqual(response.status_code, 404)
        read_only = self.headers(self.cleo, "read")
        response = self.client.delete(url.format(mine.pk), headers=read_only)
        self.assertEqual(response.status_code, 403)
        response = self.client.delete(url.format(mine.pk), headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], mine.pk)
        self.assertEqual(list(PushSubscription.objects.all()), [theirs])
