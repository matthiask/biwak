from biwak.activity.models import Event, Subscription, Unsubscription


def record(*, actor, action, project, item=None, **data):
    if item is not None:
        data.setdefault("title", item.title)
    return Event.objects.create(
        project=project, item=item, actor=actor, action=action, data=data
    )


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
