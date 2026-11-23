"""``biwak devices``: the devices getting push notifications and a test
push to one of them (specs/web-push.md)"""

import json
from unittest.mock import Mock, patch

from django.test import override_settings
from pywebpush import WebPushException

from biwak import test_cli
from biwak.accounts.models import PushSubscription
from biwak.activity.test_push import KEYS, subscribe_device
from biwak.test_utils import person


@override_settings(**KEYS)
class DevicesCLITest(test_cli.CLITest):
    def setUp(self):
        super().setUp()
        self.webpush = patch("pywebpush.webpush").start()
        self.addCleanup(patch.stopall)

    def test_listing(self):
        self.assertIn(
            "No devices get push notifications.", self.biwak("devices").output
        )
        phone = subscribe_device(self.ada)
        subscribe_device(person("Bob"))
        output = self.biwak("devices").output
        self.assertIn(str(phone.pk), output)
        self.assertIn("Safari on iPhone", output)
        self.assertIn("never", output)
        (device,) = json.loads(self.biwak("devices", "--json").output)
        self.assertEqual(device["id"], phone.pk)

    def test_sending_a_test(self):
        phone = subscribe_device(self.ada)
        result = self.biwak("devices", "test", phone.pk)
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Sent. It should show up in a few seconds.", result.output)
        self.assertEqual(self.webpush.call_count, 1)
        data = json.loads(self.biwak("devices", "test", phone.pk, "--json").output)
        self.assertEqual(data["sent"], True)
        # Read-only tokens don't send
        result = self.biwak("devices", "test", phone.pk, access="read")
        self.assertEqual(result.exit_code, 1)
        self.assertEqual(self.webpush.call_count, 2)

    def test_failing(self):
        phone = subscribe_device(self.ada)
        theirs = subscribe_device(person("Bob"))
        result = self.biwak("devices", "test", theirs.pk)
        self.assertEqual(result.exit_code, 1)
        self.assertIn("404", result.output)
        self.webpush.side_effect = WebPushException(
            "gone", response=Mock(status_code=410)
        )
        result = self.biwak("devices", "test", phone.pk)
        self.assertEqual(result.exit_code, 1)
        self.assertIn("had expired and was removed", result.output)
        self.assertEqual(list(PushSubscription.objects.all()), [theirs])
