"""Files (specs/files.md): attachments (stage 1), the message board,
folders, docs and files (stage 2). The same operations as the web
interface, and the same visibility: everything through
``Item.objects.visible_to()``."""

import datetime as dt
from types import SimpleNamespace
from typing import Literal

from django.db.models import Prefetch, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.translation import gettext as _
from ninja import File, Form, Router, Schema, Status, UploadedFile
from ninja.errors import HttpError

from biwak.accounts.models import User
from biwak.activity.mentions import resolve as resolve_mentions
from biwak.api_conventions import (
    ItemOut,
    PersonOut,
    absolute,
    html,
    item_out,
    page_of,
    paginated,
    person_out,
)
from biwak.files import attachments, operations, queries
from biwak.files.library import (
    CONTAINED,
    breadcrumbs,
    contents,
    current_version,
    version_for,
)
from biwak.files.models import Attachment
from biwak.items import operations as ops
from biwak.items.api import item_for
from biwak.items.models import Kind, MessageCategory
from biwak.permissions import api_staff_only
from biwak.projects.api import project_for
from biwak.reactions.models import Reaction
from biwak.reactions.schemas import ReactionOut, reactions_out
from biwak.templatetags.biwak import excerpt


router = Router(tags=["files"])


class AttachmentOut(Schema):
    key: str
    name: str
    size: int
    content_type: str
    project_id: int
    item_id: int | None
    uploaded_by: PersonOut
    created_at: dt.datetime
    # The download on the web, for people
    url: str
    # The download with the API token (with a bucket a redirect to a
    # presigned URL valid 5 minutes)
    download_url: str
    # What to insert into a text
    markdown: str


def attachment_out(attachment):
    return {
        "key": attachment.key,
        "name": attachment.name,
        "size": attachment.size,
        "content_type": attachment.content_type,
        "project_id": attachment.project_id,
        "item_id": attachment.item_id,
        "uploaded_by": person_out(attachment.uploaded_by),
        "created_at": attachment.created_at,
        "url": absolute(attachment.get_absolute_url()),
        "download_url": absolute(
            reverse("api:attachment_download", kwargs={"key": attachment.key})
        ),
        "markdown": attachment.markdown,
    }


def attachment_for(request, key):
    """The attachment if the person sees it, else 404 (its item's
    visibility; unlinked ones only for their uploader)"""
    return get_object_or_404(
        Attachment.objects.visible_to(request.user).select_related("uploaded_by"),
        key=key,
    )


@router.post("projects/{project_id}/attachments/", response={201: AttachmentOut})
def attachment_upload(request, project_id: int, file: File[UploadedFile]):
    """Uploads a file (multipart, field ``file``, at most 100 MB); insert
    its ``markdown`` into a text. Saving the text links it to the item;
    until then only you see it, and it's deleted after a day."""
    project = project_for(request, project_id)
    try:
        attachment = attachments.upload(
            project=project, file=file, uploaded_by=request.user
        )
    except attachments.UploadError as exc:
        raise HttpError(413, str(exc)) from exc
    return Status(201, attachment_out(attachment))


@router.get("attachments/{key}/", response=AttachmentOut)
def attachment_detail(request, key: str):
    return attachment_out(attachment_for(request, key))


@router.get("attachments/{key}/download/", url_name="attachment_download")
def attachment_download(request, key: str):
    """The file, or a redirect to a presigned URL with a bucket"""
    return attachments.serve(attachment_for(request, key))


# Whom to notify, the same choice as the forms ---------------------------

Notify = Literal["everybody", "nobody"] | list[int]


def whom(project, notify):
    """``"everybody"``, ``"nobody"`` or the IDs of project members, as
    ``notify_people()`` takes them; 400 for anybody else"""
    if isinstance(notify, str):
        return notify
    people = list(
        User.objects.active().filter(pk__in=notify, memberships__project=project)
    )
    if len(people) != len(set(notify)):
        raise HttpError(400, _("Only members of the project can be notified."))
    return people


def notify_from_form(value):
    """The multipart endpoints take ``everybody``, ``nobody`` or
    comma-separated IDs"""
    if value in {"everybody", "nobody"}:
        return value
    try:
        return [int(part) for part in value.split(",") if part.strip()]
    except ValueError as exc:
        raise HttpError(
            400, _("notify is everybody, nobody or IDs separated by commas.")
        ) from exc


def parent_folder(request, project, parent_id):
    """The folder (a folder the person sees in the project) or None"""
    if parent_id is None:
        return None
    folder = item_for(request, parent_id, Kind.FOLDER)
    if folder.project_id != project.pk:
        raise HttpError(404, _("Not found."))
    return folder


def _staff_creates(request, kind):
    """Clients create to-dos, comments and messages, not folders, docs or
    files (specs/access.md); after the checks which give 404"""
    if not ops.can_create(request.user, kind):
        raise HttpError(403, _("Only staff create folders, docs and files."))


def clean_title(title):
    """The title without surrounding spaces; 400 if nothing is left"""
    title = (title or "").strip()
    if not title:
        raise HttpError(400, _("The title can't be empty."))
    return title


def visible_in(folder, switch):
    """Whether a new doc or file is visible to clients: in a folder it
    follows the folder, at the top level the switch (``create_doc()``)"""
    return folder.is_client_visible if folder else bool(switch)


def resolve_for_new(project, visible, text, *, author):
    """Resolves ``@ada@example.org`` and ``@Ada`` in the text of an item
    which doesn't exist yet, for those who will see it"""
    stand_in = SimpleNamespace(project=project, is_client_visible=bool(visible))
    return resolve_mentions(stand_in, text, author=author)


# Messages ---------------------------------------------------------------


class CategoryOut(Schema):
    id: int
    name: str
    emoji: str


def category_out(category):
    if category is None:
        return None
    return {"id": category.pk, "name": category.name, "emoji": category.emoji}


class MessageOut(ItemOut):
    content: str
    content_html: str
    checklist_done: int
    checklist_total: int
    # The first lines as plain text, like the board shows them
    excerpt: str
    category: CategoryOut | None
    pinned: bool
    pinned_at: dt.datetime | None
    comment_count: int
    reactions: list[ReactionOut]


def message_out(item, user):
    message = item.message
    return item_out(item) | {
        "content": message.content,
        "content_html": html(message.content, item),
        "checklist_done": message.checklist_done,
        "checklist_total": message.checklist_total,
        "excerpt": excerpt(message.content),
        "category": category_out(message.category),
        "pinned": message.pinned_at is not None,
        "pinned_at": message.pinned_at,
        "comment_count": item.comment_count,
        "reactions": reactions_out(item, None, user),
    }


def message_for(request, pk):
    return item_for(request, pk, Kind.MESSAGE)


def _reactions():
    """One query for the reactions of a page of messages"""
    return Prefetch("reactions", queryset=Reaction.objects.select_related("user"))


def _message(request, pk):
    """With the annotations of the board"""
    return get_object_or_404(
        queries
        .board(None, request.user)
        .filter(pk=pk)
        .select_related("project")
        .prefetch_related(_reactions()),
    )


@router.get("message-categories/", response=list[CategoryOut])
def category_list(request):
    """The categories of the installation, for ``category_id``"""
    return [category_out(c) for c in MessageCategory.objects.all()]


@router.get("projects/{project_id}/messages/", response=page_of(MessageOut))
def message_list(
    request, project_id: int, cursor: str | None = None, page_size: int | None = None
):
    """The message board: the latest pinned first, then the rest newest
    first"""
    project = project_for(request, project_id)
    messages = (
        queries
        .board(project, request.user)
        .annotate(
            pin_key=Coalesce(
                "message__pinned_at", Value(dt.datetime(1970, 1, 1, tzinfo=dt.UTC))
            )
        )
        .prefetch_related(_reactions())
    )
    return paginated(
        request,
        messages,
        lambda item: message_out(item, request.user),
        ordering=("-pin_key", "-created_at", "-pk"),
        cursor=cursor,
        page_size=page_size,
    )


class MessageIn(Schema):
    title: str
    content: str = ""
    category_id: int | None = None
    visible_to_clients: bool = False
    # everybody (the default), nobody or the IDs of members (notify_people())
    notify: Notify = "everybody"


def _category(category_id):
    if category_id is None:
        return None
    category = MessageCategory.objects.filter(pk=category_id).first()
    if category is None:
        raise HttpError(400, _("There is no such category."))
    return category


@router.post("projects/{project_id}/messages/", response={201: MessageOut})
def message_create(request, project_id: int, data: MessageIn):
    """Posts a message and tells whom ``notify`` says. Clients' messages
    are visible to clients. Mentions are written as ``[@Name](person:ID)``."""
    project = project_for(request, project_id)
    title = clean_title(data.title)
    visible = ops.message_visibility(request.user, data.visible_to_clients)
    item = ops.create_message(
        project=project,
        title=title,
        content=resolve_for_new(project, visible, data.content, author=request.user),
        category=_category(data.category_id),
        creator=request.user,
        visible=visible,
        whom=whom(project, data.notify),
    )
    return Status(201, message_out(_message(request, item.pk), request.user))


@router.get("messages/{message_id}/", response=MessageOut)
def message_detail(request, message_id: int):
    return message_out(_message(request, message_id), request.user)


class MessagePatch(Schema):
    title: str | None = None
    content: str | None = None
    # null removes the category
    category_id: int | None = None


@router.patch("messages/{message_id}/", response=MessageOut)
def message_update(request, message_id: int, data: MessagePatch):
    """Changes the fields given; clients only their own messages"""
    item = message_for(request, message_id)
    if not ops.can_change(request.user, item):
        raise HttpError(403, _("You can only change messages you created."))
    given = data.model_fields_set
    changes = {}
    if "title" in given:
        changes["title"] = clean_title(data.title)
    if "content" in given:
        changes["content"] = resolve_mentions(
            item, data.content or "", author=request.user
        )
    if "category_id" in given:
        changes["category"] = _category(data.category_id)
    operations.update_message(item, actor=request.user, **changes)
    return message_out(_message(request, message_id), request.user)


@router.put("messages/{message_id}/pin/", response=MessageOut)
def message_pin(request, message_id: int):
    """Pins the message for everybody, staff only; the event notifies
    nobody"""
    item = message_for(request, message_id)
    if request.user.is_client:
        raise HttpError(403, _("Only staff can pin messages."))
    operations.pin_message(item, actor=request.user)
    return message_out(_message(request, message_id), request.user)


@router.delete("messages/{message_id}/pin/", response=MessageOut)
def message_unpin(request, message_id: int):
    item = message_for(request, message_id)
    if request.user.is_client:
        raise HttpError(403, _("Only staff can pin messages."))
    operations.unpin_message(item, actor=request.user)
    return message_out(_message(request, message_id), request.user)


# Folders ----------------------------------------------------------------


class EntryOut(ItemOut):
    # Files only
    size: int | None = None
    content_type: str | None = None
    download_url: str | None = None


def entry_out(item):
    entry = item_out(item)
    if item.kind == Kind.FILE:
        version = current_version(item)
        entry |= {
            "size": version.size,
            "content_type": version.content_type,
            "download_url": absolute(
                reverse("api:file_download", kwargs={"file_id": item.pk})
            ),
        }
    return entry


class CrumbOut(Schema):
    id: int
    title: str


class FolderOut(Schema):
    # None for the root
    folder: ItemOut | None
    breadcrumbs: list[CrumbOut]
    entries: list[EntryOut]


@router.get("projects/{project_id}/files/", response=FolderOut)
def folder_contents(request, project_id: int, folder_id: int | None = None):
    """The root of the project's docs and files, or a folder: folders
    first, then docs and files by title"""
    project = project_for(request, project_id)
    folder = parent_folder(request, project, folder_id)
    rows = contents(request.user, project, folder).prefetch_related("upload__versions")
    return {
        "folder": item_out(folder) if folder else None,
        "breadcrumbs": [
            {"id": c.pk, "title": c.title}
            for c in breadcrumbs(folder) + ([folder] if folder else [])
        ],
        "entries": [entry_out(row) for row in rows],
    }


class FolderIn(Schema):
    title: str
    parent_id: int | None = None
    visible_to_clients: bool = False


@router.post("projects/{project_id}/folders/", response={201: ItemOut})
def folder_create(request, project_id: int, data: FolderIn):
    """Staff only (specs/access.md)"""
    project = project_for(request, project_id)
    folder = parent_folder(request, project, data.parent_id)
    _staff_creates(request, Kind.FOLDER)
    title = clean_title(data.title)
    item = ops.create_folder(
        project=project,
        title=title,
        creator=request.user,
        parent=folder,
        visible=data.visible_to_clients,
    )
    return Status(201, item_out(item))


class MoveIn(Schema):
    # null: the root
    parent_id: int | None = None


@router.post("items/{item_id}/move/", response=ItemOut)
def item_move(request, item_id: int, data: MoveIn):
    """Moves a folder, doc or file into a folder or to the root; the
    visibility follows the new place. Clients only move what they created,
    into folders they see."""
    item = item_for(request, item_id)
    if item.kind not in CONTAINED:
        raise HttpError(400, _("Only folders, docs and files can be moved."))
    if not ops.can_change(request.user, item):
        raise HttpError(403, _("You can only move what you created."))
    folder = parent_folder(request, item.project, data.parent_id)
    try:
        ops.move_item(item, parent=folder, actor=request.user)
    except ValueError as exc:
        raise HttpError(400, _("A folder can't be moved into itself.")) from exc
    return item_out(item_for(request, item_id))


# Docs -------------------------------------------------------------------


class DocOut(ItemOut):
    content: str
    content_html: str
    checklist_done: int
    checklist_total: int
    # The newest version, the ``base_version`` of the next save
    version_id: int
    # Nobody edits it until staff turn this off (specs/collaboration.md)
    read_only: bool
    reactions: list[ReactionOut]


def doc_out(item, user):
    doc = item.doc
    return item_out(item) | {
        "content": doc.content,
        "content_html": html(doc.content, item),
        "checklist_done": doc.checklist_done,
        "checklist_total": doc.checklist_total,
        "version_id": doc.versions.first().pk,
        "read_only": doc.read_only,
        "reactions": reactions_out(item, None, user),
    }


class DocIn(Schema):
    # Becomes the text's first line, a heading before ``content``
    title: str
    content: str = ""
    parent_id: int | None = None
    visible_to_clients: bool = False
    notify: Notify = "everybody"


@router.post("projects/{project_id}/docs/", response={201: DocOut})
def doc_create(request, project_id: int, data: DocIn):
    """Staff only (specs/access.md)"""
    project = project_for(request, project_id)
    folder = parent_folder(request, project, data.parent_id)
    _staff_creates(request, Kind.DOC)
    title = clean_title(data.title)
    item = ops.create_doc(
        project=project,
        title=title,
        content=resolve_for_new(
            project,
            visible_in(folder, data.visible_to_clients),
            data.content,
            author=request.user,
        ),
        creator=request.user,
        parent=folder,
        visible=data.visible_to_clients,
        whom=whom(project, data.notify),
    )
    return Status(201, doc_out(item_for(request, item.pk, Kind.DOC), request.user))


@router.get("docs/{doc_id}/", response=DocOut)
def doc_detail(request, doc_id: int):
    return doc_out(item_for(request, doc_id, Kind.DOC), request.user)


class DocPatch(Schema):
    # Refused alone (400): the title is the first line of ``content``;
    # next to ``content`` it is ignored
    title: str | None = None
    content: str | None = None
    # Make a version now, even within ten minutes of the last one
    new_version: bool = False
    # The ``version_id`` you edited; refused (409) if somebody else saved a
    # newer version since
    base_version: int | None = None
    # Staff only
    read_only: bool | None = None


def _changeable_doc(request, doc_id):
    item = item_for(request, doc_id, Kind.DOC)
    if not ops.can_change(request.user, item):
        raise HttpError(403, _("You can only change docs you created."))
    return item


@router.patch("docs/{doc_id}/", response=DocOut)
def doc_update(request, doc_id: int, data: DocPatch):
    """Saves the fields given, with the version rules of the web
    interface: a version when the last one is older than 10 minutes or by
    someone else, or ``new_version``. The content is applied as an edit of
    the text as it was last saved, so what people type in the doc meanwhile
    stays, and it shows up in their editors (specs/collaboration.md). 409
    when ``base_version`` was overtaken by somebody else's save and for
    read-only docs. Clients only change docs they created (403);
    ``read_only`` is for staff."""
    item = _changeable_doc(request, doc_id)
    given = data.model_fields_set
    read_only = data.read_only if "read_only" in given else None
    if read_only is not None and request.user.is_client:
        raise HttpError(403, _("Only staff make docs read-only."))
    if read_only is False:
        operations.set_read_only(item, read_only=False, actor=request.user)
    changes = {}
    if "title" in given and "content" not in given:
        raise HttpError(400, _("The title is the text's first line."))
    if "content" in given:
        changes["content"] = resolve_mentions(
            item, data.content or "", author=request.user
        )
    if changes or data.new_version:
        try:
            operations.update_doc(
                item,
                actor=request.user,
                new_version=data.new_version,
                base_version=data.base_version,
                **changes,
            )
        except operations.DocReadOnly as exc:
            raise HttpError(409, _("The doc is read-only.")) from exc
        except operations.DocConflict as exc:
            raise HttpError(
                409,
                _("%(name)s saved a newer version.")
                % {"name": exc.version.created_by.get_short_name()},
            ) from exc
    if read_only:
        operations.set_read_only(item, read_only=True, actor=request.user)
    return doc_out(item_for(request, doc_id, Kind.DOC), request.user)


class DocVersionOut(Schema):
    id: int
    title: str
    created_by: PersonOut
    created_at: dt.datetime
    is_current: bool


class DocVersionDetailOut(DocVersionOut):
    content: str
    content_html: str


def _staff_only(request):
    """Older versions can hold what was meant to be internal, also of docs
    clients see now (like the history): staff only"""
    api_staff_only(request, _("Only staff see the versions."))


def version_out(version, *, is_current):
    return {
        "id": version.pk,
        "title": version.title,
        "created_by": person_out(version.created_by),
        "created_at": version.created_at,
        "is_current": is_current,
    }


@router.get("docs/{doc_id}/versions/", response=list[DocVersionOut])
def doc_versions(request, doc_id: int):
    """Newest first, staff only"""
    item = item_for(request, doc_id, Kind.DOC)
    _staff_only(request)
    versions = list(item.doc.versions.select_related("created_by"))
    return [version_out(v, is_current=v.pk == versions[0].pk) for v in versions]


@router.get("docs/{doc_id}/versions/{version_id}/", response=DocVersionDetailOut)
def doc_version(request, doc_id: int, version_id: int):
    item = item_for(request, doc_id, Kind.DOC)
    _staff_only(request)
    version = get_object_or_404(
        item.doc.versions.select_related("created_by"), pk=version_id
    )
    _before, is_latest = queries.neighbours(item.doc.versions, version)
    return version_out(version, is_current=is_latest) | {
        "content": version.content,
        "content_html": html(version.content, item),
    }


@router.post("docs/{doc_id}/versions/{version_id}/restore/", response=DocOut)
def doc_version_restore(request, doc_id: int, version_id: int):
    """Saves the old content as a new version"""
    item = item_for(request, doc_id, Kind.DOC)
    _staff_only(request)
    version = get_object_or_404(item.doc.versions, pk=version_id)
    try:
        operations.restore_doc_version(item, version, actor=request.user)
    except operations.DocReadOnly as exc:
        raise HttpError(409, _("The doc is read-only.")) from exc
    return doc_out(item_for(request, doc_id, Kind.DOC), request.user)


# Files ------------------------------------------------------------------


class FileVersionOut(Schema):
    id: int
    name: str
    size: int
    content_type: str
    uploaded_by: PersonOut
    uploaded_at: dt.datetime
    is_current: bool
    download_url: str


class FileOut(ItemOut):
    description: str
    description_html: str
    checklist_done: int
    checklist_total: int
    # The current version
    name: str
    size: int
    content_type: str
    download_url: str
    # Newest first; clients get the current version only, older ones are
    # for staff
    versions: list[FileVersionOut]
    reactions: list[ReactionOut]


def _version_out(item, version, *, current):
    if version.pk == current:
        url = reverse("api:file_download", kwargs={"file_id": item.pk})
    else:
        url = reverse(
            "api:file_version_download",
            kwargs={"file_id": item.pk, "version_id": version.pk},
        )
    return {
        "id": version.pk,
        "name": version.name,
        "size": version.size,
        "content_type": version.content_type,
        "uploaded_by": person_out(version.uploaded_by),
        "uploaded_at": version.uploaded_at,
        "is_current": version.pk == current,
        "download_url": absolute(url),
    }


def file_out(item, user):
    upload = item.upload
    versions = list(upload.versions.select_related("uploaded_by"))
    current = versions[0]
    if user.is_client:
        versions = versions[:1]
    return item_out(item) | {
        "description": upload.description,
        "description_html": html(upload.description, item),
        "checklist_done": upload.checklist_done,
        "checklist_total": upload.checklist_total,
        "name": current.name,
        "size": current.size,
        "content_type": current.content_type,
        "download_url": absolute(
            reverse("api:file_download", kwargs={"file_id": item.pk})
        ),
        "versions": [_version_out(item, v, current=current.pk) for v in versions],
        "reactions": reactions_out(item, None, user),
    }


class FileIn(Schema):
    description: str = ""
    parent_id: int | None = None
    visible_to_clients: bool = False
    # everybody (the default), nobody or IDs separated by commas
    notify: str = "everybody"


@router.post("projects/{project_id}/files/", response={201: FileOut})
def file_create(request, project_id: int, file: File[UploadedFile], data: Form[FileIn]):
    """Uploads a file (multipart, field ``file``, at most 100 MB) into the
    root or a folder; its title is the file's name. Staff only
    (specs/access.md)."""
    project = project_for(request, project_id)
    folder = parent_folder(request, project, data.parent_id)
    _staff_creates(request, Kind.FILE)
    try:
        item = ops.create_upload(
            project=project,
            file=file,
            description=resolve_for_new(
                project,
                visible_in(folder, data.visible_to_clients),
                data.description,
                author=request.user,
            ),
            creator=request.user,
            parent=folder,
            visible=data.visible_to_clients,
            whom=whom(project, notify_from_form(data.notify)),
        )
    except attachments.UploadError as exc:
        raise HttpError(413, str(exc)) from exc
    return Status(201, file_out(item_for(request, item.pk, Kind.FILE), request.user))


@router.get("files/{file_id}/", response=FileOut)
def file_detail(request, file_id: int):
    return file_out(item_for(request, file_id, Kind.FILE), request.user)


class FilePatch(Schema):
    title: str | None = None
    description: str | None = None


@router.patch("files/{file_id}/", response=FileOut)
def file_update(request, file_id: int, data: FilePatch):
    """Renames the file or changes its description; clients only their
    own files"""
    item = item_for(request, file_id, Kind.FILE)
    if not ops.can_change(request.user, item):
        raise HttpError(403, _("You can only change files you uploaded."))
    given = data.model_fields_set
    changes = {}
    if "title" in given:
        changes["title"] = clean_title(data.title)
    if "description" in given:
        changes["description"] = resolve_mentions(
            item, data.description or "", author=request.user
        )
    operations.update_upload(item, actor=request.user, **changes)
    return file_out(item_for(request, file_id, Kind.FILE), request.user)


@router.post("files/{file_id}/versions/", response={201: FileOut})
def file_replace(request, file_id: int, file: File[UploadedFile]):
    """A new version: the URL, the comments and the earlier versions stay"""
    item = item_for(request, file_id, Kind.FILE)
    if not ops.can_change(request.user, item):
        raise HttpError(403, _("You can only change files you uploaded."))
    try:
        operations.replace_upload(item, file, actor=request.user)
    except attachments.UploadError as exc:
        raise HttpError(413, str(exc)) from exc
    return Status(201, file_out(item_for(request, file_id, Kind.FILE), request.user))


@router.get("files/{file_id}/versions/", response=list[FileVersionOut])
def file_versions(request, file_id: int):
    """Newest first, staff only"""
    item = item_for(request, file_id, Kind.FILE)
    _staff_only(request)
    versions = list(item.upload.versions.select_related("uploaded_by"))
    return [_version_out(item, v, current=versions[0].pk) for v in versions]


@router.get("files/{file_id}/download/", url_name="file_download")
def file_download(request, file_id: int):
    """The current version: the file, or a redirect to a presigned URL
    valid 5 minutes with a bucket"""
    item = item_for(request, file_id, Kind.FILE)
    return attachments.serve(version_for(request, item))


@router.get(
    "files/{file_id}/versions/{version_id}/download/",
    url_name="file_version_download",
)
def file_version_download(request, file_id: int, version_id: int):
    item = item_for(request, file_id, Kind.FILE)
    return attachments.serve(version_for(request, item, version_id, deny=_staff_only))
