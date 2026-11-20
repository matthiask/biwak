from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from biwak.storage_url import storage_from_url


BASE = Path("/srv/app")


class StorageURLTest(SimpleTestCase):
    def test_file(self):
        storage = storage_from_url("file:./media/", base_dir=BASE)
        self.assertEqual(
            storage["BACKEND"], "django.core.files.storage.FileSystemStorage"
        )
        self.assertEqual(storage["OPTIONS"]["location"], BASE / "media")

    def test_s3_compatible(self):
        storage = storage_from_url(
            "s3://KEY:SECRET@objects.example.org/bucket/?aws_s3_bucket_auth=True"
            "&aws_s3_max_age_seconds=3600",
            base_dir=BASE,
        )
        self.assertEqual(storage["BACKEND"], "storages.backends.s3.S3Storage")
        self.assertEqual(
            storage["OPTIONS"],
            {
                "access_key": "KEY",
                "secret_key": "SECRET",
                "bucket_name": "bucket",
                "endpoint_url": "https://objects.example.org",
                "default_acl": None,
                "querystring_auth": True,
                "file_overwrite": False,
                "signature_version": "s3v4",
            },
        )

    def test_key_prefix_and_public_auth_ignored(self):
        storage = storage_from_url(
            "s3://KEY:SECRET@objects.example.org/bucket/biwak/files/"
            "?aws_s3_bucket_auth=False",
            base_dir=BASE,
        )
        self.assertEqual(storage["OPTIONS"]["location"], "biwak/files")
        # Always presigned: the bucket is private
        self.assertTrue(storage["OPTIONS"]["querystring_auth"])

    def test_unknown_option(self):
        with self.assertRaises(ImproperlyConfigured):
            storage_from_url(
                "s3://KEY:SECRET@objects.example.org/bucket/?aws_s3_gzip=True",
                base_dir=BASE,
            )
