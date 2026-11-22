"""Files served from their storage's URLs (specs/files.md, "Downloads",
decided 2026-11-22): pages get presigned URLs with a bucket, cached so a
file's URL stays the same; mails and the API keep the checking views"""

from unittest import mock
from urllib.parse import parse_qs, urlsplit

import boto3
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from moto import mock_aws
from storages.backends.s3 import S3Storage

from biwak.accounts.models import APIToken
from biwak.files import attachments, file_urls
from biwak.files.test_attachments import PNG
from biwak.files.test_library import png
from biwak.files.views import media
from biwak.items import operations as ops
from biwak.templatetags.biwak import mail_markdown
from biwak.test_utils import person, project


BUCKET = {
    "default": {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": "biwak-test",
            "access_key": "testing",
            "secret_key": "testing",
            "region_name": "us-east-1",
            "default_acl": None,
            "querystring_auth": True,
            "file_overwrite": False,
            "signature_version": "s3v4",
        },
    },
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


class Fixture:
    def setUp(self):
        cache.clear()
        self.ada = person("Ada")
        self.cleo = person("Cleo", client=True)
        self.project = project(members=[self.ada, self.cleo])
        self.shared = ops.create_list(
            project=self.project, title="Shared", creator=self.ada, visible=True
        )
        self.internal = ops.create_list(
            project=self.project, title="Internal", creator=self.ada
        )
        self.todo = ops.create_todo(
            todolist=self.shared, title="Visible", creator=self.ada
        )
        self.secret = ops.create_todo(
            todolist=self.internal, title="Secret", creator=self.ada
        )
        self.image = self.attach(self.todo, "sketch.png")
        self.salaries = self.attach(self.secret, "salaries.png")
        self.file = ops.create_upload(
            project=self.project,
            file=ContentFile(png(), name="map.png"),
            creator=self.ada,
            visible=True,
        )
        self.version = self.file.upload.versions.get()

    def attach(self, item, name):
        attachment = attachments.upload(
            project=self.project,
            file=ContentFile(PNG, name=name),
            uploaded_by=self.ada,
        )
        ops.update_todo(item, actor=self.ada, notes=attachment.markdown)
        return attachment


class DiskTest(Fixture, TestCase):
    def test_the_storages_url_under_media_url(self):
        self.assertEqual(
            file_urls.file_url(self.image),
            f"/media/{self.image.file.name}",
        )

    def test_a_preview_once_made(self):
        fallback = reverse("file_preview", args=[self.file.pk])
        self.assertEqual(file_urls.preview_url(self.version, fallback), fallback)
        self.client.force_login(self.ada)
        self.assertEqual(self.client.get(fallback).status_code, 200)
        url = file_urls.preview_url(self.version, fallback)
        self.assertTrue(url.startswith("/media/files/"))
        self.assertTrue(url.endswith("/preview/preview.webp"))

    def test_media_serves_with_the_downloads_headers(self):
        request = RequestFactory().get("/")
        for name, content, inline in [
            ("evil.svg", b"<svg/>", False),
            ("plan.pdf", b"%PDF", True),
            ("sketch.png", PNG, True),
        ]:
            with self.subTest(name=name):
                attachment = attachments.upload(
                    project=self.project,
                    file=ContentFile(content, name=name),
                    uploaded_by=self.ada,
                )
                response = media(request, attachment.file.name)
                self.assertEqual(b"".join(response.streaming_content), content)
                self.assertEqual(response["Content-Type"], attachment.content_type)
                self.assertEqual(
                    response["Content-Disposition"].startswith("inline"), inline
                )
                self.assertEqual(response["X-Content-Type-Options"], "nosniff")


@mock_aws
@override_settings(STORAGES=BUCKET)
class BucketTest(Fixture, TestCase):
    def setUp(self):
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="biwak-test")
        super().setUp()

    def query(self, url):
        return parse_qs(urlsplit(url).query)

    def test_presigned_an_hour_with_type_and_disposition(self):
        query = self.query(file_urls.file_url(self.image))
        self.assertEqual(query["X-Amz-Expires"], ["3600"])
        self.assertEqual(query["response-content-type"], ["image/png"])
        self.assertEqual(
            query["response-content-disposition"], ['inline; filename="sketch.png"']
        )
        evil = attachments.upload(
            project=self.project,
            file=ContentFile(b"<svg/>", name="evil.svg"),
            uploaded_by=self.ada,
        )
        query = self.query(file_urls.file_url(evil))
        self.assertEqual(query["response-content-type"], ["image/svg+xml"])
        self.assertEqual(
            query["response-content-disposition"], ['attachment; filename="evil.svg"']
        )

    def test_the_cache_keeps_the_url(self):
        first = file_urls.file_url(self.image)
        self.client.force_login(self.ada)
        with mock.patch.object(
            S3Storage, "url", side_effect=AssertionError("signed again")
        ):
            self.assertEqual(file_urls.file_url(self.image), first)
            # The download view hands out the same one
            response = self.client.get(self.image.get_absolute_url())
            self.assertEqual(response["Location"], first)
        # Cached for 50 minutes of its hour
        cache.clear()
        with mock.patch.object(cache, "set") as cache_set:
            file_urls.file_url(self.image)
        self.assertEqual(cache_set.call_args.args[2], 50 * 60)
        # Another disposition is another URL
        self.assertNotEqual(
            file_urls.storage_url(
                self.image.file.storage,
                self.image.file.name,
                content_type="image/png",
                filename="sketch.png",
                as_attachment=True,
            ),
            first,
        )

    def test_pages_get_presigned_urls(self):
        self.client.force_login(self.ada)
        page = self.client.get(self.todo.get_absolute_url()).content.decode()
        self.assertIn(
            f'src="{file_urls.file_url(self.image).replace("&", "&amp;")}"', page
        )
        self.assertNotIn(self.image.get_absolute_url(), page)
        page = self.client.get(self.file.get_absolute_url()).content.decode()
        self.assertIn(
            f'href="{file_urls.file_url(self.version).replace("&", "&amp;")}"', page
        )
        self.assertNotIn(reverse("file_download", args=[self.file.pk]), page)
        # The preview through the view until it was made, then presigned
        preview = reverse("file_preview", args=[self.file.pk])
        self.assertIn(f'src="{preview}"', page)
        self.assertEqual(self.client.get(preview).status_code, 302)
        page = self.client.get(self.file.get_absolute_url()).content.decode()
        self.assertNotIn(f'src="{preview}"', page)
        self.assertIn("preview.webp", page)
        folder = self.client.get(reverse("project_files", args=[self.project.pk]))
        self.assertContains(folder, "preview.webp")
        self.assertNotContains(folder, preview)

    def test_a_client_gets_no_url_for_internal_files(self):
        self.client.force_login(self.cleo)
        page = self.client.get(self.todo.get_absolute_url())
        self.assertContains(page, "sketch.png")
        self.assertNotContains(page, self.salaries.key)
        self.assertEqual(
            self.client.get(self.secret.get_absolute_url()).status_code, 404
        )
        self.assertEqual(
            self.client.get(self.salaries.get_absolute_url()).status_code, 404
        )

    def test_mails_and_the_api_keep_the_views(self):
        html = str(mail_markdown(self.image.markdown, self.todo))
        self.assertIn(
            f'src="http://127.0.0.1:8000{self.image.get_absolute_url()}"', html
        )
        self.assertNotIn("X-Amz", html)
        _token, secret = APIToken.create_for(user=self.ada, title="T", access="read")
        data = self.client.get(
            f"/api/v1/todos/{self.todo.pk}/",
            headers={"authorization": f"Bearer {secret}"},
        ).json()
        self.assertIn(self.image.get_absolute_url(), data["notes_html"])
        self.assertNotIn("X-Amz", data["notes_html"])
