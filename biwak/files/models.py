"""Files attached to texts (specs/files.md, stage 1)

An attachment isn't an item: it belongs to the item whose text references
it, and is visible exactly when that item is. Until the text is saved it
has no item and only its uploader sees it; ``fairy_tasks`` deletes those
after a day. The file lives in the default storage (local disk, or a
bucket, ``biwak/settings.py``) and is only ever handed out through the
download views, after the visibility check.
"""

import mimetypes
import re

from django.conf import settings
from django.db import models, transaction
from django.db.models import Q
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.translation import gettext_lazy as _

from biwak.items.models import Item
from biwak.projects.models import Project


# 100 MB per file (decided 2026-11-20); the ingress needs the same limit
MAX_SIZE = 100 * 1024 * 1024

KEY_LENGTH = 16
KEY_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789"
# How texts reference attachments: ![name](attachment:KEY), [name](...)
REFERENCE = re.compile(rf"attachment:([{KEY_CHARS}]{{{KEY_LENGTH}}})")

# Shown in the browser (Content-Disposition: inline) and as images in
# texts; everything else is a download. Never SVG or HTML: they can carry
# scripts.
IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/avif"}
INLINE_TYPES = IMAGE_TYPES | {"application/pdf"}


class ContentTypeMixin:
    """What attachments and file versions share: how their content type
    is shown"""

    content_type: str

    @property
    def is_image(self):
        return self.content_type in IMAGE_TYPES

    @property
    def is_inline(self):
        return self.content_type in INLINE_TYPES


def new_key():
    return get_random_string(KEY_LENGTH, KEY_CHARS)


def content_type_for(name):
    """From the name, not from what the browser claims"""
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


# The stored name is shortened to this many bytes (file systems allow 255
# bytes, and the folder's key and the path need room); the shown name is
# the full one (``Attachment.name``)
STORAGE_NAME_BYTES = 100


def storage_name(filename):
    """The name a file is stored under: ASCII-safe characters of the name
    and its extension, at most ``STORAGE_NAME_BYTES`` bytes long, never
    empty ("file" for names of only symbols). Files already stored keep
    their names."""
    stem, dot, extension = str(filename).rpartition(".")
    if not dot:
        stem, extension = extension, ""
    stem = _unsafe.sub("", "_".join(stem.split()))
    extension = _unsafe.sub("", extension)[:20].encode()[:20].decode()
    stem = stem.strip("._")
    room = STORAGE_NAME_BYTES - len(extension.encode()) - (1 if extension else 0)
    stem = stem.encode()[:room].decode(errors="ignore") or "file"
    return f"{stem}.{extension}" if extension else stem


_unsafe = re.compile(r"[^-\w.]")


def attachment_path(attachment, filename):
    """files/<project>/<key>/<name>: names never collide, paths can't be
    guessed"""
    return f"files/{attachment.project_id}/{attachment.key}/{storage_name(filename)}"


class AttachmentQuerySet(models.QuerySet):
    def visible_to(self, user):
        """Attachments of items the person sees (the one check,
        ``Item.objects.visible_to()``), and their own unlinked uploads in
        projects they can open"""
        if not user.is_authenticated or not user.is_active:
            return self.none()
        return self.filter(
            Q(item__in=Item.objects.visible_to(user))
            | Q(
                item__isnull=True,
                uploaded_by=user,
                project__in=Project.objects.accessible_to(user),
            )
        )


class Attachment(ContentTypeMixin, models.Model):
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="attachments",
        verbose_name=_("project"),
    )
    # Set when the text referencing it is saved (attachments.link())
    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="attachments",
        verbose_name=_("item"),
    )
    key = models.CharField(_("key"), max_length=KEY_LENGTH, unique=True)
    file = models.FileField(_("file"), upload_to=attachment_path, max_length=500)
    name = models.CharField(_("name"), max_length=255)
    size = models.PositiveBigIntegerField(_("size"))
    content_type = models.CharField(_("content type"), max_length=200)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("uploaded by"),
    )
    created_at = models.DateTimeField(_("created at"), default=timezone.now)

    objects = AttachmentQuerySet.as_manager()

    class Meta:
        ordering = ["created_at", "pk"]
        # Deleting a row asks whether another one still uses its file
        indexes = [models.Index(fields=["file"], name="files_attachment_file")]
        verbose_name = _("attachment")
        verbose_name_plural = _("attachments")

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("attachment", kwargs={"key": self.key, "name": self.name})

    @property
    def markdown(self):
        """What the text gets: an image or a link"""
        name = re.sub(r"([\\\[\]])", r"\\\1", " ".join(self.name.split()))
        return f"{'!' if self.is_image else ''}[{name}](attachment:{self.key})"


@receiver(post_delete, sender=Attachment)
def delete_file(sender, instance, **kwargs):
    """Deleting the row (also through items purged from the trash or a
    deleted project, which cascade) deletes the file, once the transaction
    commits, unless another row still uses it (the next to-do of a
    repeating one shares its predecessor's files, specs/files.md)"""
    name, storage = instance.file.name, instance.file.storage
    if name:

        def delete():
            if not Attachment.objects.filter(file=name).exists():
                storage.delete(name)

        transaction.on_commit(delete)


def version_path(version, filename):
    """files/<project>/<key>/<name>, like attachments"""
    project_id = version.upload.item.project_id
    return f"files/{project_id}/{new_key()}/{storage_name(filename)}"


class FileVersion(ContentTypeMixin, models.Model):
    """A version of an uploaded file (kind ``file``); the newest is the
    current one. Visible exactly when its file's item is."""

    upload = models.ForeignKey(
        "items.Upload",
        on_delete=models.CASCADE,
        related_name="versions",
        verbose_name=_("file"),
    )
    file = models.FileField(_("file"), upload_to=version_path, max_length=500)
    name = models.CharField(_("name"), max_length=255)
    size = models.PositiveBigIntegerField(_("size"))
    content_type = models.CharField(_("content type"), max_length=200)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("uploaded by"),
    )
    uploaded_at = models.DateTimeField(_("uploaded at"), default=timezone.now)

    class Meta:
        ordering = ["-uploaded_at", "-pk"]
        verbose_name = _("file version")
        verbose_name_plural = _("file versions")

    def __str__(self):
        return self.name

    @property
    def has_preview(self):
        """Images and PDFs get a preview (``biwak.files.previews``): what
        browsers show"""
        return self.is_inline


@receiver(post_delete, sender=FileVersion)
def delete_version_files(sender, instance, **kwargs):
    """The file and its preview go with the row, once the transaction
    commits"""
    name, storage = instance.file.name, instance.file.storage
    if name:
        names = [name, preview_name(name), failed_preview_name(name)]
        transaction.on_commit(lambda: [storage.delete(n) for n in names])


def preview_name(name):
    """The preview is stored in a folder next to the file: file names
    have no slashes, so none can be named like it"""
    return f"{name.rsplit('/', 1)[0]}/preview/preview.webp"


def failed_preview_name(name):
    """An empty file next to the preview: making it failed, don't try again"""
    return f"{name.rsplit('/', 1)[0]}/preview/failed"
