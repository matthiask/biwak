"""``STORAGE_URL`` (specs/files.md) for Django's ``STORAGES``.

speckenv 7 reads ``file:`` and ``s3:`` URLs, the latter for django-storages'
``S3Storage`` with uploads sending checksums only where required (botocore
1.36's CRC32 default is refused by S3-compatible stores). Biwak's bucket is
always private, downloads always presigned with the expiry each download
sets (``biwak/files/file_urls.py``).
"""

from speckenv_django import django_storage_url


S3 = "storages.backends.s3.S3Storage"


def storage_from_url(url, *, base_dir):
    storage = django_storage_url(url, base_dir=base_dir)
    if storage["BACKEND"] != S3:
        return storage
    storage["OPTIONS"] |= {
        # The bucket's own policy decides (private); some providers refuse
        # ACLs, and a public one would be wrong anyway
        "default_acl": None,
        "querystring_auth": True,
        "file_overwrite": False,
        "signature_version": "s3v4",
    }
    return storage
