"""Creating and stopping public links (specs/public-links.md); views, the
API and the CLI call these. Trashing an item and archiving a project end
them for good (``end_links()``)."""

import datetime as dt

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from biwak.activity.models import Action
from biwak.activity.operations import record
from biwak.items.models import Item
from biwak.public_links.models import DAYS, PublicLink


def can_share(user, item):
    """Staff, on any leaf they see (internal or visible to clients);
    clients never, like the visibility switches (decided 2026-11-22);
    nothing in templates (``is_shareable``, specs/templates.md)"""
    return not user.is_client and item.is_shareable


@transaction.atomic
def create_public_link(item, *, days, actor):
    """A new link for ``days`` (one of ``DAYS``), replacing the live one;
    the event tells nobody (``notify.SILENT``)"""
    if not can_share(actor, item):
        raise PermissionDenied
    if days not in DAYS:
        raise ValueError(f"A public link lives {', '.join(map(str, DAYS))} days.")
    PublicLink.objects.filter(item=item).delete()
    now = timezone.now()
    link = PublicLink.objects.create(
        item=item,
        created_by=actor,
        created_at=now,
        expires_at=now + dt.timedelta(days=days),
    )
    record(
        actor=actor,
        action=Action.SHARED_PUBLICLY,
        project=item.project,
        item=item,
        days=days,
        expires_at=link.expires_at.isoformat(),
    )
    return link


@transaction.atomic
def stop_public_link(item, *, actor):
    """Ends the item's link; returns it (unsaved), or None if there was
    none (a double click: nothing happens, no event)"""
    if not can_share(actor, item):
        raise PermissionDenied
    link = PublicLink.objects.filter(item=item).first()
    if link is None:
        return None
    link.delete()
    record(actor=actor, action=Action.STOPPED_SHARING, project=item.project, item=item)
    return link


def end_links(*, item=None, project=None):
    """Trashing an item (with what's in it) or archiving its project ends
    the links for good: restoring or unarchiving doesn't bring them back
    (decided 2026-11-22). No events of their own, the trashing or
    archiving says it."""
    if item is not None:
        items = Item.objects.descendants(item, include_self=True)
        return PublicLink.objects.filter(item__in=items).delete()[0]
    return PublicLink.objects.filter(item__project=project).delete()[0]


def delete_expired(*, now=None):
    """``fairy_tasks``: deletes the expired links; returns how many"""
    return PublicLink.objects.filter(expires_at__lte=now or timezone.now()).delete()[0]
