from django.db.models.functions import Greatest

from biwak.activity.models import Event, Subscription, Unsubscription
from biwak.projects.models import Project


def record(*, actor, action, project, item=None, **data):
    if item is not None:
        data.setdefault("title", item.title)
    event = Event.objects.create(
        project=project, item=item, actor=actor, action=action, data=data
    )
    _touch_project(event, item)
    return event


def _touch_project(event, item):
    """The stored activity times (specs/projects-overview.md), one UPDATE:
    every event counts for staff, only events of items visible to clients
    now for clients (not project events, not internal items)"""
    when = event.created_at
    changes = {"last_activity_at": Greatest("last_activity_at", when)}
    if item is not None and item.is_client_visible:
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
