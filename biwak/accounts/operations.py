"""Changes to a person's own preferences (specs/keyboard.md); the settings
page and the API's ``me/`` call these"""

import io

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.translation import gettext as _
from PIL import Image, ImageOps

from biwak.accounts.models import Accent, Theme


@transaction.atomic
def set_name(user, *, full_name, short_name):
    """The person's own name; the short name is optional (empty: the first
    word of the full name, ``User.get_short_name()``)"""
    user.full_name = full_name.strip()
    user.short_name = short_name.strip()
    user.save(update_fields=["full_name", "short_name"])


def set_preferences(
    user,
    *,
    keyboard_shortcuts=None,
    theme=None,
    accent=None,
    language=None,
    mark=None,
):
    """The person's keyboard setting, theme, accent color, language
    (``""`` for the browser's) and drawn mark (specs/people.md), what's
    given"""
    from biwak.accounts.marks import MARKS

    fields = []
    if mark is not None:
        if mark not in MARKS:
            raise ValueError(f"Unknown mark {mark!r}")
        user.mark = mark
        fields.append("mark")
    if language is not None:
        if language and language not in dict(settings.LANGUAGES):
            raise ValueError(f"Unknown language {language!r}")
        user.language = language
        fields.append("language")
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


# Out of office (specs/quiet-hours.md) --------------------------------------


def can_set_away(actor, person):
    """People set their own; admins others' (when someone forgot)"""
    return actor.pk == person.pk or (actor.is_admin and actor.is_active)


def one_line(note):
    """The note as one line"""
    return " ".join((note or "").split())


@transaction.atomic
def set_away(person, *, until, note="", actor):
    """Away up to and including ``until`` (today or later) with an optional
    note of one line; raises ``PermissionDenied`` and ``ValidationError``"""
    from biwak.accounts.quiet import NOTE_LENGTH

    if not can_set_away(actor, person):
        raise PermissionDenied
    if until < timezone.localdate():
        raise ValidationError(_("Choose today or a later day."))
    note = one_line(note)
    if len(note) > NOTE_LENGTH:
        raise ValidationError(
            _("The note is too long (%(count)s characters at most).")
            % {"count": NOTE_LENGTH}
        )
    person.away_until = until
    person.away_note = note
    person.save(update_fields=["away_until", "away_note"])
    return person


@transaction.atomic
def end_away(person, *, actor):
    """ "I'm back": ends it early; what waited goes with the next mail"""
    if not can_set_away(actor, person):
        raise PermissionDenied
    person.away_until = None
    person.away_note = ""
    person.save(update_fields=["away_until", "away_note"])
    return person


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
    """Back to the drawn mark; recorded in the audit log (the person's row)"""
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
