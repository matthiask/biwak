"""What every API endpoint shares (specs/api-cli.md):

- Visibility: everything goes through ``Item.objects.visible_to()``, like the
  web interface; a client's token sees what the client sees. Every item
  carries ``visible_to_clients``.
- Texts are accepted as Markdown and returned as Markdown and HTML
  (``notes`` and ``notes_html``).
- Lists which grow (completed to-dos, comments, events) use cursor
  pagination (``?cursor=``, ``next`` and ``previous`` in the response);
  short ones (projects, a list's open to-dos) are returned complete.
- URLs are absolute, pointing at the web interface.
- Errors are ``{"detail": "..."}``, validation errors ninja's list.
"""

import datetime as dt

from django.conf import settings
from ninja import Schema
from ninja.pagination import CursorPagination

from biwak.templatetags.biwak import render_markdown


def absolute(url):
    return settings.BASE_URL + url


def html(text, item=None):
    """Mentions with current names when the item is given, attachment URLs
    with BASE_URL"""
    return str(render_markdown(text, item, absolute=True))


class PersonOut(Schema):
    id: int
    name: str
    short_name: str
    is_client: bool
    organization: str


def person_out(user):
    if user is None:
        return None
    return {
        "id": user.pk,
        "name": str(user),
        "short_name": user.get_short_name(),
        "is_client": user.is_client,
        "organization": user.organization,
    }


class ItemOut(Schema):
    id: int
    kind: str
    title: str
    url: str
    project_id: int
    parent_id: int | None
    status: str
    visible_to_clients: bool
    creator: PersonOut
    created_at: dt.datetime
    updated_at: dt.datetime


def item_out(item):
    return {
        "id": item.pk,
        "kind": item.kind,
        "title": item.title,
        "url": absolute(item.get_absolute_url()),
        "project_id": item.project_id,
        "parent_id": item.parent_id,
        "status": item.status,
        # The effective visibility, not only the switch
        "visible_to_clients": item.is_client_visible,
        "creator": person_out(item.creator),
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def paginated(
    request, queryset, out, *, ordering, cursor=None, page_size=None, prepare=None
):
    """Cursor pagination with ninja's paginator, the results mapped through
    ``out``. The first ordering field has to be a field or an annotation of
    the queryset's model (it marks the position). ``prepare(objects)`` sees
    the page's objects before they are mapped, to load what they need with
    one query."""
    paginator = CursorPagination(ordering=ordering, page_size=50, max_page_size=200)
    page = paginator.paginate_queryset(
        queryset,
        pagination=paginator.Input(cursor=cursor, page_size=page_size),
        request=request,
    )
    objects = list(page["results"])
    if prepare is not None:
        prepare(objects)
    return page | {"results": [out(obj) for obj in objects]}


def page_of(schema):
    """The response schema of a paginated endpoint"""
    return type(
        f"{schema.__name__}Page",
        (Schema,),
        {
            "__annotations__": {
                "next": str | None,
                "previous": str | None,
                "results": list[schema],
            }
        },
    )
