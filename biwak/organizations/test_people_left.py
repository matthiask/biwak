"""People who left (specs/activation.md, "People who left"): ``left_at``
set by deactivating and the importer, cleared by activating; the People
page's filter, activating and the API. The importer's side in
``biwak/importer/test_importer.py``, the CLI in ``biwak/test_cli_people.py``."""

import datetime as dt

from django.test import Client, TestCase
from django.utils import timezone
from django.utils.formats import date_format

from biwak.accounts.models import User
from biwak.organizations import activation
from biwak.test_utils import external, person, project


LEFT_ON = dt.date(2025, 3, 3)


class Base(TestCase):
    def setUp(self):
        self.root = person("Root", is_admin=True)
        self.ada = person("Ada")
        self.pia = external("Pia")
        self.chris = person("Chris", client=True)
        # Left: a client and a staff member
        self.lena = person("Lena", client=True, is_active=False, left_at=LEFT_ON)
        self.otto = person("Otto", is_active=False, left_at=LEFT_ON)
        # Imported, waiting to be activated
        self.wade = person("Wade", client=True, is_active=False)
        self.site = project(
            "Site",
            members=[self.ada, self.pia, self.chris, self.lena, self.otto, self.wade],
        )

    def left_at(self, user):
        user.refresh_from_db()
        return user.left_at


class OperationsTest(Base):
    def test_deactivating_sets_the_day(self):
        activation.deactivate([self.chris], actor=self.ada)
        self.assertEqual(self.left_at(self.chris), timezone.localdate())
        self.assertFalse(self.chris.is_active)

    def test_deactivating_somebody_inactive_changes_nothing(self):
        activation.deactivate([self.wade, self.lena], actor=self.ada)
        self.assertIsNone(self.left_at(self.wade))
        self.assertEqual(self.left_at(self.lena), LEFT_ON)

    def test_activating_clears_it(self):
        activation.activate([self.lena], actor=self.ada)
        self.lena.refresh_from_db()
        self.assertTrue(self.lena.is_active)
        self.assertIsNone(self.lena.left_at)

    def test_mark_left_only_inactive_people_who_havent_left(self):
        today = timezone.localdate()
        marked = activation.mark_left([self.wade, self.lena, self.chris], on=today)
        self.assertEqual(marked, [self.wade])
        self.assertEqual(self.left_at(self.wade), today)
        self.assertEqual(self.left_at(self.lena), LEFT_ON)
        self.assertIsNone(self.left_at(self.chris))


class PageTest(Base):
    def get(self, viewer, query=""):
        self.client.force_login(viewer)
        return self.client.get(f"/people/{query}")

    def test_everybody_who_hasnt_left_by_default(self):
        for viewer in [self.root, self.ada, self.pia, self.chris]:
            with self.subTest(viewer=viewer):
                response = self.get(viewer)
                self.assertContains(response, "Wade Example")
                self.assertContains(response, "Chris Example")
                self.assertNotContains(response, "Lena Example")
                self.assertNotContains(response, "Otto Example")

    def test_the_filter_lists_who_left_with_the_day(self):
        for viewer in [self.root, self.ada]:
            with self.subTest(viewer=viewer):
                self.assertContains(self.get(viewer), "?left=1")
                response = self.get(viewer, "?left=1")
                self.assertContains(response, "People who left")
                self.assertContains(response, "Lena Example")
                self.assertContains(response, "Otto Example")
                self.assertContains(response, f"left on {date_format(LEFT_ON)}")
                self.assertNotContains(response, "Wade Example")
                self.assertNotContains(response, "Chris Example")
                # Their pages stay reachable; no Activate… in the list
                self.assertContains(response, f"/people/{self.lena.pk}/")
                self.assertNotContains(response, f"/people/{self.lena.pk}/activate/")

    def test_nobody_has_left(self):
        User.objects.filter(left_at__isnull=False).update(left_at=None)
        self.assertContains(self.get(self.ada, "?left=1"), "Nobody has left.")

    def test_the_filter_is_for_staff(self):
        for viewer in [self.pia, self.chris]:
            with self.subTest(viewer=viewer):
                response = self.get(viewer, "?left=1")
                self.assertNotContains(response, "?left=1")
                self.assertNotContains(response, "Lena Example")
                self.assertContains(response, "Wade Example")

    def test_inactive_offers_only_people_waiting(self):
        response = self.get(self.ada, "?inactive=1")
        self.assertContains(response, "Wade Example")
        self.assertContains(response, f"/people/{self.wade.pk}/activate/")
        self.assertNotContains(response, "Lena Example")
        self.assertNotContains(response, f"/people/{self.lena.pk}/activate/")

    def test_their_own_page_still_activates_them(self):
        self.client.force_login(self.ada)
        page = self.client.get(f"/people/{self.lena.pk}/")
        self.assertContains(page, f"/people/{self.lena.pk}/activate/")
        self.client.post(f"/people/{self.lena.pk}/activate/")
        self.lena.refresh_from_db()
        self.assertTrue(self.lena.is_active)
        self.assertIsNone(self.lena.left_at)
        self.assertContains(self.get(self.ada), "Lena Example")

    def test_clients_and_externals_see_their_pages_as_before(self):
        for viewer in [self.pia, self.chris]:
            with self.subTest(viewer=viewer):
                self.client.force_login(viewer)
                response = self.client.get(f"/people/{self.lena.pk}/")
                self.assertContains(response, "Lena Example")


class APITest(Base):
    def setUp(self):
        super().setUp()
        self.api = Client()
        self.api.force_login(self.ada)

    def ids(self, **params):
        response = self.api.get("/api/v1/people/", params)
        self.assertEqual(response.status_code, 200)
        return {p["id"]: p for p in response.json()}

    def test_the_lists(self):
        everybody = self.ids()
        self.assertIn(self.chris.pk, everybody)
        self.assertIsNone(everybody[self.chris.pk]["left_at"])
        self.assertEqual(set(self.ids(inactive="true")), {self.wade.pk})
        left = self.ids(left="true")
        self.assertEqual(set(left), {self.lena.pk, self.otto.pk})
        self.assertEqual(left[self.lena.pk]["left_at"], "2025-03-03")

    def test_deactivating_answers_the_day(self):
        response = self.api.post(
            "/api/v1/people/deactivate/",
            {"ids": [self.chris.pk]},
            content_type="application/json",
        )
        self.assertEqual(
            response.json()[0]["left_at"], timezone.localdate().isoformat()
        )

    def test_for_own_staff_only(self):
        for viewer in [self.pia, self.chris]:
            with self.subTest(viewer=viewer):
                self.api.force_login(viewer)
                response = self.api.get("/api/v1/people/", {"left": "true"})
                self.assertEqual(response.status_code, 403)
