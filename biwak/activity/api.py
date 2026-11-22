"""The activity feed (specs/feed.md): the events a person can see, like the
web interface's feed but one event each (merging is for people), cursor
paginated. Notification settings and the @ list (specs/notifications.md,
``biwak notifications``)."""

import datetime as dt

from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext as _
from ninja import Field, Router, Schema
from ninja.errors import HttpError

from biwak.accounts.models import MailDelivery, NotificationLevel
from biwak.activity import feed, history, lantern, mentions
from biwak.activity.models import Action, LevelOverride
from biwak.activity.operations import set_level_override, set_notification_settings
from biwak.api_conventions import PersonOut, absolute, page_of, paginated, person_out
from biwak.items.api import item_for
from biwak.items.models import Kind
from biwak.projects.api import project_for
from biwak.projects.models import known_ids_for


router = Router(tags=["feed"])


class EventItemOut(Schema):
    id: int
    kind: str
    title: str
    url: str
    visible_to_clients: bool


class EventOut(Schema):
    id: int
    action: str
    actor: PersonOut
    project_id: int
    item: EventItemOut | None
    # What the event stored: the title at the time, assignees, where it moved
    data: dict
    created_at: dt.datetime
    visible_to_clients: bool
    excerpt: str = Field(
        description="The start of the text as it is now, as plain text: the"
        " comment's for comments, the message's for every other event of a"
        " message; else empty"
    )


# What events' data names people in, by ID
PEOPLE_KEYS = ("mentioned", "assigned", "people", "assignees")


def event_out(event, user):
    item = event.item
    if not hasattr(event, "excerpt"):
        feed.add_excerpts([event])
    if not hasattr(event, "target_list"):
        feed.add_target_lists([event], user)
    data = dict(event.data)
    # People by ID: only those the reader may know (specs/access.md)
    if any(key in data for key in PEOPLE_KEYS):
        known = known_ids_for(user, event)
        for key in PEOPLE_KEYS:
            if key in data and known is not None:
                data[key] = [pk for pk in data[key] if pk in known]
    # Where a to-do was moved from and to by ID: for the timeline only
    for key in ("to_was", "group_id", "group_was"):
        data.pop(key, None)
    # The list a to-do moved to: only if the viewer may see it now
    if "to" in data:
        data["to"] = event.target_list
        if not event.target_list:
            del data["to"]
            data.pop("to_id", None)
    return {
        "id": event.pk,
        "action": event.action,
        "actor": person_out(event.actor),
        "project_id": event.project_id,
        "item": None
        if item is None
        else {
            "id": item.pk,
            "kind": item.kind,
            "title": item.title,
            "url": absolute(item.get_absolute_url()),
            "visible_to_clients": item.is_client_visible,
        },
        "data": data,
        "created_at": event.created_at,
        # Clients see the event (the item now, and the event's own time)
        "visible_to_clients": event.is_client_visible
        and item is not None
        and item.is_client_visible,
        "excerpt": event.excerpt,
    }


def _feed(
    request,
    *,
    project=None,
    person=None,
    kind=None,
    action=None,
    visible_to_clients=False,
    since=None,
    cursor=None,
    page_size=None,
):
    if since is not None:
        since = timezone.make_aware(dt.datetime.combine(since, dt.time()))
    events = feed.feed_events(
        request.user,
        project=project,
        person=person,
        kind=kind,
        action=action,
        visible_to_clients=visible_to_clients,
        since=since,
    )
    return paginated(
        request,
        events,
        lambda event: event_out(event, request.user),
        prepare=lambda events: (
            feed.add_excerpts(events),
            feed.add_target_lists(events, request.user),
        ),
        ordering=("-created_at", "-pk"),
        cursor=cursor,
        page_size=page_size,
    )


@router.get("feed/", response=page_of(EventOut))
def feed_list(
    request,
    *,
    project_id: int | None = None,
    person_id: int | None = None,
    kind: Kind | None = None,
    action: Action | None = None,
    visible_to_clients: bool = False,
    since: dt.date | None = None,
    cursor: str | None = None,
    page_size: int | None = None,
):
    """Newest first; ``since`` is a date (local time); the filters narrow
    down what the person can see"""
    project = project_for(request, project_id) if project_id else None
    person = None
    if person_id:
        person = get_object_or_404(
            feed.people_visible_to(request.user, project), pk=person_id
        )
    return _feed(
        request,
        project=project,
        person=person,
        kind=kind,
        action=action,
        visible_to_clients=visible_to_clients,
        since=since,
        cursor=cursor,
        page_size=page_size,
    )


@router.get("projects/{project_id}/feed/", response=page_of(EventOut))
def project_feed(
    request,
    project_id: int,
    *,
    person_id: int | None = None,
    kind: Kind | None = None,
    action: Action | None = None,
    visible_to_clients: bool = False,
    since: dt.date | None = None,
    cursor: str | None = None,
    page_size: int | None = None,
):
    project = project_for(request, project_id)
    person = None
    if person_id:
        person = get_object_or_404(
            feed.people_visible_to(request.user, project), pk=person_id
        )
    return _feed(
        request,
        project=project,
        person=person,
        kind=kind,
        action=action,
        visible_to_clients=visible_to_clients,
        since=since,
        cursor=cursor,
        page_size=page_size,
    )


@router.get("people/{person_id}/feed/", response=page_of(EventOut))
def person_feed(
    request,
    person_id: int,
    *,
    project_id: int | None = None,
    kind: Kind | None = None,
    action: Action | None = None,
    visible_to_clients: bool = False,
    since: dt.date | None = None,
    cursor: str | None = None,
    page_size: int | None = None,
):
    project = project_for(request, project_id) if project_id else None
    person = get_object_or_404(
        feed.people_visible_to(request.user, project), pk=person_id
    )
    return _feed(
        request,
        project=project,
        person=person,
        kind=kind,
        action=action,
        visible_to_clients=visible_to_clients,
        since=since,
        cursor=cursor,
        page_size=page_size,
    )


class DiffLineOut(Schema):
    op: str  # "+", "-", " " or "…" (lines left out)
    text: str


class ChangeOut(Schema):
    when: dt.datetime
    person: PersonOut | None
    # Who changed it if not a person: a job, "unknown"
    person_name: str
    field: str
    label: str
    kind: str  # created, changed, assigned, unassigned
    old: str | None
    new: str | None
    # Texts: the changed lines with some context
    diff: list[DiffLineOut] | None


@router.get("items/{item_id}/history/", response=list[ChangeOut])
def item_history(request, item_id: int):
    """The changes of an item from the audit log, newest first. Staff only,
    like the page."""
    item = item_for(request, item_id)
    if request.user.is_client:
        raise HttpError(403, _("The history is for staff only."))
    return [
        {
            "when": change.when,
            "person": person_out(change.user),
            "person_name": change.user_name,
            "field": change.field,
            "label": str(change.label),
            "kind": change.kind,
            "old": change.old,
            "new": change.new,
            "diff": None
            if change.diff is None
            else [{"op": op, "text": text} for op, text in change.diff],
        }
        for change in history.history(item, request.user)
    ]


# Notifications --------------------------------------------------------------

notifications_router = Router(tags=["notifications"])


class SettingsOut(Schema):
    level: NotificationLevel
    delivery: MailDelivery
    lantern_in_favicon: bool


class SettingsIn(Schema):
    level: NotificationLevel | None = None
    delivery: MailDelivery | None = None
    lantern_in_favicon: bool | None = None


def settings_out(user):
    return {
        "level": user.notification_level,
        "delivery": user.mail_delivery,
        "lantern_in_favicon": user.lantern_in_favicon,
    }


@notifications_router.get("me/notifications/", response=SettingsOut)
def settings_detail(request):
    """Your level (everything, only what concerns you, nothing), how mails
    come (each change, a daily digest, or none: the lantern only) and
    whether the tab's icon shows unread notifications"""
    return settings_out(request.user)


@notifications_router.put("me/notifications/", response=SettingsOut)
def settings_update(request, data: SettingsIn):
    """Changes what's given"""
    set_notification_settings(
        request.user,
        level=data.level,
        delivery=data.delivery,
        favicon=data.lantern_in_favicon,
    )
    return settings_out(request.user)


class OverrideIn(Schema):
    level: NotificationLevel


class ProjectOverrideOut(Schema):
    project_id: int
    level: NotificationLevel | None


class ItemOverrideOut(Schema):
    item_id: int
    level: NotificationLevel | None


def _override(user, **target):
    override = LevelOverride.objects.filter(user=user, **target).first()
    return override.level if override else None


@notifications_router.get(
    "projects/{project_id}/notifications/", response=ProjectOverrideOut
)
def project_override(request, project_id: int):
    """Your level for the project, null when it's your usual one"""
    project = project_for(request, project_id)
    return {
        "project_id": project.pk,
        "level": _override(request.user, project=project),
    }


@notifications_router.put(
    "projects/{project_id}/notifications/", response=ProjectOverrideOut
)
def project_override_set(request, project_id: int, data: OverrideIn):
    project = project_for(request, project_id)
    set_level_override(request.user, data.level, project=project)
    return {"project_id": project.pk, "level": data.level}


@notifications_router.delete(
    "projects/{project_id}/notifications/", response=ProjectOverrideOut
)
def project_override_delete(request, project_id: int):
    """Back to your usual level"""
    project = project_for(request, project_id)
    set_level_override(request.user, None, project=project)
    return {"project_id": project.pk, "level": None}


def list_for(request, item_id):
    """Lists have levels, other items don't: subscribing is the switch
    (specs/notifications.md, "Subscriptions")"""
    item = item_for(request, item_id)
    if item.kind != Kind.LIST:
        raise HttpError(
            400, _("Only lists have a level; subscribe or unsubscribe instead.")
        )
    return item


@notifications_router.get("items/{item_id}/notifications/", response=ItemOverrideOut)
def item_override(request, item_id: int):
    """Your level for the list and what's new in it, null when there's
    none; 400 for other items"""
    item = list_for(request, item_id)
    return {"item_id": item.pk, "level": _override(request.user, item=item)}


@notifications_router.put("items/{item_id}/notifications/", response=ItemOverrideOut)
def item_override_set(request, item_id: int, data: OverrideIn):
    item = list_for(request, item_id)
    set_level_override(request.user, data.level, item=item)
    return {"item_id": item.pk, "level": data.level}


@notifications_router.delete("items/{item_id}/notifications/", response=ItemOverrideOut)
def item_override_delete(request, item_id: int):
    item = list_for(request, item_id)
    set_level_override(request.user, None, item=item)
    return {"item_id": item.pk, "level": None}


class MentionableOut(Schema):
    id: int
    name: str
    short_name: str
    email: str
    available: bool
    reason: str


@notifications_router.get("items/{item_id}/mentionable/", response=list[MentionableOut])
def mentionable(request, item_id: int, q: str = ""):
    """People to mention, at most 10; those who can't see the item are
    listed as unavailable with the reason. Write a mention as
    ``[@Name](person:ID)``; ``@email`` and an unambiguous ``@Name`` work too."""
    item = item_for(request, item_id)
    return mentions.candidates(item, q, for_user=request.user)


# The lantern (specs/lantern.md) ----------------------------------------------


class LanternEntryOut(Schema):
    id: int
    read: bool
    created_at: dt.datetime
    mentioned: bool = Field(description="Whether you were mentioned")
    bookmarked: bool = Field(description="Whether you bookmarked the item")
    event: EventOut


class LanternPageOut(Schema):
    next: str | None
    previous: str | None
    results: list[LanternEntryOut]
    unread: int = Field(description="Your unread notifications")
    unread_items: int = Field(
        description="The items with unread notifications: what the menu counts"
    )


class LanternReadIn(Schema):
    item_id: int | None = None
    all: bool = False


class LanternReadOut(Schema):
    read: int


@notifications_router.get("lantern/", response=LanternPageOut)
def lantern_list(
    request,
    *,
    unread: bool = False,
    mentions: bool = False,
    cursor: str | None = None,
    page_size: int | None = None,
):
    """Your notifications (the lantern), newest first: about items you see
    now, the same as the mails. ``unread`` only those not read yet,
    ``mentions`` only those mentioning you. A page may hold fewer entries
    than asked for (items whose level is "nothing" now are left out)."""
    user = request.user
    bookmarked = lantern.bookmarked_items(user)

    def prepare(notifications):
        notifications[:] = lantern.wanted(notifications, user)
        lantern.prepare(notifications, user)

    unread_notifications, unread_items = lantern.unread_counts(user)
    page = paginated(
        request,
        lantern.notifications_for(
            user, unread=True if unread else None, mentions=mentions
        ),
        lambda notification: {
            "id": notification.pk,
            "read": notification.read_at is not None,
            "created_at": notification.created_at,
            "mentioned": notification.mentioned,
            "bookmarked": notification.event.item_id in bookmarked,
            "event": event_out(notification.event, user),
        },
        prepare=prepare,
        ordering=("-created_at", "-pk"),
        cursor=cursor,
        page_size=page_size,
    )
    return page | {"unread": unread_notifications, "unread_items": unread_items}


@notifications_router.post("lantern/read/", response=LanternReadOut)
def lantern_read(request, data: LanternReadIn):
    """Marks the notifications of an item (``item_id``: its own and its
    comments') or ``all`` as read; returns how many"""
    if data.all == (data.item_id is not None):
        raise HttpError(400, _("Give an item or all, not both."))
    if data.all:
        return {"read": lantern.read(request.user)}
    item = item_for(request, data.item_id)
    return {"read": lantern.read(request.user, item=item)}
