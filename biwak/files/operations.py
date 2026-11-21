"""Changing messages, docs and files (specs/files.md, stage 2)

Creating them is in ``biwak.items.operations`` next to the other kinds.
Views, the API and the CLI call these functions; they record the events
and subscriptions like the rest.
"""

import datetime as dt

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from biwak.activity import mentions
from biwak.activity.models import Action
from biwak.activity.operations import record
from biwak.files import attachments
from biwak.items import operations as ops
from biwak.items.models import Doc, DocVersion, Message, Upload


_UNCHANGED = ops._UNCHANGED

# Saving makes a version when the last one is older than this, or by
# somebody else (decided 2026-11-20)
VERSION_WINDOW = dt.timedelta(minutes=10)
# A doc's lock expires this long after its last renewal
LOCK_TTL = dt.timedelta(minutes=5)


class DocLocked(Exception):
    """Somebody else is editing the doc"""

    def __init__(self, user):
        super().__init__(str(user))
        self.user = user


class DocConflict(Exception):
    """Somebody else saved a newer version since the form was opened"""

    def __init__(self, version):
        super().__init__(f"{version.created_by} saved a newer version")
        self.version = version


# Messages ---------------------------------------------------------------


@transaction.atomic
def update_message(
    item, *, actor, title=_UNCHANGED, content=_UNCHANGED, category=_UNCHANGED
):
    """Changes what's given; ``category`` is a ``MessageCategory`` or None"""
    message = Message.objects.select_for_update().get(item=item)
    previous = f"{item.title}\n\n{message.content}"
    edited = False
    if title is not _UNCHANGED and title != item.title:
        item.title = title
        item.updated_at = _now()
        item.save(update_fields=["title", "updated_at"])
        edited = True
    fields = []
    if content is not _UNCHANGED and content != message.content:
        message.content = content
        fields.append("content")
        attachments.link(item, content, actor=actor)
    if category is not _UNCHANGED and category != message.category:
        message.category = category
        fields.append("category")
    if fields:
        message.save(update_fields=fields)
    if edited or fields:
        event = record(
            actor=actor, action=Action.EDITED, project=item.project, item=item
        )
        mentions.update(
            item,
            f"{item.title}\n\n{message.content}",
            actor=actor,
            event=event,
            previous=previous,
        )
    return item


@transaction.atomic
def pin_message(item, *, actor):
    """Pins the message for everybody; staff only. Pinning a pinned
    message changes nothing."""
    if actor.is_client:
        raise PermissionDenied
    message = Message.objects.select_for_update().get(item=item)
    if message.pinned_at is not None:
        return False
    message.pinned_at = _now()
    message.save(update_fields=["pinned_at"])
    record(actor=actor, action=Action.PINNED, project=item.project, item=item)
    return True


@transaction.atomic
def unpin_message(item, *, actor):
    if actor.is_client:
        raise PermissionDenied
    message = Message.objects.select_for_update().get(item=item)
    if message.pinned_at is None:
        return False
    message.pinned_at = None
    message.save(update_fields=["pinned_at"])
    record(actor=actor, action=Action.UNPINNED, project=item.project, item=item)
    return True


# Docs: versions and locks -----------------------------------------------


def _now():
    return timezone.now()


def _locked(item):
    """The doc's row, locked for the transaction"""
    return (
        Doc.objects
        .select_for_update(of=("self",))
        .select_related("locked_by")
        .get(item=item)
    )


def lock_holder(doc, *, now=None):
    """Who is editing the doc now, or None (no lock, or it expired)"""
    if doc.locked_by_id is None or doc.locked_at is None:
        return None
    if doc.locked_at < (now or _now()) - LOCK_TTL:
        return None
    return doc.locked_by


@transaction.atomic
def lock_doc(item, user):
    """Takes or renews the lock (opening the edit form, then every
    minute); raises ``DocLocked`` while somebody else holds it"""
    doc = _locked(item)
    holder = lock_holder(doc)
    if holder is not None and holder != user:
        raise DocLocked(holder)
    doc.locked_by = user
    doc.locked_at = _now()
    doc.save(update_fields=["locked_by", "locked_at"])
    return doc


@transaction.atomic
def unlock_doc(item, user):
    """Gives up one's own lock"""
    Doc.objects.filter(item=item, locked_by=user).update(locked_by=None, locked_at=None)


def _save_version(doc, *, title, content, actor, force=False):
    """The doc's newest version equals its content: a save by the same
    person within ``VERSION_WINDOW`` updates it, anything else (or
    ``force``) starts a new one. Returns the version."""
    latest = doc.versions.first()
    if (
        force
        or latest is None
        or latest.created_by_id != actor.pk
        or latest.created_at < _now() - VERSION_WINDOW
    ):
        return DocVersion.objects.create(
            doc=doc, title=title, content=content, created_by=actor
        )
    # Not changed in place: somebody who opened the form on this version
    # compares primary keys when saving, so a changed text needs a new one
    # (keeping the window's start)
    created_at = latest.created_at
    latest.delete()
    return DocVersion.objects.create(
        doc=doc, title=title, content=content, created_by=actor, created_at=created_at
    )


@transaction.atomic
def update_doc(
    item,
    *,
    actor,
    title=_UNCHANGED,
    content=_UNCHANGED,
    new_version=False,
    base_version=None,
):
    """Saves the doc's title and content (what's given).

    A version is made when the last one is older than 10 minutes or by
    someone else, or when ``new_version`` asks for one. Raises
    ``DocLocked`` while somebody else is editing, and ``DocConflict`` when
    ``base_version`` (the newest version when the form was opened) isn't
    the newest anymore and somebody else made a newer one. Saving gives up
    one's lock."""
    doc = _locked(item)
    holder = lock_holder(doc)
    if holder is not None and holder != actor:
        raise DocLocked(holder)
    if base_version is not None:
        newer = (
            doc.versions
            .filter(pk__gt=base_version)
            .exclude(created_by=actor)
            .select_related("created_by")
            .first()
        )
        if newer is not None:
            raise DocConflict(newer)
    new_title = item.title if title is _UNCHANGED else title
    new_content = doc.content if content is _UNCHANGED else content
    changed = new_title != item.title or new_content != doc.content
    if changed:
        _write_doc(item, doc, new_title, new_content, actor=actor)
        _save_version(
            doc, title=new_title, content=new_content, actor=actor, force=new_version
        )
    if doc.locked_by_id == actor.pk:
        doc.locked_by = None
        doc.locked_at = None
        doc.save(update_fields=["locked_by", "locked_at"])
    return item


def _write_doc(item, doc, title, content, *, actor):
    # Only called with a change; a new text is a change of the doc too
    # ("latest docs and files" on the project page)
    previous = f"{item.title}\n\n{doc.content}"
    item.title = title
    item.updated_at = _now()
    item.save(update_fields=["title", "updated_at"])
    if content != doc.content:
        doc.content = content
        doc.save(update_fields=["content"])
        attachments.link(item, content, actor=actor)
    event = record(actor=actor, action=Action.EDITED, project=item.project, item=item)
    mentions.update(
        item, f"{title}\n\n{content}", actor=actor, event=event, previous=previous
    )


@transaction.atomic
def restore_doc_version(item, version, *, actor):
    """Makes an older version the doc's content again, saved as a new
    version, so nothing is lost"""
    doc = _locked(item)
    if version.doc_id != doc.pk:
        raise ValueError("The version belongs to another doc")
    holder = lock_holder(doc)
    if holder is not None and holder != actor:
        raise DocLocked(holder)
    _write_doc(item, doc, version.title, version.content, actor=actor)
    return _save_version(
        doc, title=version.title, content=version.content, actor=actor, force=True
    )


# Files ------------------------------------------------------------------


@attachments.cleans_up_files
@transaction.atomic
def replace_upload(item, file, *, actor):
    """Uploads a new version: the URL, the comments and the earlier
    versions stay. Raises ``attachments.UploadError`` over the limit."""
    upload = Upload.objects.select_for_update().get(item=item)
    version = ops.new_version(upload, file, uploaded_by=actor)
    item.updated_at = _now()
    item.save(update_fields=["updated_at"])
    record(
        actor=actor,
        action=Action.EDITED,
        project=item.project,
        item=item,
        version=version.name,
    )
    return version


@transaction.atomic
def update_upload(item, *, actor, title=_UNCHANGED, description=_UNCHANGED):
    upload = Upload.objects.select_for_update().get(item=item)
    previous = f"{item.title}\n\n{upload.description}"
    edited = False
    if title is not _UNCHANGED and title != item.title:
        item.title = title
        item.updated_at = _now()
        item.save(update_fields=["title", "updated_at"])
        edited = True
    if description is not _UNCHANGED and description != upload.description:
        upload.description = description
        upload.save(update_fields=["description"])
        attachments.link(item, description, actor=actor)
        edited = True
    if edited:
        event = record(
            actor=actor, action=Action.EDITED, project=item.project, item=item
        )
        mentions.update(
            item,
            f"{item.title}\n\n{upload.description}",
            actor=actor,
            event=event,
            previous=previous,
        )
    return item
