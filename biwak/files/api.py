"""Attachments (specs/files.md, stage 1): uploading files to insert into
texts, their metadata and downloads"""

import datetime as dt

from django.shortcuts import get_object_or_404
from django.urls import reverse
from ninja import File, Router, Schema, Status, UploadedFile
from ninja.errors import HttpError

from biwak.api_conventions import PersonOut, absolute, person_out
from biwak.files import attachments
from biwak.files.models import Attachment
from biwak.projects.api import project_for


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
