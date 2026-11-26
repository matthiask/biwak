import datetime as dt
from contextlib import contextmanager
from contextvars import ContextVar

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models.functions import Greatest
from django.utils import timezone
from django.utils.translation import gettext

from biwak.accounts.models import MailDelivery, NotificationLevel
from biwak.activity.models import (
    Action,
    Event,
    LevelOverride,
    Subscription,
    Unsubscription,
)
from biwak.items.models import Item, Kind, Todo
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

# Events only staff see, also on items visible to clients: public links
# (specs/public-links.md, decided 2026-11-22). Recorded as internal, so
# every way clients read events (the feeds, the API, live updates) leaves
# them out.
STAFF_ONLY = {Action.SHARED_PUBLICLY, Action.STOPPED_SHARING}

# An edit within this time of the person's last edit of the item updates
# that event instead of writing a new one ("once per editing session")
EDIT_SESSION = dt.timedelta(minutes=10)


def _mergeable(earlier, data):
    """Whether an edit merges into the earlier edit event: always, unless
    exactly one of them is part of a batch ("Due date…" of several
    to-dos, told as "changed the dates of 3 to-dos"); then only when the
    other one changed nothing but fields the batch changed too, so no
    other change is hidden in the batch's line (decided 2026-11-23)."""
    if ("batch" in earlier) == ("batch" in data):
        return True
    batch, other = (earlier, data) if "batch" in earlier else (data, earlier)
    return set(other.get("fields", [])) <= set(batch.get("fields", []))


# What an import switches (``importing()``): nobody is told, and events carry
# the original time
_quiet = ContextVar("events_quiet", default=False)
_occurred_at = ContextVar("events_occurred_at", default=None)
_importing = ContextVar("events_importing", default=False)


@contextmanager
def importing(*, at=None):
    """For the importer (specs/import-basecamp.md): events recorded inside
    notify nobody, and carry ``at`` (when given) instead of now. Nested
    uses replace ``at``; the quiet part stays. Inside, the operations also
    accept inactive people (assigning, subscribing, memberships): the
    importer creates people without an account inactive (decided
    2026-11-21). The projects' activity times aren't touched per event:
    the importer recomputes them once per project
    (``projects.operations.recompute_activity()``, decided 2026-11-23)."""
    quiet = _quiet.set(True)
    importer = _importing.set(True)
    occurred = _occurred_at.set(at if at is not None else _occurred_at.get())
    try:
        yield
    finally:
        _importing.reset(importer)
        _occurred_at.reset(occurred)
        _quiet.reset(quiet)


def is_importing():
    """Whether we're inside ``importing()``: inactive people are accepted"""
    return _importing.get()


def read_by_acting(actor, *items):
    """The person acted on the item (completed it, commented, reacted, …):
    their notifications of it (or them) are read (``lantern.read()``, specs/lantern.md,
    "Reading by acting"). Not for the importer, which acts as other people
    (inside ``importing()``)."""
    if is_importing():
        return
    from biwak.activity import lantern

    lantern.read(actor, items=items)


def record(*, actor, action, project, item=None, internal=False, **data):
    """Writes the event; after the commit, ``notify()`` decides who's told
    (project events notify nobody). The event stores whether the item is
    visible to clients now (read from the database, not the instance);
    edits only merge into an event of the same visibility, so an event
    clients see never takes in what happened while the item was internal.
    ``STAFF_ONLY`` events are internal whatever the item, and so are
    ``internal`` ones (a reaction to a completing clients didn't see)."""
    visible = False
    if item is not None:
        data.setdefault("title", item.title)
        visible = (
            not internal
            and action not in STAFF_ONLY
            and Item.objects.filter(pk=item.pk, is_client_visible=True).exists()
        )
    now = _occurred_at.get() or timezone.now()
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
        if event is not None and not _mergeable(event.data, data):
            event = None
    if event is not None:
        event.created_at = now
        # Merged edits list everything they changed
        fields = [*event.data.get("fields", []), *data.get("fields", [])]
        # The first "was" stays
        data = {
            k: v
            for k, v in data.items()
            if not (k.endswith("_was") and k in event.data)
        }
        event.data |= data
        if fields:
            event.data["fields"] = list(dict.fromkeys(fields))
        event.save(update_fields=["created_at", "data"])
    else:
        event = Event.objects.create(
            project=project,
            item=item,
            actor=actor,
            action=action,
            data=data,
            is_client_visible=visible,
            created_at=now,
        )
    if action != Action.REACTED and not is_importing():
        # A reaction isn't activity of the project (decided by the building
        # agent, 2026-11-20); an import recomputes them at the end
        _touch_project(event)
    # Before announcing the change (both after the commit, in this order):
    # a page losing access closes before it hears of the change, since the
    # channel layer keeps the order of one sender's messages (the pages
    # check again before passing anything on too). Pinned by
    # biwak/live/test_announce.py. Also while importing: taking access
    # away is never quiet.
    if action in ACCESS_CHANGES:
        from biwak.collab import live

        live.check_access(project=project.pk)
    if item is not None and not _quiet.get():
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
    (subscribing, being assigned or mentioned) override it. Inactive people
    only inside ``importing()``."""
    if not user.is_active and not is_importing():
        raise ValueError("Inactive people can't be subscribed.")
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


class StillAssigned(ValueError):
    """Somebody assigned to a to-do can't unsubscribe from it"""

    def __init__(self):
        super().__init__(
            gettext("You're assigned, so you hear about it. Unassign yourself first.")
        )


def is_assigned(user, item):
    """Whether the person is assigned to the to-do (specs/notifications.md,
    "Assigned means subscribed")"""
    return (
        item.kind == Kind.TODO
        and Todo.assignees.through.objects.filter(todo_id=item.pk, user=user).exists()
    )


# The note of "Tell them now" is one line
NOTE_LENGTH = 200


def subscribable_people(item, by):
    """Whom ``by`` may subscribe to the item: the active people who can see
    it (``mentions.mentionable_people()``), and for clients and externals
    only those they may know (``mentions.known_to()``), as everywhere;
    not ``by`` themselves, who has their own button"""
    from biwak.activity import mentions

    people = mentions.known_to(mentions.mentionable_people(item), item.project, by)
    return people.exclude(pk=by.pk)


@transaction.atomic
def share(item, people, *, actor, notify=False, note=""):
    """Subscribes people to the item, ``added_by`` the actor (explicitly: it
    overrides an earlier unsubscribing, like assigning); ``ValueError`` for
    anybody who isn't in ``subscribable_people()``. With ``notify`` ("Tell
    them now") the ``shared`` event tells each of them at once, with the
    note (one line, ``NOTE_LENGTH`` characters at most), whatever their
    level. Returns the people, newly subscribed or not."""
    note = " ".join(note.split())
    if len(note) > NOTE_LENGTH:
        raise ValueError(f"The note has at most {NOTE_LENGTH} characters.")
    people = list(dict.fromkeys(people))
    allowed = set(
        subscribable_people(item, actor)
        .filter(pk__in=[u.pk for u in people])
        .values_list("pk", flat=True)
    )
    for user in people:
        if user.pk not in allowed:
            raise ValueError(f"{user} can't be subscribed to {item}")
    for user in people:
        subscribe(user, item, added_by=actor)
    if people and notify:
        record(
            actor=actor,
            action=Action.SHARED,
            project=item.project,
            item=item,
            people=[u.pk for u in people],
            **({"note": note} if note else {}),
        )
    return people


def unsubscribe(user, item):
    """The one check (decided 2026-11-21): ``StillAssigned`` while the
    person is assigned to the to-do; the pages, the mail link, the API and
    the CLI all come through here"""
    if is_assigned(user, item):
        raise StillAssigned
    Subscription.objects.filter(user=user, item=item).delete()
    Unsubscription.objects.get_or_create(user=user, item=item)


def is_subscribed(user, item):
    return Subscription.objects.filter(user=user, item=item).exists()


@transaction.atomic
def set_notification_settings(
    user,
    *,
    level=None,
    delivery=None,
    favicon=None,
    quiet_hours=None,
    working_days=None,
    working_from=None,
    working_until=None,
):
    """The person's level, mail delivery, whether the tab's icon shows
    unread notifications and the quiet hours (specs/quiet-hours.md), what's
    given; raises ``ValidationError`` for working hours which end before
    they start or quiet hours without working days"""
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
    if quiet_hours is not None:
        user.quiet_hours = bool(quiet_hours)
        fields.append("quiet_hours")
    if working_days is not None:
        days = sorted(set(working_days))
        if any(day not in range(7) for day in days):
            raise ValidationError(gettext("Working days are 0 (Monday) to 6 (Sunday)."))
        user.working_days = days
        fields.append("working_days")
    if working_from is not None:
        user.working_from = working_from
        fields.append("working_from")
    if working_until is not None:
        user.working_until = working_until
        fields.append("working_until")
    if user.working_from >= user.working_until:
        raise ValidationError(gettext("The working hours end after they start."))
    if user.quiet_hours and not user.working_days:
        raise ValidationError(gettext("Choose at least one working day."))
    if fields:
        user.save(update_fields=fields)


@transaction.atomic
def set_level_override(user, level, *, project=None, item=None):
    """Overrides the person's level for a project or a list (and what's new
    in it); ``level`` None removes the override. Other items have no level:
    subscribing is the switch (specs/notifications.md, "Subscriptions").
    "Everything" for a list subscribes to it too: watching it (decided
    2026-11-26, "Watching a list"); other levels unsubscribe nobody."""
    if (project is None) == (item is None):
        raise ValueError("A project or an item, not both")
    if item is not None and item.kind != Kind.LIST:
        raise ValueError("Only lists have a level")
    target = {"project": project} if project is not None else {"item": item}
    if level is None:
        LevelOverride.objects.filter(user=user, **target).delete()
        return None
    override, _created = LevelOverride.objects.update_or_create(
        user=user, **target, defaults={"level": NotificationLevel(level)}
    )
    if item is not None and level == NotificationLevel.EVERYTHING:
        subscribe(user, item)
    return override
