"""``STORAGE_URL`` (specs/files.md) for Django's ``STORAGES``.

speckenv's ``django_storage_url`` reads ``file:`` and ``s3:`` URLs, but its
``s3:`` backend is django-s3-storage. The downloads need django-storages'
``S3Storage`` (presigned URLs with their own expiry, content type and
disposition per request, ``biwak/files/attachments.py``), so its options are
translated here. Options nobody translated are an error, not ignored.
"""

from django.core.exceptions import ImproperlyConfigured
from speckenv_django import django_storage_url


# django-s3-storage's option: django-storages' option (None: not used)
S3_OPTIONS = {
    "aws_access_key_id": "access_key",
    "aws_secret_access_key": "secret_key",
    "aws_s3_bucket_name": "bucket_name",
    "aws_s3_key_prefix": "location",
    "aws_s3_endpoint_url": "endpoint_url",
    "aws_region": "region_name",
    # The bucket is always private and downloads always presigned, with
    # the expiry the download sets
    "aws_s3_bucket_auth": None,
    "aws_s3_max_age_seconds": None,
}


def storage_from_url(url, *, base_dir):
    storage = django_storage_url(url, base_dir=base_dir)
    if storage["BACKEND"] != "django_s3_storage.storage.S3Storage":
        return storage
    unknown = storage["OPTIONS"].keys() - S3_OPTIONS.keys()
    if unknown:
        raise ImproperlyConfigured(
            f"STORAGE_URL: options without a translation: {sorted(unknown)}"
        )
    options = {
        S3_OPTIONS[key]: value
        for key, value in storage["OPTIONS"].items()
        if S3_OPTIONS[key] and value
    }
    return {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": options
        | {
            # The bucket's own policy decides (private); some providers
            # refuse ACLs
            "default_acl": None,
            "querystring_auth": True,
            "file_overwrite": False,
            "signature_version": "s3v4",
        },
    }
