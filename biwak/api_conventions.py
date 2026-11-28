"""What every API endpoint shares (specs/api-cli.md):

- Visibility: everything goes through ``Item.objects.visible_to()``, like the
  web interface; a client's token sees what the client sees. Every item
  carries ``visible_to_clients``.
- Texts are accepted as Markdown and returned as Markdown and HTML
  (``notes`` and ``notes_html``). Task lists (``- [ ] a``) render as
  disabled checkboxes; to-dos, messages, docs and files return the count
  of their text as ``checklist_done`` and ``checklist_total``.
- Lists which grow (completed to-dos, comments, events) use cursor
  pagination (``?cursor=``, ``next`` and ``previous`` in the response,
  ``paginated()``: the position in the whole ordering);
  short ones (projects, a list's open to-dos) are returned complete.
- URLs are absolute, pointing at the web interface.
- Errors are ``{"detail": "..."}``, validation errors ninja's list (422);
  the model's ``ValidationError`` is a 400 (``biwak/api.py``).
"""

import base64
import binascii
import datetime as dt
import json
from typing import Annotated
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import DataError
from django.db.models import Q
from django.utils.translation import gettext
from ninja import Field, Schema
from ninja.errors import HttpError
from pydantic import StringConstraints

from biwak.templatetags.biwak import render_markdown


# The title of an item: stripped, not empty, as long as ``Item.title`` allows
Title = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)
]


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
    is_active: bool = Field(
        description="False for people who left (deactivated); they stay"
        " assigned and show as inactive (specs/handover.md)."
    )
    organization: str
    organization_id: int | None
    image_url: str | None = Field(
        description="The profile image (WebP, 256 pixels), served only to"
        " those who may know the person (as for names); null without one."
    )
    mark: str = Field(
        description="The drawn mark shown without a profile image (the name"
        " of a drawing, e.g. ibex; specs/people.md), in white on a color"
        " chosen from the id."
    )
    away_until: dt.date | None = Field(
        None,
        description="Away up to and including this day (out of office,"
        " specs/quiet-hours.md); null when not away.",
    )
    away_note: str = Field(
        "", description="The note of the person away, one line; empty otherwise."
    )


def person_out(user):
    if user is None:
        return None
    return {
        "id": user.pk,
        "name": str(user),
        "short_name": user.get_short_name(),
        "is_client": user.is_client,
        "is_active": user.is_active,
        "organization": user.organization_name,
        "organization_id": user.organization_id,
        "image_url": absolute(user.image_url) if user.image else None,
        "mark": user.mark,
        "away_until": user.away_until if user.is_away else None,
        "away_note": user.away_note if user.is_away else "",
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


# Pages of lists: the size without ``page_size`` and the largest one
PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


def paginated(
    request, queryset, out, *, ordering, cursor=None, page_size=None, prepare=None
):
    """Cursor pagination, the results mapped through ``out``. The cursor is
    the position of a row in the whole ``ordering`` (fields, annotations or
    lookups like ``parent__position``, never null, the last one unique, e.g.
    ``pk``),
    so rows leaving or joining earlier pages neither skip nor repeat
    others (fixed 2026-11-28; ninja's ``CursorPagination`` positions by the
    first field and an offset). ``prepare(objects)`` sees the page's
    objects before they are mapped, to load what they need with one
    query."""
    size = PAGE_SIZE if page_size is None else min(MAX_PAGE_SIZE, max(1, page_size))
    position, reverse, inclusive = _decode_cursor(cursor, len(ordering))
    order = _reversed(ordering) if reverse else ordering
    queryset = queryset.order_by(*order)
    if position is not None:
        try:
            queryset = queryset.filter(_after(order, position, inclusive=inclusive))
        except (DjangoValidationError, TypeError, ValueError) as error:
            raise HttpError(400, gettext("Invalid cursor.")) from error
    try:
        rows = list(queryset[: size + 1])
    except DataError as error:
        raise HttpError(400, gettext("Invalid cursor.")) from error
    more = len(rows) > size
    objects = rows[:size]
    if reverse:
        objects.reverse()

    def link(position, *, reverse, inclusive=False):
        value = {"p": position, "r": reverse} | ({"i": True} if inclusive else {})
        return _with_cursor(request, _encode_cursor(value))

    if objects:
        first, last = _position(objects[0], ordering), _position(objects[-1], ordering)
        next_ = link(last, reverse=False) if more or reverse else None
        previous = (
            link(first, reverse=True)
            if (more if reverse else position is not None)
            else None
        )
    else:
        # Beyond either end: back (or on) from where the cursor pointed
        next_ = link(position, reverse=False, inclusive=True) if reverse else None
        previous = (
            link(position, reverse=True, inclusive=True)
            if not reverse and position is not None
            else None
        )
    if prepare is not None:
        prepare(objects)
    return {
        "next": next_,
        "previous": previous,
        "results": [out(obj) for obj in objects],
    }


def _reversed(ordering):
    return tuple(f[1:] if f.startswith("-") else f"-{f}" for f in ordering)


def _position(obj, ordering):
    """The values of ``ordering`` of a row, JSON-ready"""
    values = []
    for field in ordering:
        value = obj
        for name in field.removeprefix("-").split("__"):
            value = getattr(value, name)
        if value is None:
            raise ValueError(f"{field} is null: coalesce it for the cursor")
        if isinstance(value, dt.date):  # Datetimes too
            value = value.isoformat()
        values.append(value)
    return values


def _after(ordering, position, *, inclusive):
    """Rows after ``position`` in ``ordering``"""
    condition = Q(pk__in=[])
    equal = Q()
    for field, value in zip(ordering, position, strict=True):
        name = field.removeprefix("-")
        lookup = "lt" if field.startswith("-") else "gt"
        condition |= equal & Q(**{f"{name}__{lookup}": value})
        equal &= Q(**{name: value})
    return condition | equal if inclusive else condition


def _encode_cursor(value):
    data = json.dumps(value, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _decode_cursor(cursor, length):
    """``(position, reverse, inclusive)``; cursors of ninja's paginator (used
    before 2026-11-28) are invalid"""
    if not cursor:
        return None, False, False
    try:
        value = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        position, reverse = value["p"], value["r"]
        inclusive = value.get("i", False)
        if not (
            isinstance(position, list)
            and len(position) == length
            and isinstance(reverse, bool)
            and isinstance(inclusive, bool)
            and all(
                isinstance(v, int | str) and not isinstance(v, bool) for v in position
            )
        ):
            raise ValueError(cursor)
    except (ValueError, TypeError, KeyError, binascii.Error) as error:
        raise HttpError(400, gettext("Invalid cursor.")) from error
    return position, reverse, inclusive


def _with_cursor(request, cursor):
    """The request's URL with ``cursor``, its other parameters kept"""
    scheme, netloc, path, query, fragment = urlsplit(request.build_absolute_uri())
    params = parse_qs(query, keep_blank_values=True) | {"cursor": [cursor]}
    return urlunsplit((
        scheme,
        netloc,
        path,
        urlencode(sorted(params.items()), doseq=True),
        fragment,
    ))


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
