"""Bookmarks and links (specs/feed.md). Staff change links, everybody
bookmarks what they see."""

import datetime as dt

from django.db.models import F
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _
from ninja import Router, Schema, Status
from ninja.errors import HttpError

from biwak.api_conventions import ItemOut, PersonOut, item_out, person_out
from biwak.bookmarks import operations as ops
from biwak.bookmarks.models import Bookmark, Link
from biwak.items.api import item_for
from biwak.permissions import api_staff_only
from biwak.projects.api import ProjectOut, project_for, project_out


router = Router(tags=["bookmarks"])


# Bookmarks ------------------------------------------------------------------


class BookmarkOut(Schema):
    id: int
    created_at: dt.datetime
    item: ItemOut | None
    project: ProjectOut | None


@router.get("bookmarks/", response=list[BookmarkOut])
def bookmark_list(request):
    """The person's own bookmarks of what they can see, newest first"""
    found = Bookmark.objects.visible_to(request.user).select_related(
        "item", "item__project", "item__creator", "item__answer", "project"
    )
    return [
        {
            "id": b.pk,
            "created_at": b.created_at,
            "item": item_out(b.item) if b.item else None,
            "project": project_out(b.project, request.user) if b.project else None,
        }
        for b in found
    ]


class BookmarkedOut(Schema):
    bookmarked: bool


@router.put("items/{item_id}/bookmark/", response=BookmarkedOut)
def item_bookmark_add(request, item_id: int):
    ops.add_bookmark(request.user, item=item_for(request, item_id))
    return {"bookmarked": True}


@router.delete("items/{item_id}/bookmark/", response=BookmarkedOut)
def item_bookmark_remove(request, item_id: int):
    ops.remove_bookmark(request.user, item=item_for(request, item_id))
    return {"bookmarked": False}


@router.put("projects/{project_id}/bookmark/", response=BookmarkedOut)
def project_bookmark_add(request, project_id: int):
    ops.add_bookmark(request.user, project=project_for(request, project_id))
    return {"bookmarked": True}


@router.delete("projects/{project_id}/bookmark/", response=BookmarkedOut)
def project_bookmark_remove(request, project_id: int):
    ops.remove_bookmark(request.user, project=project_for(request, project_id))
    return {"bookmarked": False}


# Links ----------------------------------------------------------------------


class LinkOut(Schema):
    id: int
    project_id: int
    item_id: int | None
    url: str
    title: str
    kind: str
    position: int
    # What clients see: the link's switch and the item's visibility
    visible_to_clients: bool
    # The link's own switch (off by default, also on visible items)
    switch: bool
    created_by: PersonOut
    created_at: dt.datetime


def link_out(link):
    return {
        "id": link.pk,
        "project_id": link.project_id,
        "item_id": link.item_id,
        "url": link.url,
        "title": link.title,
        "kind": link.kind,
        "position": link.position,
        "visible_to_clients": link.visible_to_clients
        and (link.item is None or link.item.is_client_visible),
        "switch": link.visible_to_clients,
        "created_by": person_out(link.created_by),
        "created_at": link.created_at,
    }


def _links(request):
    return Link.objects.visible_to(request.user).select_related(
        "item", "created_by", "project"
    )


def _staff_only(request):
    api_staff_only(request, _("Only staff change links."))


@router.get("projects/{project_id}/links/", response=list[LinkOut])
def project_links(request, project_id: int):
    """All the links of the project in order, then those on items"""
    project = project_for(request, project_id)
    found = _links(request).filter(project=project)
    found = found.order_by(F("item_id").asc(nulls_first=True), "position", "pk")
    return [link_out(link) for link in found]


@router.get("items/{item_id}/links/", response=list[LinkOut])
def item_links(request, item_id: int):
    item = item_for(request, item_id)
    return [link_out(link) for link in _links(request).filter(item=item)]


class LinkIn(Schema):
    url: str
    title: str = ""
    visible_to_clients: bool = False


def _create(request, data, *, project, item=None):
    _staff_only(request)
    link = ops.add_link(
        project=project,
        item=item,
        url=data.url,
        title=data.title,
        visible=data.visible_to_clients,
        created_by=request.user,
    )
    return Status(201, link_out(link))


@router.post("projects/{project_id}/links/", response={201: LinkOut})
def project_link_create(request, project_id: int, data: LinkIn):
    return _create(request, data, project=project_for(request, project_id))


@router.post("items/{item_id}/links/", response={201: LinkOut})
def item_link_create(request, item_id: int, data: LinkIn):
    item = item_for(request, item_id)
    return _create(request, data, project=item.project, item=item)


def _link_for(request, link_id):
    return get_object_or_404(_links(request), pk=link_id)


class LinkPatch(Schema):
    url: str | None = None
    title: str | None = None
    visible_to_clients: bool | None = None


@router.patch("links/{link_id}/", response=LinkOut)
def link_update(request, link_id: int, data: LinkPatch):
    link = _link_for(request, link_id)
    _staff_only(request)
    ops.update_link(
        link, url=data.url, title=data.title, visible=data.visible_to_clients
    )
    return link_out(link)


@router.delete("links/{link_id}/", response=LinkOut)
def link_delete(request, link_id: int):
    """Returns the deleted link"""
    link = _link_for(request, link_id)
    _staff_only(request)
    data = link_out(link)
    ops.delete_link(link)
    return data


class LinkOrderIn(Schema):
    links: list[int]


def _order(request, data, *, project, item=None):
    _staff_only(request)
    try:
        ordered = ops.reorder_links(
            data.links, user=request.user, project=project, item=item
        )
    except ValueError as exc:
        raise HttpError(
            400, _("Send the IDs of all the links, in the new order.")
        ) from exc
    return [link_out(link) for link in ordered]


@router.put("projects/{project_id}/links/order/", response=list[LinkOut])
def project_link_order(request, project_id: int, data: LinkOrderIn):
    """The project's own links (not those on items) in the given order"""
    return _order(request, data, project=project_for(request, project_id))


@router.put("items/{item_id}/links/order/", response=list[LinkOut])
def item_link_order(request, item_id: int, data: LinkOrderIn):
    item = item_for(request, item_id)
    return _order(request, data, project=item.project, item=item)
