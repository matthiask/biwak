import datetime as dt

from django.db import transaction
from django.db.models.functions import Greatest
from django.utils import timezone

from biwak.accounts.models import MailDelivery, NotificationLevel
from biwak.activity.models import (
    Action,
    Event,
    LevelOverride,
    Subscription,
    Unsubscription,
)
from biwak.items.models import Item
from biwak.live import announce
from biwak.projects.models import Project


# What may take away who sees or edits docs: their open editors check again
# (specs/collaboration.md)
ACCESS_CHANGES = {
    Action.MOVED,
    Action.VISIBILITY_CHANGED,
    Action.TRASHED,
    Action.ARCHIVED,
    Action.EDITED_PROJECT,
    Action.REMOVED,
    Action.LEFT,
}

# An edit within this time of the person's last edit of the item updates
# that event instead of writing a new one ("once per editing session")
EDIT_SESSION = dt.timedelta(minutes=10)


def record(*, actor, action, project, item=None, **data):
    """Writes the event; after the commit, ``notify()`` decides who's told
    (project events notify nobody). The event stores whether the item is
    visible to clients now (read from the database, not the instance);
    edits only merge into an event of the same visibility, so an event
    clients see never takes in what happened while the item was internal."""
    visible = False
    if item is not None:
        data.setdefault("title", item.title)
        visible = Item.objects.filter(pk=item.pk, is_client_visible=True).exists()
    now = timezone.now()
    event = None
    # Edits merge, and so do moves between the groups of a list (board
    # columns, decided 2026-11-21): dragging back and forth is one event
    group_move = action == Action.MOVED and "group" in data
    if (action == Action.EDITED or group_move) and item is not None:
        events = Event.objects.filter(
            item=item,
            actor=actor,
            action=action,
            is_client_visible=visible,
            created_at__gte=now - EDIT_SESSION,
        )
        if group_move:
            events = events.filter(data__has_key="group")
        event = events.order_by("-created_at", "-pk").first()
    if event is not None:
        event.created_at = now
        event.data |= data
        event.save(update_fields=["created_at", "data"])
    else:
        event = Event.objects.create(
            project=project,
            item=item,
            actor=actor,
            action=action,
            data=data,
            is_client_visible=visible,
        )
    if action != Action.REACTED:
        # A reaction isn't activity of the project (decided by the building
        # agent, 2026-11-20)
        _touch_project(event)
    if action in ACCESS_CHANGES:
        from biwak.collab import live

        live.check_access(project=project.pk)
    if item is not None:
        from biwak.activity.notify import notify

        transaction.on_commit(lambda: notify(event.pk), robust=True)
        # The open pages of the item and its parent (specs/lantern.md)
        announce.changed(
            item, action=action, actor=actor, visible=event.is_client_visible
        )
    return event


def _touch_project(event):
    """The stored activity times (specs/projects-overview.md), one UPDATE:
    every event counts for staff, only events visible to clients for
    clients (not project events, not internal items)"""
    when = event.created_at
    changes = {"last_activity_at": Greatest("last_activity_at", when)}
    if event.is_client_visible:
        changes["last_client_activity_at"] = Greatest("last_client_activity_at", when)
    Project.objects.filter(pk=event.project_id).update(**changes)


def subscribe(user, item, *, added_by=None, explicit=True):
    """Subscribes a person. Automatic subscriptions (``explicit=False``,
    e.g. commenting) respect an earlier unsubscribing; explicit ones
    (subscribing, being assigned or mentioned) override it."""
    if explicit:
        Unsubscription.objects.filter(user=user, item=item).delete()
    elif Unsubscription.objects.filter(user=user, item=item).exists():
        return None
    subscription, _created = Subscription.objects.get_or_create(
        user=user,
        item=item,
        defaults={"added_by": added_by if added_by != user else None},
    )
    return subscription


def unsubscribe(user, item):
    Subscription.objects.filter(user=user, item=item).delete()
    Unsubscription.objects.get_or_create(user=user, item=item)


def is_subscribed(user, item):
    return Subscription.objects.filter(user=user, item=item).exists()


@transaction.atomic
def set_notification_settings(user, *, level=None, delivery=None, favicon=None):
    """The person's level, mail delivery and whether the tab's icon shows
    unread notifications, what's given"""
    fields = []
    if favicon is not None:
        user.lantern_in_favicon = favicon
        fields.append("lantern_in_favicon")
    if level is not None:
        user.notification_level = NotificationLevel(level)
        fields.append("notification_level")
    if delivery is not None:
        user.mail_delivery = MailDelivery(delivery)
        fields.append("mail_delivery")
    if fields:
        user.save(update_fields=fields)


@transaction.atomic
def set_level_override(user, level, *, project=None, item=None):
    """Overrides the person's level for a project or an item (and what's in
    it); ``level`` None removes the override"""
    if (project is None) == (item is None):
        raise ValueError("A project or an item, not both")
    target = {"project": project} if project is not None else {"item": item}
    if level is None:
        LevelOverride.objects.filter(user=user, **target).delete()
        return None
    override, _created = LevelOverride.objects.update_or_create(
        user=user, **target, defaults={"level": NotificationLevel(level)}
    )
    return override
