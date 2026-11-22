from pathlib import Path

from django.test import SimpleTestCase
from storages.backends.s3 import S3Storage

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
        options = dict(storage["OPTIONS"])
        config = options.pop("client_config")
        self.assertEqual(config.request_checksum_calculation, "when_required")
        self.assertEqual(
            options,
            {
                "access_key": "KEY",
                "secret_key": "SECRET",
                "bucket_name": "bucket",
                "location": "",
                "endpoint_url": "https://objects.example.org",
                # speckenv translates django-s3-storage's options
                "querystring_expire": 3600,
                "object_parameters": {"CacheControl": "private, max-age=3600"},
                "default_acl": None,
                "querystring_auth": True,
                "file_overwrite": False,
                "signature_version": "s3v4",
            },
        )

    def test_uploads_without_the_checksums_s3_compatibles_refuse(self):
        """botocore 1.36 and later add a CRC32 checksum to every upload
        (``x-amz-checksum-crc32``, sent chunked); S3-compatible stores which
        don't know it answer InvalidArgument (production, 2026-11-22):
        checksums only where an operation requires one"""
        storage = S3Storage(
            **storage_from_url(
                "s3://KEY:SECRET@objects.example.org/bucket/", base_dir=BASE
            )["OPTIONS"]
        )
        client = storage.connection.meta.client
        sent = []

        class Stop(Exception):
            pass

        def capture(request, **kwargs):
            sent.append({k.lower(): v for k, v in request.headers.items()})
            raise Stop

        client.meta.events.register("before-send.s3.PutObject", capture)
        with self.assertRaises(Stop):
            client.put_object(Bucket="bucket", Key="files/a.txt", Body=b"tent")
        headers = sent[0]
        self.assertFalse([h for h in headers if h.startswith("x-amz-checksum-")])
        self.assertNotIn("x-amz-sdk-checksum-algorithm", headers)
        self.assertNotIn("aws-chunked", headers.get("content-encoding", ""))

    def test_key_prefix_and_public_auth_ignored(self):
        storage = storage_from_url(
            "s3://KEY:SECRET@objects.example.org/bucket/biwak/files/"
            "?aws_s3_bucket_auth=False",
            base_dir=BASE,
        )
        self.assertEqual(storage["OPTIONS"]["location"], "biwak/files")
        # Always presigned and no public ACL: the bucket is private
        self.assertTrue(storage["OPTIONS"]["querystring_auth"])
        self.assertIsNone(storage["OPTIONS"]["default_acl"])

    def test_an_option_without_a_counterpart(self):
        # django-s3-storage's, which django-storages has no URL option for
        with self.assertRaisesRegex(ValueError, "aws_s3_metadata"):
            storage_from_url(
                "s3://KEY:SECRET@objects.example.org/bucket/?aws_s3_metadata=x",
                base_dir=BASE,
            )
