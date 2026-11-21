"""Changes to a person's own preferences (specs/keyboard.md); the settings
page and the API's ``me/`` call these"""

import io

from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils.crypto import get_random_string
from django.utils.translation import gettext as _
from PIL import Image, ImageOps

from biwak.accounts.models import Accent, Theme


@transaction.atomic
def set_preferences(user, *, keyboard_shortcuts=None, theme=None, accent=None):
    """The person's keyboard setting, theme and accent color, what's given"""
    fields = []
    if keyboard_shortcuts is not None:
        user.keyboard_shortcuts = bool(keyboard_shortcuts)
        fields.append("keyboard_shortcuts")
    if theme is not None:
        user.theme = Theme(theme)
        fields.append("theme")
    if accent is not None:
        user.accent = Accent(accent)
        fields.append("accent")
    if fields:
        user.save(update_fields=fields)


# Profile images (specs/people.md) ------------------------------------------

IMAGE_MAX_BYTES = 5 * 1024 * 1024
IMAGE_SIZE = 256
IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}


class InvalidImage(ValueError):
    """Not a JPEG, PNG or WebP image, or too big"""


def can_change_image(actor, person):
    """People change their own image; admins can remove anyone's"""
    return actor.pk == person.pk


def can_remove_image(actor, person):
    return actor.pk == person.pk or actor.is_admin


def image_data(data):
    """The 256 pixel square WebP made from what was uploaded: cut in the
    middle, scaled, rotated as the camera said"""
    if len(data) > IMAGE_MAX_BYTES:
        raise InvalidImage(_("The image is too big (5 MB at most)."))
    try:
        return _square_webp(data)
    except InvalidImage:
        raise
    except Exception as exc:  # broken files, decompression bombs
        raise InvalidImage(_("Please upload a JPEG, PNG or WebP image.")) from exc


def _square_webp(data):
    image = Image.open(io.BytesIO(data))
    if image.format not in IMAGE_FORMATS:
        raise InvalidImage(_("Please upload a JPEG, PNG or WebP image."))
    image.load()
    image = ImageOps.fit(
        ImageOps.exif_transpose(image),
        (IMAGE_SIZE, IMAGE_SIZE),
        method=Image.Resampling.LANCZOS,
    )
    if image.mode not in {"RGB", "RGBA"}:
        image = image.convert("RGBA" if "transparency" in image.info else "RGB")
    out = io.BytesIO()
    image.save(out, "WEBP", quality=85)
    return out.getvalue()


@transaction.atomic
def set_image(person, data, *, actor):
    """Replaces the image with the one in ``data`` (bytes); raises
    ``InvalidImage`` and ``PermissionDenied``"""
    if not can_change_image(actor, person):
        raise PermissionDenied
    return store_image(person, data)


def store_image(person, data):
    """Without the permission check: the importer's and ``set_image``"""
    webp = image_data(data)
    storage = default_storage
    previous = person.image
    version = get_random_string(12, "abcdefghijklmnopqrstuvwxyz0123456789")
    person.image = storage.save(f"people/{person.pk}/{version}.webp", ContentFile(webp))
    person.save(update_fields=["image"])
    if previous:
        transaction.on_commit(lambda: _delete(previous))
    return person


@transaction.atomic
def remove_image(person, *, actor):
    """Back to the initials; recorded in the audit log (the person's row)"""
    if not can_remove_image(actor, person):
        raise PermissionDenied
    previous = person.image
    if previous:
        person.image = ""
        person.save(update_fields=["image"])
        transaction.on_commit(lambda: _delete(previous))
    return person


def _delete(name):
    default_storage.delete(name)
