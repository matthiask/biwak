"""Forwarded mails (specs/forwarding.md): your own, filed as a message or
a to-do, or deleted, like on the "Forwarded" page. Clients get 403,
somebody else's forwarded mail is a 404, and everything is a 404 while
forwarding is off."""

import datetime as dt
from typing import Literal

from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _
from ninja import Router, Schema, Status
from ninja.errors import HttpError

from biwak.api_conventions import ItemOut, Title, absolute, item_out
from biwak.forwarding import operations as ops
from biwak.forwarding.views import text_html
from biwak.items.api import item_for
from biwak.items.models import Group, Kind, MessageCategory
from biwak.permissions import api_staff_only
from biwak.projects.api import project_for


router = Router(tags=["forwarded mails"])


class SenderOut(Schema):
    name: str
    email: str


class ForwardedFileOut(Schema):
    name: str
    size: int
    content_type: str
    url: str


class ForwardedOut(Schema):
    id: int
    subject: str
    sender: SenderOut
    sent_on: dt.date | None
    to: str
    cc: str
    received_at: dt.datetime
    text: str
    text_html: str
    files: list[ForwardedFileOut]


def forwarded_out(mail):
    return {
        "id": mail.pk,
        "subject": mail.subject,
        "sender": {"name": mail.sender_name, "email": mail.sender_email},
        "sent_on": mail.sent_on,
        "to": mail.to,
        "cc": mail.cc,
        "received_at": mail.received_at,
        "text": mail.text,
        "text_html": text_html(mail, absolute=True),
        "files": [
            {
                "name": file.name,
                "size": file.size,
                "content_type": file.content_type,
                "url": absolute(file.get_absolute_url()),
            }
            for file in mail.files.all()
        ],
    }


def _forwarded(request):
    if not ops.enabled():
        raise Http404
    api_staff_only(request, _("Only staff forward mails."))
    return ops.forwarded_for(request.user).prefetch_related("files")


@router.get("forwarded/", response=list[ForwardedOut])
def forwarded_list(request):
    """Your forwarded mails, newest first (kept 30 days unless filed);
    the text references its files as ``forwarded:KEY`` until filed"""
    return [forwarded_out(mail) for mail in _forwarded(request)]


class FileIn(Schema):
    kind: Literal["message", "todo"]
    # The forwarded mail's subject when left out
    title: Title | None = None
    # A message: the project and optionally a category
    project_id: int | None = None
    category_id: int | None = None
    # A to-do: the list and optionally one of its groups
    list_id: int | None = None
    group_id: int | None = None


@router.post("forwarded/{forwarded_id}/file/", response={201: ItemOut})
def forwarded_file(request, forwarded_id: int, data: FileIn):
    """Files the forwarded mail as an internal message (``project_id``,
    ``category_id``) or as a to-do in a list (``list_id``, ``group_id``;
    visible to clients when the list is), with a line about the original,
    its text and files; the forwarded mail is gone afterwards"""
    mail = get_object_or_404(_forwarded(request), pk=forwarded_id)
    title = data.title or mail.subject
    if not title:
        raise HttpError(400, _("The title can't be empty."))
    if data.kind == "message":
        if data.project_id is None:
            raise HttpError(400, _("Give the project."))
        project = project_for(request, data.project_id)
        if not ops.message_projects(request.user).filter(pk=project.pk).exists():
            raise HttpError(400, _("The project is archived."))
        category = None
        if data.category_id is not None:
            category = MessageCategory.objects.filter(pk=data.category_id).first()
            if category is None:
                raise HttpError(400, _("There is no such category."))
        item = ops.file_as_message(
            mail, project=project, title=title, category=category, actor=request.user
        )
    else:
        if data.list_id is None:
            raise HttpError(400, _("Give the list."))
        todolist = item_for(request, data.list_id, Kind.LIST)
        if not ops.todo_lists(request.user).filter(pk=todolist.pk).exists():
            raise HttpError(400, _("Forwarded mails are filed into active lists only."))
        group = None
        if data.group_id is not None:
            group = Group.objects.filter(
                pk=data.group_id, todolist=todolist.todolist
            ).first()
            if group is None:
                raise HttpError(400, _("The group isn't in this list."))
        item = ops.file_as_todo(
            mail, todolist=todolist, group=group, title=title, actor=request.user
        )
    return Status(201, item_out(item))


@router.delete("forwarded/{forwarded_id}/", response={204: None})
def forwarded_delete(request, forwarded_id: int):
    """Deletes the forwarded mail with its files; it can't be restored"""
    mail = get_object_or_404(_forwarded(request), pk=forwarded_id)
    ops.delete(mail, actor=request.user)
    return Status(204, None)
