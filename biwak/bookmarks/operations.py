"""Bookmarks and links (specs/feed.md). Neither records events: a bookmark
is private and a link is a reference, not news for the feed (decided by
the building agent, 2026-11-20)."""

from django.db import transaction
from django.db.models import Max

from biwak import links
from biwak.bookmarks.models import Bookmark, Link


@transaction.atomic
def add_bookmark(user, *, item=None, project=None):
    """Idempotent; returns whether it was added. The caller checked that
    the person can see the target."""
    if (item is None) == (project is None):
        raise ValueError("A bookmark is on an item or a project.")
    _bookmark, created = Bookmark.objects.get_or_create(
        user=user, item=item, project=project
    )
    return created


@transaction.atomic
def remove_bookmark(user, *, item=None, project=None):
    """Returns whether there was one"""
    deleted, _rows = Bookmark.objects.filter(
        user=user, item=item, project=project
    ).delete()
    return bool(deleted)


def is_bookmarked(user, *, item=None, project=None):
    return Bookmark.objects.filter(user=user, item=item, project=project).exists()


def can_manage_links(user):
    """Staff add, change, reorder and delete links; clients only see them"""
    return user.is_authenticated and not user.is_client


@transaction.atomic
def add_link(*, project, url, created_by, title="", visible=False):
    """On a project. Raises ``ValidationError`` for anything but http(s) URLs."""
    url = url.strip()
    position = (
        Link.objects.filter(project=project).aggregate(m=Max("position"))["m"] or 0
    ) + 1
    link = Link(
        project=project,
        url=url,
        title=title.strip() or links.host_of(url) or url,
        position=position,
        visible_to_clients=visible,
        created_by=created_by,
    )
    link.save()
    return link


@transaction.atomic
def update_link(link, *, url=None, title=None, visible=None):
    if url is not None:
        link.url = url.strip()
    if title is not None:
        link.title = title.strip() or links.host_of(link.url) or link.url
    if visible is not None:
        link.visible_to_clients = visible
    link.save()
    return link


@transaction.atomic
def delete_link(link):
    link.delete()


@transaction.atomic
def reorder_links(ids, *, user, project):
    """Puts the links of the project in the order of ``ids``, which has
    to name all the links the person sees there, each once; raises ``ValueError`` otherwise. Returns the links
    in the new order."""
    found = {
        link.pk: link
        for link in Link.objects
        .visible_to(user)
        .filter(project=project)
        .select_related("created_by", "project")
    }
    if sorted(ids) != sorted(found):
        raise ValueError("Name all the links, each once.")
    ordered = [found[pk] for pk in ids]
    for position, link in enumerate(ordered, start=1):
        if link.position != position:
            link.position = position
            link.save(update_fields=["position"])
    return ordered
