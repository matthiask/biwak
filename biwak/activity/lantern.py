"""The lantern: the notifications in the app (specs/lantern.md)

The same notifications as the mails (``notify()`` writes them), listed
with the rules of mailing them (``mails._deliverable()``): only about
items the person sees now (subscribing is the switch: the level doesn't
hide anything), and of completing and reopening only the net change.
Others stay in the database, unseen. Only the lantern reads them
(decided 2026-11-21): following an entry (a link posting ``views.lantern_open``
in the background)
or marking them read, not opening the item some other way; read before
its mail goes, a notification isn't mailed (``mails.send_mails()``).
"""

from django.db import models, transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _, ngettext

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
        "event__item__project",
        "event__item__answer",
        "event__item__parent",
        "event__actor",
    ).order_by("-created_at", "-pk")


def wanted(notifications, user):
    """Those the person may still get (``mails._deliverable()``: the item
    visible to them now, of the unread ones only the net change of
    completing and reopening, counting those outside ``notifications``;
    the rest is in ``notifications_for()``)"""
    from biwak.activity.mails import _deliverable, done_neighbours

    # The neighbours beyond a page's edge or the menu's limit count too
    others = done_neighbours(notifications_for(user, unread=True), notifications)
    return _deliverable(notifications, user, others=others)


# The keys of to-dos assigned by one "Assign…" and dated by one "Due
# date…" (``batch_key()``)
ASSIGNED = "assigned"
DATED = "dated"

# The actions of to-dos changed together, across projects
# (specs/handover.md), and their keys
TODO_BATCHES = {Action.ASSIGNED: ASSIGNED, Action.EDITED: DATED}


def todo_batch(action):
    """The key of to-dos changed together by ``action``, or None"""
    return TODO_BATCHES.get(action)


def batch_key(notification):
    """For files uploaded in a batch: who uploaded them where (the project
    and the folder, or the top level); for to-dos assigned by one
    "Assign…" or dated by one "Due date…" (specs/handover.md): who did it,
    across projects; None for anything else"""
    event = notification.event
    if not event.data.get("batch"):
        return None
    if kind := todo_batch(event.action):
        return (kind, event.actor_id)
    if event.action != Action.CREATED:
        return None
    return (event.actor_id, event.project_id, event.item.parent_id)


def chain(chains, key, batch, at):
    """The number of the entry (and mail) an upload belongs to, the uploads
    taken oldest first: one person's uploads into one folder (``key``) are
    one chain while each comes within ``mails.MERGE_AFTER`` of the one
    before; a batch's files stay in the chain it started in, whatever came
    in between (still going up, however long a file takes, another tab's
    batch). ``chains`` keeps the state, one dict per run. The one rule of
    the lantern and the mails (decided 2026-11-22)."""
    from biwak.activity.mails import MERGE_AFTER

    state = chains.setdefault(key, {"count": 0, "last": None, "batches": {}})
    if batch in state["batches"]:
        number = state["batches"][batch]
    elif state["last"] is not None and at - state["last"][0] <= MERGE_AFTER:
        number = state["last"][1]
    else:
        number = state["count"]
        state["count"] += 1
    state["last"] = (at, number)
    state["batches"][batch] = number
    return number


def group_batches(notifications):
    """Sets ``batch_entry`` on the notifications of files uploaded in
    batches: one person's uploads into one folder (or the top level), each
    within ``mails.MERGE_AFTER`` of the one before or of its batch, are one
    entry, also from separate rounds (decided 2026-11-21, like the feed
    merges; ``chain()``). To-dos one person assigned with "Assign…" the
    same (specs/handover.md). Returns the notifications."""
    chains = {}
    for notification in sorted(notifications, key=lambda n: (n.created_at, n.pk)):
        key = batch_key(notification)
        if key is None:
            continue
        number = chain(
            chains, key, notification.event.data["batch"], notification.created_at
        )
        notification.batch_entry = (*key, number)
    return notifications


def entry_key(notification):
    """What the lantern's entry of a notification is: its item, or the
    files uploaded together (specs/files.md, "Uploading files";
    ``group_batches()`` ran)"""
    if entry := getattr(notification, "batch_entry", None):
        return ("batch", entry)
    return ("item", notification.event.item_id)


def entry_items(user, notification):
    """The items of the notification's entry: its item, or the files
    uploaded together (``group_batches()`` among the person's
    notifications of that person's uploads there)"""
    key = batch_key(notification)
    if key is None:
        return [notification.event.item]
    if key[0] in {ASSIGNED, DATED}:
        action = next(a for a, kind in TODO_BATCHES.items() if kind == key[0])
        same = notifications_for(user).filter(event__actor=key[1], event__action=action)
    else:
        actor, project, parent = key
        same = notifications_for(user).filter(
            event__actor=actor,
            event__project=project,
            event__item__parent=parent,
            event__action=Action.CREATED,
        )
    same = group_batches(list(same.filter(event__data__has_key="batch")))
    entry = next(n.batch_entry for n in same if n.pk == notification.pk)
    return [n.event.item for n in same if n.batch_entry == entry]


def unread_counts(user):
    """``(notifications, entries)``: how many unread notifications the
    person has, and about how many items (the menu groups by item, and a
    batch of files is one entry). Counted in the database (consistent,
    2026-11-28): only what needs the order of events is loaded, the
    notifications of items with completing, reopening or moves among them
    (which may cancel out, ``wanted()``) and those of batches
    (``group_batches()``); the same numbers as the menu's."""
    from biwak.activity.mails import DONE, _deliverable

    unread = notifications_for(user, unread=True).order_by()
    batched = models.Q(event__data__has_key="batch") & models.Q(
        event__action__in=[*TODO_BATCHES, Action.CREATED]
    )
    ordered = models.Q(
        event__item__in=unread.filter(event__action__in=[*DONE, Action.MOVED]).values(
            "event__item"
        )
    )
    # ``wanted()`` without looking for neighbours: those of the items
    # completed or reopened are all here
    loaded = group_batches(_deliverable(list(unread.filter(ordered | batched)), user))
    entries = {entry_key(n) for n in loaded}
    items = [key for kind, key in entries if kind == "item"]
    rest = unread.exclude(ordered | batched).aggregate(
        count=models.Count("pk"),
        items=models.Count(
            "event__item",
            distinct=True,
            filter=~models.Q(event__item__in=items),
        ),
    )
    return len(loaded) + rest["count"], len(entries) + rest["items"]


def unread_count(user):
    """The number of entries the menu shows as unread: the items (and
    batches) with unread notifications, not the notifications (decided
    2026-11-21)"""
    return unread_counts(user)[1]


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
            % {"actor": event.actor_name, "content": event.data.get("content", "")}
            if event.action == Action.REACTED
            else describe(event, user)
        )
        # A link to where it applies (its address shows on hovering, it
        # opens in a new tab); following it posts to ``read_url`` in the
        # background, which reads the item's notifications
        notification.url = anchor(notification)
        notification.read_url = reverse("lantern_open", args=[notification.pk])
    return notifications


def unread_by_item(user, item_ids):
    """``{item ID: newest unread notification}`` of the items among
    ``item_ids``, with ``read_url`` (following a link to the item posts
    there, which reads its notifications); the same rules as the menu. Two
    queries at most, for any number of items. Home marks its rows with it
    (specs/dashboard.md)."""
    if not item_ids:
        return {}
    found = wanted(
        list(notifications_for(user, unread=True).filter(event__item__in=item_ids)),
        user,
    )
    result = {}
    for notification in found:
        notification.read_url = reverse("lantern_open", args=[notification.pk])
        result.setdefault(notification.event.item_id, notification)
    return result


class Batch:
    """Files uploaded together (``group_batches()``), one entry of the
    lantern in place of an item's: "Ada uploaded 5 files to Minutes", each
    file linked; or the to-dos of one "Assign…" (specs/handover.md): "Ada
    assigned you 23 to-dos", or of one "Due date…": "Ada changed the dates
    of 23 to-dos", each to-do linked"""

    is_batch = True

    def __init__(self, entries):
        from biwak.search.views import KIND_ICONS

        newest = entries[0]
        files = {}
        for notification in reversed(entries):
            item = notification.event.item
            item.read_url = getattr(notification, "read_url", "")
            files.setdefault(item.pk, item)
        self.files = list(files.values())
        # What frontend/lantern.js tells the entries apart by
        self.pk = f"{self.files[0].pk}-batch"
        self.has_unread = any(n.read_at is None for n in entries)
        projects = {item.project_id for item in self.files}
        # Across projects for to-dos: none to name
        self.project = self.files[0].project if len(projects) == 1 else None
        event = newest.event
        if event.action == Action.ASSIGNED:
            self.kind_icon = "person-plus"
            self.item_icon = KIND_ICONS[self.files[0].kind]
            you = any(
                newest.user_id in n.event.data.get("assignees", ()) for n in entries
            )
            self.title = _("To-dos")
            self.url = reverse("todos")
            self.line = assigned_line(event.actor_name, len(self.files), you=you)
            self.subject = self.line.removesuffix(".")
            return
        if event.action == Action.EDITED:
            self.kind_icon = "calendar-event"
            self.item_icon = KIND_ICONS[self.files[0].kind]
            self.title = _("To-dos")
            self.url = reverse("todos")
            self.line = dated_line(event.actor_name, len(self.files))
            self.subject = self.line.removesuffix(".")
            return
        self.kind_icon = "upload"
        self.item_icon = "file-earmark"
        folder = self.files[0].parent
        self.title = folder.title if folder else _("Docs and files")
        self.subject = self.title
        self.url = (
            folder.get_absolute_url()
            if folder
            else reverse("project_files", args=[self.project.pk])
        )
        self.line = batch_line(event.actor_name, len(self.files), self.title)


def batch_line(actor, count, where):
    return ngettext(
        "%(actor)s uploaded a file to %(where)s.",
        "%(actor)s uploaded %(count)s files to %(where)s.",
        count,
    ) % {"actor": actor, "count": count, "where": where}


def assigned_line(actor, count, *, you):
    """ "Ada assigned you 23 to-dos.", or for those told who weren't
    assigned (subscribed to the to-dos) "Ada assigned people to 23 to-dos." """
    if you:
        text = ngettext(
            "%(actor)s assigned you a to-do.",
            "%(actor)s assigned you %(count)s to-dos.",
            count,
        )
    else:
        text = ngettext(
            "%(actor)s assigned people to a to-do.",
            "%(actor)s assigned people to %(count)s to-dos.",
            count,
        )
    return text % {"actor": actor, "count": count}


def dated_line(actor, count):
    """ "Ada changed the dates of 23 to-dos." (one "Due date…")"""
    return ngettext(
        "%(actor)s changed the dates of a to-do.",
        "%(actor)s changed the dates of %(count)s to-dos.",
        count,
    ) % {"actor": actor, "count": count}


def by_item(notifications, *, batches=True):
    """``[(item, [notification, …])]``, in the order of each item's newest
    notification (the notifications are newest first); files uploaded
    together are one ``(Batch, [newest notification])`` (unless not
    ``batches``: the bookmarked items are items)"""
    from biwak.search.views import KIND_ICONS

    groups = {}
    if batches:
        group_batches(notifications)
    for notification in notifications:
        key = (
            entry_key(notification) if batches else ("item", notification.event.item_id)
        )
        groups.setdefault(key, []).append(notification)
    result = []
    for (kind, _key), entries in groups.items():
        if kind == "batch":
            result.append((Batch(entries), entries[:1]))
            continue
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
    notifications = notifications_for(user).filter(event__item__in=items)
    # The unread ones and the latest read one of each item go through
    # wanted(), then the latest left of each item: the latest may cancel
    # out against another, an older one still shows the item (an unread
    # one is in the badge's count)
    candidates = [
        *notifications.filter(read_at__isnull=True),
        *notifications
        .filter(read_at__isnull=False)
        .order_by("event__item_id", "-created_at", "-pk")
        .distinct("event__item_id"),
    ]
    latest = {}
    for notification in sorted(
        wanted(candidates, user),
        key=lambda n: (n.created_at, n.pk),
        reverse=True,
    ):
        latest.setdefault(notification.event.item_id, notification)
    latest = list(latest.values())
    groups = by_item(prepare(latest, user), batches=False)
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
    more = len(unread) > MENU_UNREAD
    unread = unread[:MENU_UNREAD]
    prepare(unread + read, user)
    # One entry per item (decided 2026-11-23): an item with unread
    # notifications shows its read ones in its entry among the unread,
    # not a second time among the read
    unread_items = {n.event.item_id for n in unread}
    shown = sorted(
        [*unread, *(n for n in read if n.event.item_id in unread_items)],
        key=lambda n: (n.created_at, n.pk),
        reverse=True,
    )
    read = [n for n in read if n.event.item_id not in unread_items]
    return marks, by_item(shown), by_item(read), more


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
    """Where the entry opens the item: at the comment where it applies, at
    the reactions to completing it"""
    url = notification.event.item.get_absolute_url()
    if comment := notification.event.data.get("comment"):
        return f"{url}#comment-{comment}"
    if notification.event.action == Action.REACTED and (
        completed := notification.event.data.get("event")
    ):
        return f"{url}#reactions-event-{completed}"
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
    """Marks the item's notifications the person sees
    (``notifications_for()``) unread again, those read together with the
    newest one (``read()`` reads an item's at once, so the entry comes
    back as it was, decided 2026-11-21), and never to be mailed; returns
    whether there was one"""
    read = notifications_for(user, unread=False).filter(event__item=item)
    newest = read.first()
    if newest is None:
        return False
    Notification.objects.filter(
        pk__in=read.filter(read_at=newest.read_at).order_by().values("pk")
    ).update(
        read_at=None,
        # Marked by hand: never mailed (decided 2026-11-21)
        marked_unread_at=timezone.now(),
    )
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
