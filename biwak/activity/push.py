"""Push notifications (specs/web-push.md): being mentioned and being
assigned, pushed to the person's devices through the browsers' push
services once the mails' merge window has passed. ``send_mails`` runs
``send_due()`` every minute; nothing is pushed on requests or in threads.

Not pushed: what the person read in the lantern already, their own
actions, anything outside their working time or while they're away (and
nothing later: the lantern has it)."""

import datetime as dt
import json
import logging

from django.conf import settings
from django.db import transaction
from django.db.models import Exists, F, Func, JSONField, OuterRef, Q
from django.templatetags.static import static
from django.utils import timezone, translation

from biwak.accounts.languages import language_for
from biwak.accounts.models import PushSubscription, User
from biwak.activity import mails, mentions
from biwak.activity.models import Action, Notification
from biwak.api_conventions import absolute


logger = logging.getLogger(__name__)

# How long a push service keeps a push for a device which is offline
# (decided 2026-11-22); a push not delivered meanwhile is dropped
TTL = dt.timedelta(hours=12)
# One request to a push service
TIMEOUT = 10


def enabled():
    """Pushes need the VAPID key pair (``WEBPUSH_VAPID_*``); without it the
    setting isn't offered and nothing is sent"""
    return bool(
        settings.WEBPUSH_VAPID_PUBLIC_KEY and settings.WEBPUSH_VAPID_PRIVATE_KEY
    )


def wanted(notification):
    """Whether the notification is for the person in particular: the event
    mentions them, or assigns them (the tests of the lantern's "You were
    mentioned." and ``mails.describe()``). Not when read, not about their
    own actions."""
    event = notification.event
    user_id = notification.user_id
    if notification.read_at is not None or event.actor_id == user_id:
        return False
    if event.action == Action.ASSIGNED and user_id in event.data.get("assignees", ()):
        return True
    return user_id in event.data.get("mentioned", ())


class _ToJsonb(Func):
    function = "to_jsonb"
    output_field = JSONField()


def _wanted():
    """``wanted()`` in SQL"""
    me = _ToJsonb(F("user"))
    return (
        Q(event__data__mentioned__contains=me)
        | Q(event__action=Action.ASSIGNED, event__data__assignees__contains=me)
    ) & ~Q(event__actor=F("user"))


def pending():
    """The notifications still to push: wanted, not pushed, not read or
    marked unread in the lantern, for people with a device subscribed
    before the notification (subscribing doesn't push what was before)"""
    return Notification.objects.filter(
        _wanted(),
        Exists(
            PushSubscription.objects.filter(
                user=OuterRef("user"), created_at__lte=OuterRef("created_at")
            )
        ),
        pushed_at__isnull=True,
        read_at__isnull=True,
        marked_unread_at__isnull=True,
    )


def hold(notifications, now):
    """Marks the notifications of people in quiet hours or away as pushed
    without a push: nothing is pushed later (specs/web-push.md); returns
    those people's IDs"""
    from biwak.accounts.quiet import mails_held

    people = User.objects.filter(pk__in=notifications.values("user"))
    held = {user.pk for user in people if mails_held(user, now)}
    if held:
        notifications.filter(user__in=held).update(pushed_at=now)
    return held


def send_due(now=None):
    """Pushes what's due: one push per person and item (or the to-dos of
    one "Assign…") once the newest of its notifications is
    ``mails.MERGE_AFTER`` old, like the mails; returns how many pushes went
    to at least one device"""
    if not enabled():
        return 0
    now = now or timezone.now()
    notifications = pending()
    held = hold(notifications, now)
    groups = mails._groups(notifications.exclude(user__in=held))
    users = User.objects.in_bulk({user_id for user_id, _what in groups})
    count = 0
    for (user_id, (kind, _key)), group in groups.items():
        newest = group["newest"][0]
        if newest > now - mails.MERGE_AFTER:
            continue
        if group["more"] and newest > now - mails.BATCH_WAIT:
            continue
        try:
            count += _push(users[user_id], group["pks"], kind, now)
        except Exception:
            logger.exception("Pushing a notification failed")
    return count


def _push(user, pks, kind, now):
    """Claims the notifications (marks them pushed in a short transaction,
    so no other run takes them), pushes them as one to the person's
    devices outside it, so nothing waits for the push services, and gives
    them back for the next run when no device took it and none is gone,
    until ``TTL`` has passed"""
    claimed = _claim(pks, now)
    if not claimed:
        return 0
    deliverable = mails._deliverable(claimed, user)
    payload = None
    if deliverable:
        with (
            translation.override(language_for(user)),
            mentions.reading_as(user),
        ):
            payload = content(user, deliverable, batch=kind == "batch")
    pushed = deliver(user, payload) if payload else False
    newest = max(n.created_at for n in claimed)
    if pushed is None and newest > now - TTL:
        # Every device failed for now: the next run tries again (unless
        # read meanwhile, which pending() leaves out anyway)
        Notification.objects.filter(
            pk__in=[n.pk for n in claimed], pushed_at=now
        ).update(pushed_at=None)
        return 0
    return int(bool(pushed))


@transaction.atomic
def _claim(pks, now):
    """The notifications still to push among ``pks``, marked pushed at
    ``now``; those another run holds are skipped"""
    claimed = list(
        Notification.objects
        .select_for_update(skip_locked=True, of=("self",))
        .filter(
            pk__in=pks,
            pushed_at__isnull=True,
            read_at__isnull=True,
            marked_unread_at__isnull=True,
        )
        .select_related(
            "event__item__project",
            "event__item__parent",
            "event__actor",
            "user",
        )
    )
    Notification.objects.filter(pk__in=[n.pk for n in claimed]).update(pushed_at=now)
    return claimed


def content(user, notifications, *, batch=False):
    """What the push shows: the item's title, the lantern's line of the
    newest notification ("You were mentioned." where the lantern says it),
    the excerpt of a comment or message and the project; ``tag`` replaces
    an earlier push about the same item on the device, ``url`` is opened
    on a tap"""
    from biwak.activity import lantern

    icon = absolute(static("biwak/icon-192.png"))
    newest = max(notifications, key=lambda n: (n.created_at, n.pk))
    if batch:
        entry = lantern.Batch(
            sorted(notifications, key=lambda n: (n.created_at, n.pk), reverse=True)
        )
        return {
            "title": str(entry.title),
            "body": "\n".join(
                str(line) for line in [entry.line, entry.project or ""] if line
            ),
            "tag": f"biwak-{entry.pk}",
            "url": absolute(entry.url),
            "icon": icon,
            "actions": actions(),
        }
    (notification,) = lantern.prepare([newest], user)
    event = notification.event
    item = event.item
    line = notification.line
    if notification.mentioned:
        line = f"{line} {translation.gettext('You were mentioned.')}"
    return {
        "title": mentions.title(item.title, item),
        "body": "\n".join(
            part for part in [line, event.excerpt, str(item.project)] if part
        ),
        "tag": f"biwak-item-{item.pk}",
        "url": absolute(notification.url),
        "icon": icon,
        "actions": actions(),
    }


def actions():
    """A button on the push (where browsers show them): turning pushes off
    on the device without signing in, for a browser signed out
    (frontend/sw.js; the next push's 410 deletes the device)"""
    return [{"action": "off", "title": translation.gettext("Turn off on this device")}]


def _vapid_key():
    """The private key as py_vapid takes it: PEM, or base64url (DER or
    raw) on one line"""
    from py_vapid import Vapid

    key = settings.WEBPUSH_VAPID_PRIVATE_KEY.strip()
    if key.startswith("-----BEGIN"):
        return Vapid.from_pem(key.encode())
    return Vapid.from_string(key)


def deliver(user, payload):
    """Sends the payload to each of the person's devices: True when one
    took it, False when there's none left (a 404 or 410 deletes the
    subscription: the browser dropped it), None when all failed otherwise
    (logged)"""
    from pywebpush import WebPushException, webpush

    subscriptions = list(user.push_subscriptions.all())
    if not subscriptions:
        return False
    key = _vapid_key()
    data = json.dumps(payload)
    delivered = failed = False
    for subscription in subscriptions:
        try:
            webpush(
                subscription.info(),
                data=data,
                vapid_private_key=key,
                # webpush() adds to the claims: a new dict each time
                vapid_claims={"sub": settings.WEBPUSH_SUBJECT},
                ttl=int(TTL.total_seconds()),
                timeout=TIMEOUT,
            )
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status in {404, 410}:
                subscription.delete()
                continue
            logger.warning("Push to %s failed: %s", subscription.endpoint, exc)
            failed = True
        except Exception:
            logger.exception("Push to %s failed", subscription.endpoint)
            failed = True
        else:
            PushSubscription.objects.filter(pk=subscription.pk).update(
                last_success_at=timezone.now()
            )
            delivered = True
    if delivered:
        return True
    return None if failed else False
