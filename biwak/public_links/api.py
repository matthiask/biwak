"""Public links (specs/public-links.md): staff create, show and stop the
link of an item they see, and list the live ones like the page of all
public links. Clients get 403 (404 for what they can't see)."""

import datetime as dt
from typing import Literal

from django.http import Http404
from django.utils.translation import gettext as _
from ninja import Router, Schema, Status
from ninja.errors import HttpError

from biwak.api_conventions import ItemOut, PersonOut, absolute, item_out, person_out
from biwak.items.api import item_for
from biwak.permissions import api_staff_only
from biwak.public_links import operations as ops
from biwak.public_links.models import DEFAULT_DAYS, PublicLink


router = Router(tags=["public links"])


class PublicLinkOut(Schema):
    id: int
    url: str
    item: ItemOut
    created_by: PersonOut
    created_at: dt.datetime
    expires_at: dt.datetime


def link_out(link):
    return {
        "id": link.pk,
        "url": absolute(link.get_absolute_url()),
        "item": item_out(link.item),
        "created_by": person_out(link.created_by),
        "created_at": link.created_at,
        "expires_at": link.expires_at,
    }


def _staff_only(request):
    api_staff_only(request, _("Only staff share items publicly."))


def _shareable(request, item_id):
    item = item_for(request, item_id)
    _staff_only(request)
    if not item.is_shareable:
        raise HttpError(
            400,
            _("Only to-dos, messages, docs, files and check-in answers can be shared."),
        )
    return item


@router.get("public-links/", response=list[PublicLinkOut])
def public_link_list(request):
    """The live public links in the projects you can open (admins: all),
    the soonest expiry first"""
    _staff_only(request)
    links = PublicLink.objects.listed_for(request.user).select_related(
        "item", "item__project", "item__creator", "item__answer", "created_by"
    )
    return [link_out(link) for link in links]


def _link(item):
    link = (
        PublicLink.objects
        .live()
        .filter(item=item)
        .select_related("item__creator", "created_by")
        .first()
    )
    if link is None:
        raise Http404
    return link


@router.get("items/{item_id}/public-link/", response=PublicLinkOut)
def public_link_show(request, item_id: int):
    """The item's live public link; 404 without one"""
    return link_out(_link(_shareable(request, item_id)))


class PublicLinkIn(Schema):
    days: Literal[1, 3, 7, 30] = DEFAULT_DAYS


@router.post("items/{item_id}/public-link/", response={201: PublicLinkOut})
def public_link_create(request, item_id: int, data: PublicLinkIn):
    """A new public link for 1, 3, 7 or 30 days; it replaces the live one"""
    item = _shareable(request, item_id)
    link = ops.create_public_link(item, days=data.days, actor=request.user)
    return Status(201, link_out(link))


@router.delete("items/{item_id}/public-link/", response=PublicLinkOut)
def public_link_stop(request, item_id: int):
    """Stops sharing; returns the link stopped, 404 without one"""
    item = _shareable(request, item_id)
    data = link_out(_link(item))
    ops.stop_public_link(item, actor=request.user)
    return data
