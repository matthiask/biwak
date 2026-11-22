"""Drawn marks (specs/people.md, "Stage 2: drawn marks"): the drawings
and their classes, giving marks, choosing one in the settings and the
API, the avatar's markup"""

import json
import re
from pathlib import Path

from django.conf import settings
from django.template import Context, Template
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse

from biwak.accounts import operations
from biwak.accounts.marks import MARKS, fewest_used, mark_for
from biwak.accounts.models import APIToken, User
from biwak.accounts.test_images import picture
from biwak.test_utils import organization, person


BASE = Path(settings.BASE_DIR)


class DrawingsTest(SimpleTestCase):
    def test_every_drawing_has_its_class_and_every_class_its_drawing(self):
        drawings = {
            path.stem for path in (BASE / "biwak/static/biwak/marks").glob("*.svg")
        }
        css = (BASE / "frontend/styles/marks.css").read_text()
        classes = dict(
            re.findall(
                r'\.wb-mark-([\w-]+) \{\s*--wb-mark-image: url\("([^"]+)"\)', css
            )
        )
        self.assertEqual(len(drawings), 35)
        self.assertEqual(set(classes), drawings)
        for mark, url in classes.items():
            self.assertEqual(url, f"../../biwak/static/biwak/marks/{mark}.svg")
        # And every one can be chosen
        self.assertEqual(set(MARKS), drawings)

    def test_the_drawings_follow_the_rules(self):
        """One color (currentColor, a second tone by opacity) on 64 by 64"""
        for path in (BASE / "biwak/static/biwak/marks").glob("*.svg"):
            with self.subTest(path.name):
                svg = path.read_text()
                self.assertIn('viewBox="0 0 64 64"', svg)
                colors = set(re.findall(r'(?:fill|stroke)="([^"]+)"', svg))
                self.assertLessEqual(colors, {"currentColor", "none"})


class GivingTest(TestCase):
    def test_the_first_in_the_lists_order_for_the_first_person(self):
        self.assertEqual(person("Ada").mark, next(iter(MARKS)))

    def test_the_one_fewest_people_of_the_organization_have(self):
        people = [person(f"P{i}") for i in range(len(MARKS))]
        # A team of 35 has no repeats
        self.assertEqual({p.mark for p in people}, set(MARKS))
        # The 36th gets the first again, then the second
        self.assertEqual(person("Q1").mark, "tent")
        self.assertEqual(person("Q2").mark, "mountain")

    def test_ties_go_to_the_first_in_the_list(self):
        self.assertEqual(fewest_used({}), "tent")
        self.assertEqual(fewest_used({"tent": 1}), "mountain")
        self.assertEqual(
            fewest_used(dict.fromkeys(MARKS, 2) | {"owl": 1, "cat": 1}), "owl"
        )

    def test_per_organization(self):
        ada = person("Ada")
        cleo = person("Cleo", client=True)
        dora = person("Dora", client=True, organization="Other Example Ltd")
        self.assertEqual(ada.mark, "tent")
        self.assertEqual(cleo.mark, "tent")
        self.assertEqual(dora.mark, "tent")
        self.assertEqual(person("Ben").mark, "mountain")
        # Without an organization: among those without one
        pia = person("Pia", organization=None)
        self.assertEqual(pia.mark, "tent")
        self.assertEqual(mark_for(None), "mountain")

    def test_people_who_left_dont_count_those_waiting_to_be_activated_do(self):
        import datetime as dt

        ada = person("Ada")
        person("Ben", is_active=False)  # waiting to be activated
        self.assertEqual(mark_for(ada.organization_id), "horn")
        ada.is_active = False
        ada.left_at = dt.date(2026, 1, 1)
        ada.save()
        self.assertEqual(mark_for(ada.organization_id), "tent")
        ada.refresh_from_db()
        self.assertEqual(ada.mark, "tent")  # kept

    def test_a_given_mark_is_kept(self):
        own = organization("Example Team", is_own=True)
        user = User.objects.create_user("eve@example.org", organization=own, mark="owl")
        self.assertEqual(user.mark, "owl")


class AvatarTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.ben = person("Ben")

    def render(self, who):
        request = RequestFactory().get("/")
        request.user = self.ada
        return Template("{% load biwak %}{% avatar who 'md' %}").render(
            Context({"request": request, "who": who})
        )

    def test_without_a_photo_the_drawn_mark_no_initials(self):
        html = self.render(self.ben)
        self.assertEqual(
            html,
            '<span class="wb-avatar wb-avatar-md wb-mark wb-mark-mountain"'
            f' data-avatar-color="{self.ben.avatar_color}" title="Ben Example"'
            ' role="img" aria-label="Ben Example"></span>',
        )

    def test_with_a_photo_the_photo(self):
        operations.set_image(self.ben, picture(), actor=self.ben)
        html = self.render(self.ben)
        self.assertIn("<img", html)
        self.assertNotIn("wb-mark", html)

    def test_the_scripts_data_has_the_mark(self):
        data = self.ben.avatar_data
        self.assertEqual(data["mark"], "mountain")
        self.assertNotIn("initials", data)


class OperationTest(TestCase):
    def test_choosing_a_mark(self):
        ada = person("Ada")
        operations.set_preferences(ada, mark="ibex")
        ada.refresh_from_db()
        self.assertEqual(ada.mark, "ibex")

    def test_unknown_marks_are_refused(self):
        ada = person("Ada")
        for mark in ["unicorn", "", "../tent"]:
            with self.subTest(mark), self.assertRaises(ValueError):
                operations.set_preferences(ada, mark=mark)


class SettingsTest(TestCase):
    def test_the_grid_with_ones_own_selected_staff_and_client(self):
        for user in [person("Ada"), person("Cleo", client=True)]:
            with self.subTest(user=user):
                self.client.force_login(user)
                response = self.client.get(reverse("settings"))
                html = response.content.decode()
                self.assertContains(response, "Drawn")
                self.assertContains(response, "Photo")
                buttons = re.findall(
                    r'<button\s+type="submit"\s+name="mark".*?>', html, re.DOTALL
                )
                self.assertEqual(len(buttons), len(MARKS))
                pressed = [b for b in buttons if 'aria-pressed="true"' in b]
                self.assertEqual(len(pressed), 1)
                self.assertIn(f'value="{user.mark}"', pressed[0])
                # On the person's own color
                self.assertRegex(
                    html, rf'wb-mark-ibex"\s+data-avatar-color="{user.avatar_color}"'
                )

    def test_a_click_saves_it(self):
        cleo = person("Cleo", client=True)
        self.client.force_login(cleo)
        response = self.client.post(reverse("settings_mark"), {"mark": "owl"})
        self.assertRedirects(
            response,
            reverse("settings") + "#profile-image",
            fetch_redirect_response=False,
        )
        cleo.refresh_from_db()
        self.assertEqual(cleo.mark, "owl")
        response = self.client.get(reverse("settings"))
        self.assertContains(response, "Your mark has been saved.")
        self.assertRegex(
            response.content.decode(), r'value="owl"[^>]*aria-pressed="true"'
        )

    def test_an_unknown_mark_is_refused(self):
        ada = person("Ada")
        self.client.force_login(ada)
        response = self.client.post(reverse("settings_mark"), {"mark": "unicorn"})
        self.assertEqual(response.status_code, 400)
        ada.refresh_from_db()
        self.assertEqual(ada.mark, "tent")

    def test_only_posts(self):
        self.client.force_login(person("Ada"))
        self.assertEqual(self.client.get(reverse("settings_mark")).status_code, 405)


class APITest(TestCase):
    def setUp(self):
        self.cleo = person("Cleo", client=True)
        _token, secret = APIToken.create_for(user=self.cleo, title="T", access="write")
        self.auth = {"HTTP_AUTHORIZATION": f"Bearer {secret}"}

    def test_the_mark_is_on_people_and_can_be_changed(self):
        response = self.client.get("/api/v1/me/", **self.auth)
        self.assertEqual(response.json()["mark"], "tent")
        response = self.client.put(
            "/api/v1/me/",
            json.dumps({"mark": "fox"}),
            content_type="application/json",
            **self.auth,
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["mark"], "fox")
        self.cleo.refresh_from_db()
        self.assertEqual(self.cleo.mark, "fox")

    def test_unknown_marks_are_refused(self):
        response = self.client.put(
            "/api/v1/me/",
            json.dumps({"mark": "unicorn"}),
            content_type="application/json",
            **self.auth,
        )
        self.assertEqual(response.status_code, 422)
        self.cleo.refresh_from_db()
        self.assertEqual(self.cleo.mark, "tent")
