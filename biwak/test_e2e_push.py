"""Subscribing a device to push notifications in the settings
(specs/web-push.md, frontend/push.js), Chromium's push service stubbed:
the browser's PushManager answers with a made-up subscription"""

import json

from django.test import override_settings

from biwak.accounts.models import PushSubscription
from biwak.activity.test_push import KEYS
from biwak.test_e2e import E2ETestCase, expect


ENDPOINT = "https://push.example.org/send/e2e"

# The subscription lives in sessionStorage, so that it survives the reload
STUB = """
(() => {
  const json = {
    endpoint: "%s",
    expirationTime: null,
    keys: { p256dh: "BKeyOfTheDevice", auth: "secret" },
  }
  const fake = {
    endpoint: json.endpoint,
    toJSON: () => json,
    unsubscribe: async () => {
      sessionStorage.removeItem("subscribed")
      sessionStorage.setItem("unsubscribed", "1")
      return true
    },
  }
  PushManager.prototype.subscribe = async function (options) {
    sessionStorage.setItem("key-bytes", options.applicationServerKey.length)
    sessionStorage.setItem("subscribed", "1")
    return fake
  }
  PushManager.prototype.getSubscription = async function () {
    return sessionStorage.getItem("subscribed") ? fake : null
  }
  // Headless Chromium denies notifications whatever the context grants
  let permission = "%s"
  Object.defineProperty(Notification, "permission", { get: () => permission })
  Notification.requestPermission = async () => {
    permission = "%s"
    return permission
  }
})()
"""


@override_settings(**KEYS)
class SubscribingTest(E2ETestCase):
    def page_with(self, user, *, now="default", asked="granted"):
        """The permission ``now``, and after asking"""
        page = self.login(user)
        page.context.add_init_script(STUB % (ENDPOINT, now, asked))
        return page

    def test_subscribing_and_removing(self):
        page = self.page_with(self.cleo)
        page.goto(f"{self.live_server_url}/accounts/settings/")
        button = page.get_by_role("button", name="Notify me on this device")
        button.click()
        this = page.locator("[data-push-this]")
        expect(this).to_be_visible()
        device = PushSubscription.objects.get()
        self.assertEqual(
            (device.user, device.endpoint, device.auth),
            (self.cleo, ENDPOINT, "secret"),
        )
        self.assertIn("HeadlessChrome", device.user_agent)
        expect(button).to_be_hidden()
        # The service worker is there, for the pushes
        self.assertTrue(
            page.evaluate(
                "navigator.serviceWorker.getRegistration('/').then((r) => !!r)"
            )
        )
        # The key as its 65 bytes
        self.assertEqual(page.evaluate("sessionStorage.getItem('key-bytes')"), "65")
        page.locator("#push-devices").get_by_role("button", name="Remove").click()
        expect(button).to_be_visible()
        expect(page.locator("#push-devices")).to_have_count(0)
        self.assertFalse(PushSubscription.objects.exists())
        self.assertEqual(page.evaluate("sessionStorage.getItem('unsubscribed')"), "1")
        self.assertEqual(self.errors, [])

    def test_signing_out_ends_it_on_this_device(self):
        """The page unsubscribes the browser and names the device, also
        when its cookie is gone; the person's other devices stay"""
        phone = PushSubscription.objects.create(
            user=self.cleo,
            endpoint="https://push.example.org/send/phone",
            p256dh="BKey",
            auth="secret",
        )
        page = self.page_with(self.cleo)
        page.goto(f"{self.live_server_url}/accounts/settings/")
        page.get_by_role("button", name="Notify me on this device").click()
        expect(page.locator("[data-push-this]:visible")).to_have_count(1)
        page.context.clear_cookies(name="biwak_push_device")
        # The menu's sign-out
        menu = page.locator("details", has=page.locator("button.dropdown-item"))
        menu.locator("summary").click()
        menu.get_by_role("button", name="Sign out").click()
        expect(
            page.get_by_text("Push notifications on this device are off.")
        ).to_be_visible()
        self.assertEqual(list(PushSubscription.objects.all()), [phone])
        self.assertEqual(page.evaluate("sessionStorage.getItem('unsubscribed')"), "1")
        # The sign-in page's allauth scripts aren't served without collectstatic
        allauth = ("/static/mfa/", "/static/account/")
        self.assertEqual(
            [e for e in self.errors if not any(path in e for path in allauth)], []
        )

    def test_another_device_in_the_list(self):
        PushSubscription.objects.create(
            user=self.ada,
            endpoint="https://push.example.org/send/laptop",
            p256dh="BKey",
            auth="secret",
            user_agent="Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Firefox/140.0",
        )
        page = self.page_with(self.ada)
        page.goto(f"{self.live_server_url}/accounts/settings/")
        devices = page.locator("#push-devices")
        expect(devices).to_contain_text("Firefox on Linux")
        expect(devices.locator("[data-push-this]")).to_be_hidden()
        expect(
            page.get_by_role("button", name="Notify me on this device")
        ).to_be_visible()
        self.assertEqual(self.errors, [])

    def test_blocked(self):
        page = self.page_with(self.ada, now="denied")
        page.goto(f"{self.live_server_url}/accounts/settings/")
        expect(
            page.get_by_role("button", name="Notify me on this device")
        ).to_be_hidden()
        expect(
            page.get_by_text(
                "Notifications are blocked for Biwak in this browser's settings."
            )
        ).to_be_visible()
        self.assertEqual(self.errors, [])

    def test_blocked_when_asked(self):
        page = self.page_with(self.ada, asked="denied")
        page.goto(f"{self.live_server_url}/accounts/settings/")
        page.get_by_role("button", name="Notify me on this device").click()
        expect(
            page.get_by_text(
                "Notifications are blocked for Biwak in this browser's settings."
            )
        ).to_be_visible()
        self.assertFalse(PushSubscription.objects.exists())
        self.assertEqual(self.errors, [])

    def test_an_iphone_not_on_the_home_screen(self):
        page = self.login(
            self.ada,
            user_agent=(
                "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)"
                " AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0"
                " Mobile/15E148 Safari/604.1"
            ),
        )
        # Safari outside the home screen has no PushManager
        page.context.add_init_script("delete window.PushManager")
        page.goto(f"{self.live_server_url}/accounts/settings/")
        expect(
            page.get_by_text(
                "Add Biwak to your home screen to get notifications on this iPhone."
            )
        ).to_be_visible()
        expect(
            page.get_by_role("button", name="Notify me on this device")
        ).to_be_hidden()
        self.assertEqual(self.errors, [])


@override_settings(**KEYS)
class ServiceWorkerTest(E2ETestCase):
    """frontend/sw.js in Chromium: a push delivered through the DevTools
    protocol, ``showNotification`` recorded in the worker (headless
    Chromium shows nothing). A tap can't be tested: only a real
    notification's click lets the worker focus or open windows."""

    def worker(self, page):
        with page.context.expect_event("serviceworker") as event:
            page.evaluate("navigator.serviceWorker.register('/sw.js')")
        worker = event.value
        page.evaluate("navigator.serviceWorker.ready")
        worker.evaluate(
            """() => {
              self.shown = []
              self.registration.showNotification = async (title, options) => {
                self.shown.push({ title, ...options })
              }
            }"""
        )
        return worker

    def push(self, page, data):
        """Delivers ``data`` to the service worker as a push"""
        scope = page.evaluate(
            "navigator.serviceWorker.getRegistration('/').then((r) => r.scope)"
        )
        session = page.context.new_cdp_session(page)
        registrations = []
        session.on(
            "ServiceWorker.workerRegistrationUpdated",
            lambda event: registrations.extend(
                r for r in event["registrations"] if r["scopeURL"] == scope
            ),
        )
        session.send("ServiceWorker.enable")
        # The events come while Playwright waits on the page
        for _attempt in range(50):
            if registrations:
                break
            page.wait_for_timeout(20)
        session.send(
            "ServiceWorker.deliverPushMessage",
            {
                "origin": self.live_server_url,
                "registrationId": registrations[0]["registrationId"],
                "data": json.dumps(data),
            },
        )

    def test_a_push_is_shown(self):
        page = self.page
        page.goto(f"{self.live_server_url}/accounts/settings/")
        worker = self.worker(page)
        url = f"{self.live_server_url}/todos/1/"
        self.push(
            page,
            {
                "title": "Order the tent",
                "body": "Ada Example assigned you.\nWebsite",
                "tag": "biwak-item-1",
                "url": url,
                "icon": "/static/biwak/icon-192.png",
            },
        )
        worker.evaluate(
            """() => new Promise((resolve) => {
              const check = () => self.shown.length ? resolve() : setTimeout(check, 10)
              check()
            })"""
        )
        self.assertEqual(
            worker.evaluate("self.shown"),
            [
                {
                    "title": "Order the tent",
                    "body": "Ada Example assigned you.\nWebsite",
                    "tag": "biwak-item-1",
                    "icon": "/static/biwak/icon-192.png",
                    "actions": [],
                    "data": {"url": url},
                }
            ],
        )
        self.assertEqual(self.errors, [])

    def test_turning_off_on_this_device(self):
        """ "Turn off on this device" ends the browser's subscription without
        signing in; a click on a real notification can't be made, so the
        worker gets the event as the browser would send it"""
        page = self.page
        page.goto(f"{self.live_server_url}/accounts/settings/")
        worker = self.worker(page)
        self.assertTrue(
            worker.evaluate(
                """async () => {
                  self.unsubscribed = false
                  self.registration.pushManager.getSubscription = async () => ({
                    unsubscribe: async () => { self.unsubscribed = true },
                  })
                  const event = new Event("notificationclick")
                  let done
                  event.action = "off"
                  event.notification = { close() {}, data: { url: "/" } }
                  event.waitUntil = (promise) => { done = promise }
                  self.dispatchEvent(event)
                  await done
                  return self.unsubscribed
                }"""
            )
        )
        self.assertEqual(self.errors, [])
