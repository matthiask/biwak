"""Changing messages, docs and files (specs/files.md, stage 2)

Creating them is in ``biwak.items.operations`` next to the other kinds.
Views, the API and the CLI call these functions; they record the events
and subscriptions like the rest.
"""

import datetime as dt

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from biwak.accounts.middleware import set_user_name, user_name_kept
from biwak.accounts.models import Color
from biwak.activity import mentions
from biwak.activity.models import Action
from biwak.activity.notify import told_by_default
from biwak.activity.operations import (
    read_by_acting,
    record,
    share,
    subscribable_people,
)
from biwak.collab import live
from biwak.files import attachments
from biwak.files.titles import doc_title
from biwak.items import editing, operations as ops
from biwak.items.models import (
    Doc,
    DocVersion,
    Folder,
    Item,
    Kind,
    Message,
    Status,
    Upload,
)
from biwak.projects.models import FilesOrdering, MessagesOrder, Project
from biwak.richtext import checklists


_UNCHANGED = ops._UNCHANGED

# Saving makes a version when the last one is older than this, or by
# somebody else (decided 2026-11-20)
VERSION_WINDOW = dt.timedelta(minutes=10)

# A doc begun as a draft whose creator never answered "Tell people about
# it?" tells those who want to hear once it had no change for this long
# (decided 2026-11-21)
TELL_AFTER = dt.timedelta(hours=1)


class DocReadOnly(Exception):
    """The doc is read-only: nobody edits it until staff turn that off"""


class DocConflict(Exception):
    """Somebody else saved a newer version since the form was opened:
    ``author`` typed in ``version``"""

    def __init__(self, version, author=None):
        self.version = version
        self.author = author or version.created_by
        super().__init__(f"{self.author} saved a newer version")


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
    edited = []
    if title is not _UNCHANGED and title != item.title:
        item.title = title
        item.updated_at = _now()
        item.save(update_fields=["title", "updated_at"])
        edited.append("title")
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
        # What changed, for the timeline (specs/timeline.md)
        event = record(
            actor=actor,
            action=Action.EDITED,
            project=item.project,
            item=item,
            fields=[*edited, *fields],
        )
        mentions.update(
            item,
            f"{item.title}\n\n{message.content}",
            actor=actor,
            event=event,
            previous=previous,
        )
        read_by_acting(actor, item)
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
    author. The other authors are its ``coauthors``. Returns the
    version."""
    latest = doc.versions.first()
    if (
        force
        or latest is None
        or latest.created_by_id not in {a.pk for a in authors}
        or latest.created_at < _now() - VERSION_WINDOW
    ):
        version = DocVersion.objects.create(
            doc=doc, title=title, content=content, created_by=authors[0]
        )
        version.coauthors.set(authors[1:])
        return version
    # Not changed in place: somebody who opened the doc on this version
    # compares primary keys when saving, so a changed text needs a new one
    # (keeping the window's start)
    created_by, created_at = latest.created_by, latest.created_at
    coauthors = {*latest.coauthors.all(), *authors} - {created_by}
    latest.delete()
    version = DocVersion.objects.create(
        doc=doc,
        title=title,
        content=content,
        created_by=created_by,
        created_at=created_at,
    )
    version.coauthors.set(coauthors)
    return version


def _save(item, doc, *, actor=None, new_version=False, name_authors=False):
    """Merges what was typed live (and edits through ``live.apply_text()``)
    into ``Doc.content``; a new text sets the doc's title, its first line
    (specs/doc-titles.md). One ``edited`` event
    per person and editing session (merging into their last one), a
    version by the version rules. Returns whether anything changed.
    ``name_authors``: the audit log names who typed it (one person, or
    several short names)."""
    content, authors, typed, typists = live.merge(doc)
    if name_authors and authors:
        set_user_name(
            authors[0]
            if len(authors) == 1
            else ", ".join(a.get_short_name() for a in authors)
        )
    if actor is not None and actor not in authors:
        authors.append(actor)
    published = False
    if item.is_draft:
        if ops.is_blank(content):
            # Still nobody's business: the text only, no event, no version
            if content != doc.content:
                doc.content = content
                doc.save(update_fields=["content"])
            return False
        # The doc exists from its first save with text (specs/files.md,
        # "Docs"): created now, telling nobody but who it mentions
        published = True
        item.is_draft = False
        item.created_at = _now()
        item.save(update_fields=["is_draft", "created_at"])
    title = doc_title(content) if content != doc.content else item.title
    renamed = title != item.title
    if not authors or not (renamed or content != doc.content or new_version):
        return False
    changed = renamed or content != doc.content
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
        # Also the files of those whose typing stays without them being
        # authors (they lost access, others built on it)
        for person in {p.pk: p for p in [*authors, *typists]}.values():
            attachments.link(item, content, actor=person)
    if published:
        # Only its creator typed in it; quiet: the subscribers of its
        # folder aren't told, the creator tells people at "Done"
        events = [
            record(
                actor=author,
                action=Action.CREATED,
                project=item.project,
                item=item,
                quiet=True,
            )
            for author in authors
        ]
    else:
        # What changed, for the timeline (specs/timeline.md): nothing for
        # "Save as a version" alone
        fields = [
            *(["title"] if renamed else []),
            *(["content"] if changed else []),
        ]
        events = [
            record(
                actor=author,
                action=Action.EDITED,
                project=item.project,
                item=item,
                fields=fields,
            )
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
    if changed:
        # Whoever typed or saved it edited the doc (specs/lantern.md)
        for author in authors:
            read_by_acting(author, item)
    return True


@transaction.atomic
def update_doc(
    item,
    *,
    actor,
    content=_UNCHANGED,
    new_version=False,
    base_version=None,
):
    """Saves the doc's content (when given; its first line is the title):
    the content as an
    edit of the text the API saw last, merged with what people type live
    meanwhile, and sent to their editors.

    A version is made when the last one is older than 10 minutes or by
    someone else, or when ``new_version`` asks for one. Raises
    ``DocReadOnly`` for read-only docs, and ``DocConflict`` when
    ``base_version`` (the newest version when the text was read) isn't the
    newest anymore and somebody else made or typed in a newer one."""
    doc = _locked(item)
    if doc.read_only:
        raise DocReadOnly
    if base_version is not None:
        # Also a version of the actor's with somebody else's typing merged
        # into it
        for newer in (
            doc.versions
            .filter(pk__gt=base_version)
            .select_related("created_by")
            .prefetch_related("coauthors")
        ):
            others = [
                user
                for user in [newer.created_by, *newer.coauthors.all()]
                if user != actor
            ]
            if others:
                raise DocConflict(newer, others[0])
    changed = content is not _UNCHANGED and live.apply_text(doc, content, user=actor)
    _save(
        item,
        doc,
        actor=actor if changed or new_version else None,
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
def save_live(pk):
    """Saves what was typed live (``collab.consumers``, after a pause and
    when the editor leaves, the doc's pages, ``save_pending()``). The audit
    log names who typed it, not who caused the save (decided 2026-11-28),
    and the name set before comes back afterwards."""
    doc = (
        Doc.objects
        .select_for_update(of=("self",))
        .select_related("item")
        .filter(pk=pk)
        .first()
    )
    if doc is None:
        return False
    with user_name_kept():
        return _save(doc.item, doc, name_authors=True)


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
    _save(item, doc, actor=actor, new_version=True)
    return doc.versions.first()


def default_told(item, user):
    """Those the doc tells by default (``notify.told_by_default()``) who
    aren't subscribed yet (people mentioned in its first text were told
    then) and whom ``user`` may subscribe"""
    told = told_by_default(
        item.project, item.parent, visible=item.is_client_visible, actor=user
    )
    allowed = set(
        subscribable_people(item, user)
        .exclude(subscriptions__item=item)
        .filter(pk__in=[u.pk for u in told])
        .values_list("pk", flat=True)
    )
    return [u for u in told if u.pk in allowed]


@transaction.atomic
def tell(item, *, actor, also=(), note=""):
    """ "Tell people about it?" answered, once (specs/files.md, "Docs"): a
    ``shared`` event to those told by default (``default_told()``) and
    ``also``, with the note; nothing when there's nobody. Never asked
    again. The doc's row is locked and checked, so the creator's answer
    and ``tell_unanswered()`` can't both tell; returns whether this call
    did."""
    doc = (
        Doc.objects
        .select_for_update(of=("self",))
        .filter(pk=item.pk, tell_pending=True)
        .first()
    )
    if doc is None:
        return False
    people = [*default_told(item, actor), *also]
    if people:
        share(item, people, actor=actor, notify=True, note=note)
    doc.tell_pending = False
    doc.save(update_fields=["tell_pending"])
    return True


def tell_unanswered(*, now=None):
    """Docs begun as drafts whose creator never answered "Tell people about
    it?" (no first "Done") tell those who want to hear once they had no
    change for ``TELL_AFTER``, as "No one else" would, with the creator as
    the actor; the question isn't asked any more (decided 2026-11-21).
    ``send_mails`` runs it every minute. Each doc in a transaction of its
    own with its row locked (``skip_locked``: a run at the same time or
    the creator answering has it) and checked again; one with typing not
    merged yet (``LiveUpdate`` rows) waits for the next run. Returns how
    many docs told."""
    from biwak.collab.models import LiveUpdate

    cutoff = (now or timezone.now()) - TELL_AFTER
    unanswered = Item.objects.filter(
        kind=Kind.DOC,
        is_draft=False,
        doc__tell_pending=True,
        updated_at__lt=cutoff,
    ).exclude(status=Status.TRASHED)
    count = 0
    for pk in unanswered.order_by("pk").values_list("pk", flat=True):
        with transaction.atomic():
            doc = (
                Doc.objects
                .select_for_update(of=("self",), skip_locked=True)
                .filter(item__in=unanswered.filter(pk=pk))
                .select_related("item__creator")
                .first()
            )
            if doc is None or LiveUpdate.objects.filter(doc_id=pk).exists():
                continue
            count += tell(doc.item, actor=doc.item.creator)
    return count


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


# Folders ----------------------------------------------------------------


@transaction.atomic
def update_folder(item, *, actor, title=_UNCHANGED, color=_UNCHANGED):
    """Renames a folder or sets its color: an edit like any other. A
    color alone is just a setting (like the order): no event."""
    folder = item.folder
    if color is not _UNCHANGED and color != folder.color:
        if color:
            Color(color)  # ValueError for a name outside the palette
        folder.color = color
        folder.save(update_fields=["color"])
    if title is _UNCHANGED or title == item.title:
        return item
    item.title = title
    item.updated_at = _now()
    item.save(update_fields=["title", "updated_at"])
    record(actor=actor, action=Action.EDITED, project=item.project, item=item)
    return item


@transaction.atomic
def move_items(items, *, parent, actor):
    """Moves several folders, docs and files (dragged, or the selection's
    "Move to…") with ``move_item()``; those already there stay. All or
    none: a folder into itself raises ``ValueError``."""
    for item in items:
        if item.parent_id != (parent.pk if parent else None):
            ops.move_item(item, parent=parent, actor=actor)


@transaction.atomic
def trash_items(items, *, actor):
    """The selection's "Move to trash" (``trash()`` each; what's inside a
    trashed folder follows it)"""
    for item in items:
        item.refresh_from_db(fields=["status"])
        if item.status != Status.TRASHED:
            ops.trash(item, actor=actor)


def set_ordering(target, ordering, *, actor):
    """The order of a folder's contents (``target`` its item) or of the
    project's top level (``target`` the project), for everybody; staff
    only. Just a setting: no event (specs/files.md, "Folders")."""
    if actor.is_client:
        raise PermissionDenied
    ordering = FilesOrdering(ordering)
    if isinstance(target, Project):
        Project.objects.filter(pk=target.pk).update(files_ordering=ordering)
        target.files_ordering = ordering
    else:
        Folder.objects.filter(pk=target.pk).update(ordering=ordering)
        target.folder.ordering = ordering
    return ordering


def set_messages_order(project, order, *, actor):
    """The order of the project's message board, for everybody; staff
    only. Just a setting, like ``set_ordering()``: no event."""
    if actor.is_client:
        raise PermissionDenied
    order = MessagesOrder(order)
    Project.objects.filter(pk=project.pk).update(messages_order=order)
    project.messages_order = order
    return order


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
        fields=["file"],
    )
    read_by_acting(actor, item)
    return version


@transaction.atomic
def update_upload(item, *, actor, title=_UNCHANGED, description=_UNCHANGED, base=None):
    upload = Upload.objects.select_for_update().get(item=item)
    editing.check_base(item, base, actor=actor)
    editing.stop(item, actor)
    previous = f"{item.title}\n\n{upload.description}"
    edited = []
    if title is not _UNCHANGED and title != item.title:
        item.title = title
        item.updated_at = _now()
        item.save(update_fields=["title", "updated_at"])
        edited.append("title")
    if description is not _UNCHANGED and description != upload.description:
        upload.description = description
        upload.save(update_fields=["description"])
        attachments.link(item, description, actor=actor)
        edited.append("description")
    if edited:
        # What changed, for the timeline (specs/timeline.md)
        event = record(
            actor=actor,
            action=Action.EDITED,
            project=item.project,
            item=item,
            fields=edited,
        )
        mentions.update(
            item,
            f"{item.title}\n\n{upload.description}",
            actor=actor,
            event=event,
            previous=previous,
        )
        read_by_acting(actor, item)
    return item
