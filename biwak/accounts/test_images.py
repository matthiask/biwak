"""Profile images (specs/people.md): processing, the operations, serving with
the visibility rule of the People page, the mark"""

import io

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.template import Context, Template
from django.test import RequestFactory, TestCase
from django.test.client import BOUNDARY, MULTIPART_CONTENT, encode_multipart
from django.urls import reverse
from PIL import Image

from biwak.accounts import operations
from biwak.accounts.models import PALETTE, APIToken
from biwak.audit.models import LoggedAction
from biwak.test_utils import partner, person, project


def picture(width=400, height=200, format="PNG", color=(200, 30, 30)):
    out = io.BytesIO()
    Image.new("RGB", (width, height), color).save(out, format)
    return out.getvalue()


class ProcessingTest(TestCase):
    def test_a_square_of_256_pixels_as_webp(self):
        data = operations.image_data(picture(400, 200))
        image = Image.open(io.BytesIO(data))
        self.assertEqual((image.format, image.size), ("WEBP", (256, 256)))

    def test_it_is_cut_in_the_middle(self):
        out = io.BytesIO()
        image = Image.new("RGB", (300, 100), (255, 0, 0))
        image.paste((0, 0, 255), (100, 0, 200, 100))  # the middle third
        image.save(out, "PNG")
        result = Image.open(io.BytesIO(operations.image_data(out.getvalue())))
        r, _g, b = result.convert("RGB").getpixel((128, 128))
        self.assertGreater(b, 200)
        self.assertLess(r, 60)

    def test_jpeg_and_webp_are_accepted(self):
        for format in ["JPEG", "WEBP"]:
            operations.image_data(picture(format=format))

    def test_other_formats_and_garbage_are_refused(self):
        for data in [picture(format="GIF"), b"not an image", b""]:
            with self.assertRaises(operations.InvalidImage):
                operations.image_data(data)

    def test_more_than_5_mb_is_refused(self):
        with self.assertRaises(operations.InvalidImage):
            operations.image_data(b"x" * (5 * 1024 * 1024 + 1))


class OperationsTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.root = person("Root", is_admin=True)
        self.cleo = person("Cleo", client=True)

    def test_set_stores_the_image_and_replaces_the_old_one(self):
        with self.captureOnCommitCallbacks(execute=True):
            operations.set_image(self.ada, picture(), actor=self.ada)
        first = self.ada.image
        self.assertTrue(default_storage.exists(first))
        self.assertTrue(first.startswith(f"people/{self.ada.pk}/"))
        with self.captureOnCommitCallbacks(execute=True):
            operations.set_image(self.ada, picture(), actor=self.ada)
        self.assertNotEqual(first, self.ada.image)
        self.assertFalse(default_storage.exists(first))
        self.ada.refresh_from_db()
        self.assertTrue(default_storage.exists(self.ada.image))

    def test_nobody_sets_somebody_elses_image_not_even_admins(self):
        for actor in [self.root, self.cleo]:
            with self.assertRaises(PermissionDenied):
                operations.set_image(self.ada, picture(), actor=actor)

    def test_remove_by_the_person_or_an_admin_only(self):
        operations.set_image(self.ada, picture(), actor=self.ada)
        with self.assertRaises(PermissionDenied):
            operations.remove_image(self.ada, actor=self.cleo)
        name = self.ada.image
        with self.captureOnCommitCallbacks(execute=True):
            operations.remove_image(self.ada, actor=self.root)
        self.ada.refresh_from_db()
        self.assertEqual(self.ada.image, "")
        self.assertFalse(default_storage.exists(name))

    def test_removing_is_in_the_audit_log(self):
        operations.set_image(self.ada, picture(), actor=self.ada)
        name = self.ada.image
        LoggedAction.objects.all().delete()
        operations.remove_image(self.ada, actor=self.root)
        change = LoggedAction.objects.get(table_name="accounts_user")
        self.assertEqual(change.action, "U")
        self.assertEqual(change.changed_fields["image"], "")
        self.assertEqual(change.row_data["image"], name)


class ServingTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.ben = person("Ben")
        self.pia = partner("Pia")
        self.paul = partner("Paul")
        self.cleo = person("Cleo", client=True)
        self.dora = person("Dora", client=True, organization="Other Clients")
        self.camp = project("Camp", members=[self.pia, self.cleo], all_access=False)
        for user in [self.ada, self.pia, self.cleo]:
            operations.set_image(user, picture(), actor=user)

    def url(self, user):
        return reverse("person_image", args=[user.pk, user.image_version])

    def test_own_staff_get_everybody_s_image_with_long_cache_headers(self):
        self.client.force_login(self.ben)
        response = self.client.get(self.url(self.cleo))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/webp")
        self.assertEqual(
            Image.open(io.BytesIO(response.content)).size,
            (256, 256),
        )
        cache = response["Cache-Control"]
        self.assertIn("max-age=31536000", cache)
        self.assertIn("immutable", cache)
        self.assertIn("private", cache)

    def test_partners_and_clients_get_the_images_of_members_of_their_projects(self):
        self.client.force_login(self.pia)
        self.assertEqual(self.client.get(self.url(self.cleo)).status_code, 200)
        self.assertEqual(self.client.get(self.url(self.pia)).status_code, 200)
        self.client.force_login(self.cleo)
        self.assertEqual(self.client.get(self.url(self.pia)).status_code, 200)

    def test_partners_get_those_of_staff_with_access_to_their_projects(self):
        # Partners know a project's people (decided 2026-11-21): Ada opens
        # the all-access project without being a member; clients don't
        open_camp = project("Open camp", members=[self.pia, self.cleo])
        self.client.force_login(self.pia)
        self.assertEqual(self.client.get(self.url(self.ada)).status_code, 200)
        self.client.force_login(self.cleo)
        self.assertEqual(self.client.get(self.url(self.ada)).status_code, 404)
        open_camp.memberships.filter(user=self.pia).delete()
        self.client.force_login(self.pia)
        self.assertEqual(self.client.get(self.url(self.ada)).status_code, 404)

    def test_not_the_images_of_people_they_do_not_know(self):
        # Ada is staff but in no project with Pia or Cleo
        for user in [self.pia, self.cleo, self.paul, self.dora]:
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url(self.ada)).status_code, 404)
        self.client.force_login(self.paul)
        self.assertEqual(self.client.get(self.url(self.cleo)).status_code, 404)

    def test_anybody_gets_their_own(self):
        self.client.force_login(self.paul)
        operations.set_image(self.paul, picture(), actor=self.paul)
        self.assertEqual(self.client.get(self.url(self.paul)).status_code, 200)

    def test_anonymous_gets_nothing(self):
        response = self.client.get(self.url(self.ada))
        self.assertNotEqual(response.status_code, 200)

    def test_a_wrong_version_and_no_image_are_404(self):
        self.client.force_login(self.ben)
        self.assertEqual(
            self.client.get(
                reverse("person_image", args=[self.ada.pk, "old"])
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                reverse("person_image", args=[self.ben.pk, "x"])
            ).status_code,
            404,
        )

    def test_a_new_image_has_a_new_url(self):
        old = self.url(self.ada)
        operations.set_image(self.ada, picture(), actor=self.ada)
        self.assertNotEqual(old, self.url(self.ada))
        self.client.force_login(self.ben)
        self.assertEqual(self.client.get(old).status_code, 404)
        self.assertEqual(self.client.get(self.url(self.ada)).status_code, 200)


class AvatarTagTest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.ben = person("Ben")
        self.cleo = person("Cleo", client=True)
        self.camp = project("Camp", members=[self.cleo])

    def render(self, viewer, who, size="sm"):
        request = RequestFactory().get("/")
        request.user = viewer
        return Template(f"{{% load biwak %}}{{% avatar who '{size}' %}}").render(
            Context({"request": request, "who": who})
        )

    def test_initials_on_a_palette_color_chosen_from_the_id(self):
        html = self.render(self.ada, self.ben)
        self.assertIn(">BE</span>", html)
        self.assertIn(f'data-avatar-color="{PALETTE[self.ben.pk % 10]}"', html)
        self.assertIn('title="Ben Example"', html)
        self.assertEqual(
            html, self.render(self.cleo, self.ben).replace("Cleo", "Ada")
        )  # the same for everybody

    def test_initials_of_single_names_and_addresses(self):
        self.ben.full_name = "Ben"
        self.assertEqual(self.ben.initials, "B")
        self.ben.full_name = "ada maria von lovelace"
        self.assertEqual(self.ben.initials, "AL")
        self.ben.full_name = ""
        self.assertEqual(self.ben.initials, "B")  # from ben@example.org

    def test_the_image_with_alt_and_title(self):
        operations.set_image(self.ben, picture(), actor=self.ben)
        html = self.render(self.ada, self.ben, "lg")
        self.assertIn(
            f"/accounts/people/{self.ben.pk}/image/{self.ben.image_version}.webp", html
        )
        self.assertIn('alt="Ben Example"', html)
        self.assertIn('title="Ben Example"', html)
        self.assertIn("wb-avatar-lg", html)

    def test_no_image_where_the_viewer_may_not_know_the_person(self):
        operations.set_image(self.ben, picture(), actor=self.ben)
        html = self.render(self.cleo, self.ben)  # not in a project of Cleo's
        self.assertNotIn("<img", html)
        self.assertIn(">BE</span>", html)

    def test_without_a_request_only_initials(self):
        operations.set_image(self.ben, picture(), actor=self.ben)
        html = Template("{% load biwak %}{% avatar who %}").render(
            Context({"who": self.ben})
        )
        self.assertNotIn("<img", html)

    def test_unknown_sizes_are_an_error(self):
        with self.assertRaises(ValueError):
            self.render(self.ada, self.ben, "huge")


class SettingsTest(TestCase):
    def setUp(self):
        self.cleo = person("Cleo", client=True)
        self.client.force_login(self.cleo)

    def upload(self, data, name="me.png"):
        file = io.BytesIO(data)
        file.name = name
        return self.client.post(reverse("settings_image"), {"image": file}, follow=True)

    def test_the_section_is_on_the_settings_page(self):
        response = self.client.get(reverse("settings"))
        self.assertContains(response, "Profile image")
        self.assertContains(response, "JPEG, PNG or WebP, at most 5 MB.")
        self.assertNotContains(response, "image/remove/")

    def test_uploading_shows_the_image_and_offers_removing(self):
        response = self.upload(picture())
        self.assertContains(response, "Your profile image has been saved.")
        self.cleo.refresh_from_db()
        self.assertTrue(self.cleo.image)
        self.assertContains(response, "<img")
        self.assertContains(
            response, reverse("person_image_remove", args=[self.cleo.pk])
        )

    def test_a_wrong_file_is_refused_with_a_message(self):
        response = self.upload(b"just text", "me.png")
        self.assertContains(response, "Please upload a JPEG, PNG or WebP image.")
        self.cleo.refresh_from_db()
        self.assertEqual(self.cleo.image, "")
        response = self.client.post(reverse("settings_image"), follow=True)
        self.assertContains(response, "Please choose an image.")

    def test_removing_asks_first_then_goes_back_to_the_initials(self):
        self.upload(picture())
        url = reverse("person_image_remove", args=[self.cleo.pk])
        self.assertContains(self.client.get(url), "Remove the profile image?")
        self.cleo.refresh_from_db()
        self.assertTrue(self.cleo.image)
        response = self.client.post(url, follow=True)
        self.assertContains(response, "Your profile image has been removed.")
        self.cleo.refresh_from_db()
        self.assertEqual(self.cleo.image, "")
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_the_modal_form_is_the_form_only(self):
        self.upload(picture())
        url = reverse("person_image_remove", args=[self.cleo.pk])
        response = self.client.get(url, headers={"HX-Modal": "true"})
        self.assertNotContains(response, "<html")
        self.assertContains(response, "Remove")


class APITest(TestCase):
    def setUp(self):
        self.ada = person("Ada")
        self.cleo = person("Cleo", client=True)
        self.camp = project("Camp", members=[self.ada, self.cleo])

    def headers(self, user, access="write"):
        _token, secret = APIToken.create_for(user=user, title="T", access=access)
        return {"authorization": f"Bearer {secret}"}

    def put(self, user, data, name="me.png", access="write"):
        file = SimpleUploadedFile(name, data)
        return self.client.put(
            "/api/v1/me/image/",
            encode_multipart(BOUNDARY, {"image": file}),
            content_type=MULTIPART_CONTENT,
            headers=self.headers(user, access),
        )

    def test_people_have_an_image_url_or_null(self):
        headers = self.headers(self.cleo)
        data = self.client.get("/api/v1/me/", headers=headers).json()
        self.assertIsNone(data["image_url"])
        self.assertEqual(self.put(self.cleo, picture()).status_code, 200)
        self.cleo.refresh_from_db()
        data = self.client.get("/api/v1/me/", headers=headers).json()
        self.assertEqual(data["image_url"], settings.BASE_URL + self.cleo.image_url)
        # In other people's outputs too (the project's members), where the
        # image is served to whoever may know the person
        members = self.client.get(
            f"/api/v1/projects/{self.camp.pk}/members/", headers=self.headers(self.ada)
        ).json()
        urls = {m["name"]: m["image_url"] for m in members}
        self.assertTrue(urls["Cleo Example"].endswith(self.cleo.image_url))
        self.assertIsNone(urls["Ada Example"])

    def test_uploading_and_removing(self):
        response = self.put(self.ada, picture())
        self.assertEqual(response.status_code, 200)
        self.ada.refresh_from_db()
        name = self.ada.image
        self.assertTrue(default_storage.exists(name))
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.delete(
                "/api/v1/me/image/", headers=self.headers(self.ada)
            )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["image_url"])
        self.assertFalse(default_storage.exists(name))

    def test_invalid_images_are_a_400(self):
        response = self.put(self.ada, b"not an image")
        self.assertEqual(response.status_code, 400)
        self.assertIn("JPEG, PNG or WebP", response.json()["detail"])

    def test_a_read_only_token_cannot_change_it(self):
        self.assertEqual(self.put(self.ada, picture(), access="read").status_code, 403)

    def test_the_images_follow_the_visibility_through_the_api_url(self):
        self.put(self.cleo, picture())
        self.cleo.refresh_from_db()
        stranger = person("Dora", client=True, organization="Other")
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(self.cleo.image_url).status_code, 404)
        self.client.force_login(self.ada)
        self.assertEqual(self.client.get(self.cleo.image_url).status_code, 200)
