"""The activity feed (specs/feed.md): the events a person can see, like the
web interface's feed but one event each (merging is for people), cursor
paginated"""

import datetime as dt

from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import Router, Schema

from biwak.activity import feed
from biwak.activity.models import Action
from biwak.api_conventions import PersonOut, absolute, page_of, paginated, person_out
from biwak.items.models import Kind
from biwak.projects.api import project_for


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


def event_out(event, user):
    item = event.item
    data = dict(event.data)
    if user.is_client:
        # A list's name may be internal even if the to-do is visible now
        data.pop("to", None)
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
        "visible_to_clients": item is not None and item.is_client_visible,
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
    kind: Kind | None = None,
    action: Action | None = None,
    visible_to_clients: bool = False,
    since: dt.date | None = None,
    cursor: str | None = None,
    page_size: int | None = None,
):
    return _feed(
        request,
        project=project_for(request, project_id),
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
    kind: Kind | None = None,
    action: Action | None = None,
    visible_to_clients: bool = False,
    since: dt.date | None = None,
    cursor: str | None = None,
    page_size: int | None = None,
):
    person = get_object_or_404(feed.people_visible_to(request.user), pk=person_id)
    return _feed(
        request,
        person=person,
        kind=kind,
        action=action,
        visible_to_clients=visible_to_clients,
        since=since,
        cursor=cursor,
        page_size=page_size,
    )
