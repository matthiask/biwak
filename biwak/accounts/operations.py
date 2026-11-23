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

from biwak.accounts.models import Accent, PushSubscription, Theme


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


# Devices getting push notifications (specs/web-push.md) ---------------------


def subscription_data(data):
    """``(endpoint, p256dh, auth)`` from the JSON of the browser's
    ``PushSubscription.toJSON()``; ``ValidationError`` for anything else"""
    from django.core.validators import URLValidator

    try:
        endpoint = data["endpoint"]
        keys = data["keys"]
        p256dh, auth = keys["p256dh"], keys["auth"]
    except KeyError, TypeError:
        raise ValidationError("Not a push subscription.") from None
    if not all(isinstance(value, str) and value for value in (endpoint, p256dh, auth)):
        raise ValidationError("Not a push subscription.")
    URLValidator(schemes=["https"])(endpoint)
    if len(endpoint) > 1000 or len(p256dh) > 200 or len(auth) > 100:
        raise ValidationError("Not a push subscription.")
    return endpoint, p256dh, auth


@transaction.atomic
def add_device(user, data, *, user_agent=""):
    """Subscribes the device (the JSON of ``PushSubscription.toJSON()``):
    the browser's subscription is the device's, so subscribing again
    updates it; somebody else's on that browser becomes the person's"""
    from biwak.accounts.models import PushSubscription

    endpoint, p256dh, auth = subscription_data(data)
    subscription = (
        PushSubscription.objects.select_for_update().filter(endpoint=endpoint).first()
    )
    if subscription is None or subscription.user_id != user.pk:
        # Somebody else's before: theirs no more, and nothing of before
        # pushed (``push.pending()``)
        if subscription is not None:
            subscription.delete()
        subscription = PushSubscription(user=user, endpoint=endpoint)
    subscription.p256dh, subscription.auth = p256dh, auth
    subscription.user_agent = user_agent[:500]
    subscription.save()
    return subscription


@transaction.atomic
def remove_device(user, *, pk=None, endpoint=None):
    """Removes one of the person's devices, by ID or endpoint; returns
    whether there was one"""
    devices = user.push_subscriptions.all()
    devices = (
        devices.filter(pk=pk) if pk is not None else devices.filter(endpoint=endpoint)
    )
    deleted, _rows = devices.delete()
    return bool(deleted)


# As long as teams' names
DEVICE_NAME_LENGTH = PushSubscription._meta.get_field("name").max_length


def clean_device_name(name):
    """The name with single spaces, ``ValidationError`` when too long;
    empty is the browser and system again"""
    name = " ".join(str(name or "").split())
    if len(name) > DEVICE_NAME_LENGTH:
        raise ValidationError(
            _("At most %(count)s characters.") % {"count": DEVICE_NAME_LENGTH}
        )
    return name


@transaction.atomic
def rename_device(user, *, pk, name):
    """Names one of the person's devices (empty: the browser and system);
    returns it, None when there's no such device of the person's"""
    device = user.push_subscriptions.select_for_update().filter(pk=pk).first()
    if device is None:
        return None
    device.name = clean_device_name(name)
    device.save(update_fields=["name"])
    return device
