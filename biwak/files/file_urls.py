"""The URLs pages use for files (specs/files.md, "Downloads", decided
2026-11-22)

Pages link and embed files at their storage's URL, not through the app:
with a bucket a presigned URL valid ``PRESIGNED_SECONDS``, with the
content type and disposition the download views would set, kept in
Django's cache for most of that time so a file's URL stays the same and
browsers cache it; on disk (development) ``MEDIA_URL``, served by
``biwak.files.views.media`` with ``DEBUG`` only.

Only pages which checked access already use these. Where an address must
stay valid (mails, the API, links people copy to share) the app's own
download views stay, which check every time (``attachments.serve()``).
"""

import hashlib

from django.core.cache import cache
from django.utils.http import content_disposition_header


# How long a presigned URL is valid
PRESIGNED_SECONDS = 3600
# How long one is handed out again: what's left is enough for a page
# opened just before it changes
CACHED_SECONDS = 50 * 60

PREVIEW = {"content_type": "image/webp", "filename": "preview.webp"}


def presigns(storage):
    """Buckets hand out presigned URLs; other storages (local disk) are
    served by name"""
    try:
        from storages.backends.s3 import S3Storage
    except ImportError:  # pragma: no cover
        return False
    return isinstance(storage, S3Storage)


def parameters(*, content_type, filename, as_attachment):
    """The bucket's response headers: images and PDFs inline, everything
    else (SVG and HTML above all) a download"""
    return {
        "ResponseContentType": content_type,
        "ResponseContentDisposition": content_disposition_header(
            as_attachment, filename
        ),
    }


def _key(name, params):
    raw = "\0".join([name, *(f"{k}={v}" for k, v in sorted(params.items()))])
    return "file-url:" + hashlib.sha256(raw.encode()).hexdigest()


def cached_url(storage, name, *, content_type, filename, as_attachment):
    """The presigned URL handed out already, or None (always None on disk)"""
    if not presigns(storage):
        return None
    params = parameters(
        content_type=content_type, filename=filename, as_attachment=as_attachment
    )
    return cache.get(_key(name, params))


def storage_url(storage, name, *, content_type, filename, as_attachment):
    """The URL of a stored file: presigned and cached with a bucket, the
    storage's own (``MEDIA_URL``) on disk"""
    if not presigns(storage):
        return storage.url(name)
    params = parameters(
        content_type=content_type, filename=filename, as_attachment=as_attachment
    )
    key = _key(name, params)
    if (url := cache.get(key)) is None:
        url = storage.url(name, parameters=params, expire=PRESIGNED_SECONDS)
        cache.set(key, url, CACHED_SECONDS)
    return url


def file_url(file):
    """For everything with ``file``, ``name``, ``content_type`` and
    ``is_inline``: attachments, file versions, forwarded files"""
    return storage_url(
        file.file.storage,
        file.file.name,
        content_type=file.content_type,
        filename=file.name,
        as_attachment=not file.is_inline,
    )


def preview_url(version, fallback):
    """The preview of a file version once it was made and handed out (the
    preview view makes it on the first request, ``previews.serve()``),
    else ``fallback``, the view's URL: a page doesn't look into the bucket
    for every tile"""
    from biwak.files.models import preview_name

    storage = version.file.storage
    name = preview_name(version.file.name)
    if presigns(storage):
        url = cached_url(storage, name, **PREVIEW, as_attachment=False)
    else:
        url = storage.url(name) if storage.exists(name) else None
    return url or fallback
