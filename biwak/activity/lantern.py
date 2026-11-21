"""The lantern: the notifications in the app (specs/lantern.md)

The same notifications as the mails (``notify()`` writes them), listed
with the rules of mailing them (``mails._deliverable()``): only about
items the person sees now, not those whose level is "nothing" now.
Others stay in the database, unseen. Only the lantern reads them
(decided 2026-11-21): following an entry, a form posting (``views.lantern_open``)
or marking them read, not opening the item some other way; read before
its mail goes, a notification isn't mailed (``mails.send_mails()``).
"""

from django.db import models, transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from biwak import cursors
from biwak.activity import feed
from biwak.activity.models import Action, Notification
from biwak.items.models import Item
from biwak.live import announce as live


# The menu shows the unread notifications and this many read ones
MENU_READ = 30
# More unread ones than this: the menu says so, the page has them all
MENU_UNREAD = 100


def notifications_for(user, *, unread=None, mentions=False):
    """The person's notifications about items they see now, newest first;
    ``unread`` True or False: only those; ``mentions``: only those where
    they were mentioned. Clients only those of the time clients saw the
    item (they're never told about others, this makes sure)."""
    notifications = Notification.objects.filter(
        user=user, event__item__in=Item.objects.visible_to(user)
    )
    if user.is_client:
        notifications = notifications.filter(event__is_client_visible=True)
    if unread is not None:
        notifications = notifications.filter(read_at__isnull=unread)
    if mentions:
        notifications = notifications.filter(event__data__mentioned__contains=[user.pk])
    return notifications.select_related(
        "event__item__project", "event__item__answer", "event__actor"
    ).order_by("-created_at", "-pk")


def wanted(notifications, user):
    """Those whose item's level isn't "nothing" now (the rest of
    ``mails._deliverable()`` is in ``notifications_for()``)"""
    from biwak.activity.mails import _deliverable

    return _deliverable(notifications, user)


def unread_count(user):
    return len(wanted(list(notifications_for(user, unread=True)), user))


def prepare(notifications, user):
    """What the entries show: the excerpts, the list a to-do moved to,
    whether the person was mentioned"""
    from biwak.activity.mails import describe

    events = [n.event for n in notifications]
    feed.add_excerpts(events)
    feed.add_target_lists(events, user)
    for notification in notifications:
        event = notification.event
        # An assignment's line says it itself ("and mentioned you")
        notification.mentioned = (
            user.pk in event.data.get("mentioned", ())
            and event.action != Action.ASSIGNED
        )
        # The mails' wording, a reaction with what it says
        notification.line = (
            _("%(actor)s reacted %(content)s")
            % {"actor": event.actor, "content": event.data.get("content", "")}
            if event.action == Action.REACTED
            else describe(event, user)
        )
        # Through the lantern: following it reads the item's notifications
        notification.url = reverse("lantern_open", args=[notification.pk])
    return notifications


def by_item(notifications):
    """``[(item, [notification, …])]``, in the order of each item's newest
    notification (the notifications are newest first)"""
    from biwak.search.views import KIND_ICONS

    groups = {}
    for notification in notifications:
        groups.setdefault(notification.event.item_id, []).append(notification)
    result = []
    for entries in groups.values():
        item = entries[0].event.item
        item.kind_icon = KIND_ICONS[item.kind]
        item.has_unread = any(n.read_at is None for n in entries)
        result.append((item, entries))
    return result


def bookmarked_items(user):
    """The IDs of the items the person bookmarked (and sees now)"""
    from biwak.bookmarks.models import Bookmark

    return set(
        Bookmark.objects
        .visible_to(user)
        .filter(item__isnull=False)
        .values_list("item", flat=True)
    )


def bookmarked(user, items=None):
    """The bookmarked items with notifications, each with its latest one, read
    or not, newest first: ``[(item, [notification])]``"""
    items = bookmarked_items(user) if items is None else items
    if not items:
        return []
    latest = wanted(
        list(
            notifications_for(user)
            .filter(event__item__in=items)
            .order_by("event__item_id", "-created_at", "-pk")
            .distinct("event__item_id")
        ),
        user,
    )
    latest.sort(key=lambda n: (n.created_at, n.pk), reverse=True)
    groups = by_item(prepare(latest, user))
    for item, _entries in groups:
        item.is_bookmarked = True
    return groups


def menu(user):
    """``(bookmarked groups, unread groups, read groups, more unread)`` for
    the menu; the bookmarked items aren't in the others"""
    items = bookmarked_items(user)
    marks = bookmarked(user, items)
    unread = wanted(
        list(
            notifications_for(user, unread=True).exclude(event__item__in=items)[
                : MENU_UNREAD + 1
            ]
        ),
        user,
    )
    read = wanted(
        list(
            notifications_for(user, unread=False).exclude(event__item__in=items)[
                :MENU_READ
            ]
        ),
        user,
    )
    prepare(unread[:MENU_UNREAD] + read, user)
    return (
        marks,
        by_item(unread[:MENU_UNREAD]),
        by_item(read),
        len(unread) > MENU_UNREAD,
    )


@transaction.atomic
def bookmark(user, item):
    """Bookmarks the item: its notifications go to the top"""
    from biwak.bookmarks.operations import add_bookmark

    added = add_bookmark(user, item=item)
    live.lantern_changed([user.pk], item=item)
    return added


@transaction.atomic
def unbookmark(user, item):
    """Removes the bookmark"""
    from biwak.bookmarks.operations import remove_bookmark

    removed = remove_bookmark(user, item=item)
    live.lantern_changed([user.pk], item=item)
    return removed


def anchor(notification):
    """Where the entry opens the item: at the comment where it applies"""
    url = notification.event.item.get_absolute_url()
    if comment := notification.event.data.get("comment"):
        return f"{url}#comment-{comment}"
    return url


def read(user, *, item=None, items=None):
    """Marks the person's notifications read: those of the item (and its
    comments, which are the item's events) or the items, or all; returns
    how many. Only those the person sees (``notifications_for()``): the
    others aren't counted, and stay unread and unseen. One query when
    there's nothing to read."""
    notifications = notifications_for(user, unread=True)
    if item is not None:
        items = [item]
    if items is not None:
        notifications = notifications.filter(event__item__in=items)
    count = Notification.objects.filter(
        pk__in=notifications.order_by().values("pk")
    ).update(read_at=timezone.now())
    if count:
        # Only notifications the person sees were read: no item to check
        live.lantern_changed([user.pk])
    return count


@transaction.atomic
def unread(user, *, item):
    """Marks the item's newest notification the person sees
    (``notifications_for()``) unread again, and never to be mailed;
    returns whether there was one"""
    newest = notifications_for(user, unread=False).filter(event__item=item).first()
    if newest is None:
        return False
    newest.read_at = None
    # Marked by hand: never mailed (decided 2026-11-21)
    newest.marked_unread_at = timezone.now()
    newest.save(update_fields=["read_at", "marked_unread_at"])
    live.lantern_changed([user.pk], item=item)
    return True


def page(user, *, unread=None, mentions=False, before=None, size=50):
    """A page of the lantern page: ``(groups, cursor of the next page)``;
    ``before`` the cursor of this page. The bookmarked items aren't in
    it (``bookmarked()``)."""
    notifications = notifications_for(user, unread=unread, mentions=mentions).exclude(
        event__item__in=bookmarked_items(user)
    )
    if before:
        at, pk = cursors.decode(before)
        notifications = notifications.filter(
            models.Q(created_at__lt=at) | models.Q(created_at=at, pk__lt=pk)
        )
    rows = list(notifications[: size + 1])
    more = len(rows) > size
    rows = rows[:size]
    cursor = cursors.encode(rows[-1].created_at, rows[-1].pk) if more else None
    rows = prepare(wanted(rows, user), user)
    return by_item(rows), cursor
