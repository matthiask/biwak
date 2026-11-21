"""Uploading, linking and serving attachments (specs/files.md, stage 1)

The operations of attachments: views and the API call these. The item
operations saving texts call ``link()``.
"""

import contextlib
import contextvars
import datetime as dt
import functools
from pathlib import PurePath

from django.db import transaction
from django.http import FileResponse, HttpResponseRedirect
from django.utils import timezone
from django.utils.cache import patch_cache_control
from django.utils.http import content_disposition_header
from django.utils.translation import gettext as _

from biwak.files.models import (
    MAX_SIZE,
    REFERENCE,
    Attachment,
    content_type_for,
    new_key,
)


# Unlinked attachments (uploaded, but the text never saved) are deleted
# after this (fairy_tasks)
UNLINKED_DAYS = 1
# How long a presigned download URL of the bucket is valid
PRESIGNED_SECONDS = 300


class UploadError(ValueError):
    pass


def clean_name(name):
    """The file's name without directories, never empty"""
    name = " ".join(PurePath(str(name).replace("\\", "/")).name.split())
    return name[-255:] or "file"


# The files stored by the operation running (see ``cleans_up_files``)
_stored = contextvars.ContextVar("stored_files", default=None)


def store(fieldfile, name, file):
    """Saves ``file`` through the model's file field. If the running
    operation fails afterwards, ``cleans_up_files`` deletes it."""
    fieldfile.save(name, file, save=False)
    if (stored := _stored.get()) is not None:
        stored.append((fieldfile.storage, fieldfile.name))


def cleans_up_files(function):
    """For operations storing files (``store()``) inside a transaction: a
    rolled back transaction doesn't take the files back, so the files
    stored are deleted when the operation raises. Put it outside of
    ``@transaction.atomic``."""

    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        if _stored.get() is not None:  # nested: the outer one cleans up
            return function(*args, **kwargs)
        stored = []
        token = _stored.set(stored)
        try:
            return function(*args, **kwargs)
        except BaseException:
            for storage, name in stored:
                with contextlib.suppress(OSError):
                    storage.delete(name)
            raise
        finally:
            _stored.reset(token)

    return wrapper


def check_size(file):
    if file.size > MAX_SIZE:
        raise UploadError(
            _("Files can be at most %(size)s MB.") % {"size": MAX_SIZE // 2**20}
        )


@cleans_up_files
@transaction.atomic
def upload(*, project, file, uploaded_by):
    """Stores the file as an attachment without item; the caller checked
    that the person may open the project"""
    check_size(file)
    name = clean_name(file.name)
    attachment = Attachment(
        project=project,
        key=new_key(),
        name=name,
        size=file.size,
        content_type=content_type_for(name),
        uploaded_by=uploaded_by,
    )
    store(attachment.file, name, file)
    attachment.save()
    return attachment


def link(item, text, *, actor):
    """Links the attachments ``text`` references to ``item``: those without
    item yet, in the item's project, uploaded by ``actor`` (the one saving
    the text). Called by the operations saving texts, in their
    transaction."""
    keys = set(REFERENCE.findall(text or ""))
    if not keys:
        return 0
    return Attachment.objects.filter(
        key__in=keys, item=None, project=item.project_id, uploaded_by=actor
    ).update(item=item)


@transaction.atomic
def delete_unlinked(*, now=None):
    """Deletes attachments whose text was never saved, after a day; the
    files go when the transaction commits (``models.delete_file``)"""
    cutoff = (now or timezone.now()) - dt.timedelta(days=UNLINKED_DAYS)
    old = Attachment.objects.filter(item=None, created_at__lt=cutoff)
    count = 0
    for attachment in old:
        attachment.delete()
        count += 1
    return count


def serve(attachment):
    """The download, after the visibility check: a redirect to a presigned
    URL valid 5 minutes with a bucket, the file itself otherwise. Images
    and PDFs inline, everything else (SVG and HTML above all) as a
    download; never sniffed. Works for everything with ``file``, ``name``,
    ``content_type`` and ``is_inline`` (attachments, file versions)."""
    return respond(
        attachment.file.storage,
        attachment.file.name,
        content_type=attachment.content_type,
        filename=attachment.name,
        as_attachment=not attachment.is_inline,
    )


def respond(storage, name, *, content_type, filename, as_attachment):
    if _presigns(storage):
        response = HttpResponseRedirect(
            storage.url(
                name,
                parameters={
                    "ResponseContentType": content_type,
                    "ResponseContentDisposition": content_disposition_header(
                        as_attachment, filename
                    ),
                },
                expire=PRESIGNED_SECONDS,
            )
        )
    else:
        response = FileResponse(
            storage.open(name, "rb"),
            as_attachment=as_attachment,
            filename=filename,
            content_type=content_type,
        )
    response["X-Content-Type-Options"] = "nosniff"
    patch_cache_control(response, private=True, max_age=0)
    return response


def _presigns(storage):
    """Buckets hand out presigned URLs; other storages (local disk, later
    others) are streamed through the app"""
    try:
        from storages.backends.s3 import S3Storage
    except ImportError:  # pragma: no cover
        return False
    return isinstance(storage, S3Storage)
