"""Changing messages, docs and files (specs/files.md, stage 2)

Creating them is in ``biwak.items.operations`` next to the other kinds.
Views, the API and the CLI call these functions; they record the events
and subscriptions like the rest.
"""

import datetime as dt

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from biwak import checklists
from biwak.accounts.middleware import set_user_name
from biwak.activity import mentions
from biwak.activity.models import Action
from biwak.activity.operations import record
from biwak.collab import live
from biwak.files import attachments
from biwak.items import editing, operations as ops
from biwak.items.models import Doc, DocVersion, Message, Upload


_UNCHANGED = ops._UNCHANGED

# Saving makes a version when the last one is older than this, or by
# somebody else (decided 2026-11-20)
VERSION_WINDOW = dt.timedelta(minutes=10)


class DocReadOnly(Exception):
    """The doc is read-only: nobody edits it until staff turn that off"""


class DocConflict(Exception):
    """Somebody else saved a newer version since the form was opened"""

    def __init__(self, version):
        super().__init__(f"{version.created_by} saved a newer version")
        self.version = version


# Messages ---------------------------------------------------------------


@transaction.atomic
def update_message(
    item, *, actor, title=_UNCHANGED, content=_UNCHANGED, category=_UNCHANGED, base=None
):
    """Changes what's given; ``category`` is a ``MessageCategory`` or None.
    ``base``: see ``items.operations.update_todo()``."""
    message = Message.objects.select_for_update().get(item=item)
    editing.check_base(item, base, actor=actor)
    editing.stop(item, actor)
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


# Docs: versions, edited live ---------------------------------------------


def _now():
    return timezone.now()


def _locked(item):
    """The doc's row, locked for the transaction"""
    return Doc.objects.select_for_update(of=("self",)).get(item=item)


def _save_version(doc, *, title, content, authors, force=False):
    """The doc's newest version equals its content: a save by one of its
    authors within ``VERSION_WINDOW`` of its start updates it (and keeps
    its author), anything else (or ``force``) starts a new one by the first
    author. Returns the version."""
    latest = doc.versions.first()
    if (
        force
        or latest is None
        or latest.created_by_id not in {a.pk for a in authors}
        or latest.created_at < _now() - VERSION_WINDOW
    ):
        return DocVersion.objects.create(
            doc=doc, title=title, content=content, created_by=authors[0]
        )
    # Not changed in place: somebody who opened the doc on this version
    # compares primary keys when saving, so a changed text needs a new one
    # (keeping the window's start)
    created_by, created_at = latest.created_by, latest.created_at
    latest.delete()
    return DocVersion.objects.create(
        doc=doc,
        title=title,
        content=content,
        created_by=created_by,
        created_at=created_at,
    )


def _save(item, doc, *, title=None, actor=None, new_version=False):
    """Merges what was typed live (and edits through ``live.apply_text()``)
    into ``Doc.content``; ``title`` renames the doc. One ``edited`` event
    per person and editing session (merging into their last one), a
    version by the version rules. Returns whether anything changed."""
    content, authors, typed = live.merge(doc)
    if actor is not None and actor not in authors:
        authors.append(actor)
    renamed = title is not None and title != item.title
    if not authors or not (renamed or content != doc.content or new_version):
        return False
    # The text before: mentions in it were looked at when they were written
    previous = f"{item.title}\n\n{doc.content}"
    if renamed:
        item.title = title
    # A new text is a change of the doc too ("latest docs and files" on the
    # project page)
    item.updated_at = _now()
    item.save(update_fields=["title", "updated_at"])
    if content != doc.content:
        doc.content = content
        doc.save(update_fields=["content"])
        for author in authors:
            attachments.link(item, content, actor=author)
    events = [
        record(actor=author, action=Action.EDITED, project=item.project, item=item)
        for author in authors
    ]
    # Mentions to who typed them, the rest (a title, an API edit) to the
    # first author
    by_author = dict(zip(authors, events, strict=True))
    mentions.update(
        item,
        f"{item.title}\n\n{content}",
        actor=authors[0],
        event=events[0],
        previous=previous,
        credit={pk: (author, by_author[author]) for pk, author in typed.items()},
    )
    _save_version(
        doc, title=item.title, content=content, authors=authors, force=new_version
    )
    return True


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
    """Saves the doc's title and content (what's given): the content as an
    edit of the text the API saw last, merged with what people type live
    meanwhile, and sent to their editors.

    A version is made when the last one is older than 10 minutes or by
    someone else, or when ``new_version`` asks for one. Raises
    ``DocReadOnly`` for read-only docs, and ``DocConflict`` when
    ``base_version`` (the newest version when the text was read) isn't the
    newest anymore and somebody else made a newer one."""
    doc = _locked(item)
    if doc.read_only:
        raise DocReadOnly
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
    changed = content is not _UNCHANGED and live.apply_text(doc, content, user=actor)
    _save(
        item,
        doc,
        title=None if title is _UNCHANGED else title,
        actor=actor if changed or new_version or title is not _UNCHANGED else None,
        new_version=new_version,
    )
    return item


@transaction.atomic
def tick_doc(item, *, actor, index, version, checked=None):
    """Toggles checkbox ``index`` of the doc's text as an edit of the live
    text (the open editors' Yjs state, what's typed and not saved yet
    included), sent to the editors like an API edit: it changes the one box
    and nothing else (specs/editor.md, "Docs: ticks never wait").
    ``version`` is the hash of the text the page showed: the stored one
    (``Doc.content``, which follows the typing after a few seconds: its box
    is ticked in the state it came from, and the typing since merges
    around it) or the live one (as the editors have it). ``ChecklistConflict``
    if it's neither. Returns the new text."""
    doc = _locked(item)
    if doc.read_only:
        raise DocReadOnly
    if checklists.text_hash(doc.content) == version:
        changed = live.apply_text(
            doc, checklists.tick(doc.content, index, checked), user=actor
        )
    elif checklists.text_hash(current := live.live_text(doc)) == version:
        changed = live.apply_live_text(
            doc, checklists.tick(current, index, checked), user=actor
        )
    else:
        raise ops.ChecklistConflict(*editing.last_change(item))
    _save(item, doc, actor=actor if changed else None)
    return doc.content


@transaction.atomic
def save_live(pk, user=None):
    """Saves what was typed live (``collab.consumers``, after a pause and
    when the editor leaves); ``user`` is who the audit log records"""
    if user is not None:
        set_user_name(user)
    doc = (
        Doc.objects
        .select_for_update(of=("self",))
        .select_related("item")
        .filter(pk=pk)
        .first()
    )
    if doc is None:
        return False
    return _save(doc.item, doc)


def save_pending():
    """Saves what was typed but not saved, e.g. when the server stopped
    while somebody was typing (``fairy_tasks``)"""
    return sum(save_live(doc.pk) for doc in live.pending())


@transaction.atomic
def save_version(item, *, actor):
    """ "Save as a version": what's typed so far as a version of its own"""
    doc = _locked(item)
    return _save(item, doc, actor=actor, new_version=True)


@transaction.atomic
def restore_doc_version(item, version, *, actor):
    """Makes an older version the doc's content again, saved as a new
    version, so nothing is lost; in the open editors too"""
    doc = _locked(item)
    if version.doc_id != doc.pk:
        raise ValueError("The version belongs to another doc")
    if doc.read_only:
        raise DocReadOnly
    live.apply_text(doc, version.content, user=actor)
    _save(item, doc, title=version.title, actor=actor, new_version=True)
    return doc.versions.first()


@transaction.atomic
def set_read_only(item, *, read_only, actor):
    """Staff make a doc read-only for everybody, or editable again; the
    open editors follow"""
    if actor.is_client:
        raise PermissionDenied
    doc = _locked(item)
    if doc.read_only == read_only:
        return False
    doc.read_only = read_only
    doc.save(update_fields=["read_only"])
    live.check_access(doc=item.pk)
    return True


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
def update_upload(item, *, actor, title=_UNCHANGED, description=_UNCHANGED, base=None):
    upload = Upload.objects.select_for_update().get(item=item)
    editing.check_base(item, base, actor=actor)
    editing.stop(item, actor)
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
