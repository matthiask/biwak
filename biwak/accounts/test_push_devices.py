"""Devices getting push notifications (specs/web-push.md): the settings'
section, subscribing and removing, the service worker, the API"""

import json

from django.core.exceptions import ValidationError
from django.test import Client, TestCase, override_settings

from biwak.accounts import operations
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
IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15"
    " (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
)
CHROME = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    " (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)


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

    def test_several_devices_of_one_person(self):
        """Phone, laptop and desktop: each its own device, listed so they
        can be told apart; another person on one of the browsers takes only
        that one"""
        self.client.force_login(self.ada)
        for name, agent in [
            ("phone", IPHONE),
            ("laptop", FIREFOX),
            ("desktop", CHROME),
        ]:
            self.client.post(
                "/accounts/push/",
                json.dumps(
                    SUBSCRIPTION | {"endpoint": f"https://push.example.org/{name}"}
                ),
                content_type="application/json",
                headers={"user-agent": agent},
            )
        self.assertEqual(self.ada.push_subscriptions.count(), 3)
        response = self.client.get("/accounts/settings/")
        for name in ["Safari on iPhone", "Firefox on Linux", "Chrome on Windows"]:
            self.assertContains(response, name)
        self.assertContains(response, "Last used")
        self.assertContains(response, "data-push-endpoint=", count=3)
        # Subscribing on the phone again keeps the others
        self.post(SUBSCRIPTION | {"endpoint": "https://push.example.org/phone"})
        self.assertEqual(self.ada.push_subscriptions.count(), 3)
        # Cleo on Ada's laptop: the laptop is Cleo's, Ada keeps the others
        self.client.force_login(self.cleo)
        self.post(SUBSCRIPTION | {"endpoint": "https://push.example.org/laptop"})
        self.assertEqual(
            sorted(self.ada.push_subscriptions.values_list("endpoint", flat=True)),
            ["https://push.example.org/desktop", "https://push.example.org/phone"],
        )
        self.assertEqual(self.cleo.push_subscriptions.count(), 1)

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

    def test_renaming(self):
        """Two laptops with the same browser and system: a name tells them
        apart; empty is the browser and system again"""
        device = subscribe_device(self.cleo)
        device.user_agent = FIREFOX
        device.save()
        self.assertEqual(device.label, "Firefox on Linux")
        renamed = operations.rename_device(
            self.cleo, pk=device.pk, name="  Work \n laptop "
        )
        self.assertEqual(renamed.name, "Work laptop")
        self.assertEqual(renamed.label, "Work laptop")
        with self.assertRaises(ValidationError):
            operations.rename_device(self.cleo, pk=device.pk, name="x" * 101)
        renamed = operations.rename_device(self.cleo, pk=device.pk, name=" ")
        self.assertEqual((renamed.name, renamed.label), ("", "Firefox on Linux"))
        # Only one's own
        self.assertIsNone(operations.rename_device(self.ada, pk=device.pk, name="Mine"))
        device.refresh_from_db()
        self.assertEqual(device.name, "")

    def test_renaming_in_the_list(self):
        device = subscribe_device(self.cleo)
        device.user_agent = FIREFOX
        device.save()
        url = f"/accounts/push/{device.pk}/rename/"
        self.client.force_login(self.cleo)
        response = self.client.get("/accounts/settings/")
        self.assertContains(response, f'href="{url}"')
        self.assertContains(response, "Rename…")
        # The form, as a modal and as a page
        response = self.client.get(url, headers={"HX-Modal": "true"})
        self.assertContains(response, "Rename the device")
        self.assertContains(response, 'placeholder="Firefox on Linux"')
        self.assertContains(response, 'maxlength="100"')
        self.assertContains(self.client.get(url), "Rename the device")
        response = self.client.post(url, {"name": "x" * 101})
        self.assertContains(response, "Ensure this value has at most 100 characters")
        response = self.client.post(url, {"name": "Work  laptop"})
        self.assertRedirects(response, "/accounts/settings/#devices")
        device.refresh_from_db()
        self.assertEqual(device.name, "Work laptop")
        response = self.client.get("/accounts/settings/")
        self.assertContains(response, "Work laptop")
        self.assertNotContains(response, "Firefox on Linux")
        # Somebody else's device isn't there for them
        self.client.force_login(self.ada)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, {"name": "Mine"}).status_code, 404)
        device.refresh_from_db()
        self.assertEqual(device.name, "Work laptop")

    def test_in_the_audit_log_without_the_keys(self):
        LoggedAction.objects.all().delete()
        self.client.force_login(self.ada)
        self.post(SUBSCRIPTION)
        change = LoggedAction.objects.get(table_name="accounts_pushsubscription")
        self.assertEqual(change.action, "I")
        self.assertEqual(change.row_data["endpoint"], SUBSCRIPTION["endpoint"])
        self.assertNotIn("auth", change.row_data)
        self.assertNotIn("p256dh", change.row_data)


@override_settings(**KEYS)
class SignOutTest(TestCase):
    """Signing out explicitly ends pushes on that browser, and says so"""

    def setUp(self):
        self.ada = person("Ada")
        self.phone = subscribe_device(self.ada)
        self.client.force_login(self.ada)

    def subscribe(self):
        response = self.client.post(
            "/accounts/push/", json.dumps(SUBSCRIPTION), content_type="application/json"
        )
        self.assertIn("biwak_push_device", response.cookies)
        return PushSubscription.objects.get(endpoint=SUBSCRIPTION["endpoint"])

    def test_the_browsers_device_by_its_cookie(self):
        self.subscribe()
        response = self.client.post("/accounts/logout/", follow=True)
        self.assertContains(response, "Push notifications on this device are off.")
        # Only this browser's: the phone keeps getting them
        self.assertEqual(list(self.ada.push_subscriptions.all()), [self.phone])

    def test_by_the_endpoint_the_page_sends(self):
        response = self.client.post(
            "/accounts/logout/", {"push_endpoint": self.phone.endpoint}, follow=True
        )
        self.assertContains(response, "Push notifications on this device are off.")
        self.assertFalse(self.ada.push_subscriptions.exists())

    def test_not_somebody_elses(self):
        theirs = subscribe_device(person("Bob"))
        response = self.client.post(
            "/accounts/logout/", {"push_endpoint": theirs.endpoint}, follow=True
        )
        self.assertNotContains(response, "Push notifications on this device")
        self.assertTrue(PushSubscription.objects.filter(pk=theirs.pk).exists())

    def test_nothing_to_end(self):
        response = self.client.post("/accounts/logout/", follow=True)
        self.assertNotContains(response, "Push notifications on this device")
        self.assertEqual(list(self.ada.push_subscriptions.all()), [self.phone])

    def test_not_when_the_session_ends_otherwise(self):
        """An expired session (here: deleted) isn't signing out"""
        device = self.subscribe()
        self.client.session.delete()
        self.client.get("/accounts/settings/")
        self.assertTrue(PushSubscription.objects.filter(pk=device.pk).exists())

    def test_removing_it_in_the_settings_forgets_the_cookie(self):
        device = self.subscribe()
        response = self.client.delete(
            "/accounts/push/", json.dumps(SUBSCRIPTION), content_type="application/json"
        )
        self.assertEqual(response.cookies["biwak_push_device"].value, "")
        self.assertFalse(PushSubscription.objects.filter(pk=device.pk).exists())

    def test_the_pages_know_where_signing_out_is(self):
        response = self.client.get("/accounts/settings/")
        self.assertContains(response, 'data-sign-out="/accounts/logout/"')


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
        self.assertEqual(device["name"], "Safari on iPhone")
        operations.rename_device(self.cleo, pk=mine.pk, name="Old phone")
        response = self.client.get("/api/v1/me/push-subscriptions/", headers=headers)
        (device,) = response.json()
        self.assertEqual(device["name"], "Old phone")
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
