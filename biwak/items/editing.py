"""Who has an item's edit form open, and who changed its text last
(specs/editor.md, "Ticking while someone edits")

The forms announce themselves with a row per item and person
(``Editing``): ``start()`` when the form opens and every minute after,
``stop()`` when it's saved or cancelled; a row counts for ``TTL`` after its
last renewal, so a closed tab stops blocking ticks by itself. The rows
live in the database (not the cache) so that every process agrees.
"""

import datetime as dt

from django.utils import timezone
from django.utils.timesince import timesince
from django.utils.translation import gettext as _

from biwak import checklists
from biwak.activity.models import Action, Event
from biwak.items.models import Editing, Item, Kind
from biwak.organizations.names import display_name


TTL = dt.timedelta(minutes=2)


class BeingEdited(Exception):
    """Somebody has the form open, so the item's text isn't ticked now"""

    def __init__(self, users):
        super().__init__(", ".join(str(user) for user in users))
        self.users = users


class StaleEdit(Exception):
    """Somebody saved the text since the form was opened; ``who`` is the
    person (or None) and ``when`` the time of the last change"""

    def __init__(self, who, when):
        super().__init__(f"{who} changed it at {when}")
        self.who = who
        self.when = when


def start(item, user, *, now=None):
    """The form is open (again)"""
    Editing.objects.update_or_create(
        item=item, user=user, defaults={"seen_at": now or timezone.now()}
    )


def stop(item, user):
    """The form is saved or cancelled"""
    Editing.objects.filter(item=item, user=user).delete()


def holders(item, *, now=None):
    """The people with the item's form open, longest first"""
    since = (now or timezone.now()) - TTL
    rows = (
        Editing.objects
        .filter(item=item, seen_at__gt=since)
        .select_related("user")
        .order_by("seen_at", "pk")
    )
    return [row.user for row in rows]


def prune(*, now=None):
    """Deletes the expired rows (the daily job)"""
    since = (now or timezone.now()) - TTL
    return Editing.objects.filter(seen_at__lte=since).delete()[0]


# Versions of the text ---------------------------------------------------


def _title_and_text(item):
    from biwak.items import operations as ops

    item = Item.objects.select_related(
        *([ops.TEXT_FIELDS[item.kind][0]] if item.kind in ops.TEXT_FIELDS else [])
    ).get(pk=item.pk)
    return f"{item.title}\n{ops.text_of(item)}"


def version(item):
    """What an edit form carries from when it opened: the hash of the
    title and text as they are now"""
    return checklists.text_hash(_title_and_text(item))


def check_base(item, base, *, actor):
    """Raises ``StaleEdit`` if the title and text changed since the form
    (which carried ``base``) opened; no ``base``, no check. Call it with
    the detail row locked."""
    if not base:
        return
    if version(item) != base:
        who, when = last_change(item)
        raise StaleEdit(who, when)


def last_change(item):
    """``(person, time)`` of the last edit; the person is None if nobody is
    known (a text that was never edited has its creation)"""
    event = (
        Event.objects
        .filter(item=item, action=Action.EDITED)
        .select_related("actor")
        .order_by("-created_at", "-pk")
        .first()
    )
    if event is None:
        return item.creator, item.created_at
    return event.actor, event.created_at


# Messages -----------------------------------------------------------------


def name_for(viewer, project, person):
    """The person's name if the viewer may know them (clients only know the
    project's members), else None"""
    if person is None or not project.people_known_to(viewer, [person]):
        return None
    return display_name(person, viewer)


def ago(when, *, now=None):
    """One unit, like the ``ago`` filter (decided 2026-11-22)"""
    now = now or timezone.now()
    if now - when < dt.timedelta(minutes=1):
        return _("a moment ago")
    return _("%(time)s ago") % {"time": timesince(when, now, depth=1)}


def being_edited_message(viewer, project, users):
    """Why a tick is refused. ``users`` have the form open; the viewer's
    own form counts too."""
    others = [user for user in users if user.pk != viewer.pk]
    if not others:
        return _("You have the edit form of this open; save or cancel it first.")
    if len(others) > 1:
        return _("Several people are editing this; try again when they're done.")
    name = name_for(viewer, project, others[0])
    if name is None:
        return _("Someone is editing this; try again when they're done.")
    return _("%(name)s is editing this; try again when they're done.") % {"name": name}


def heads_up(viewer, project, users):
    """What a page tells about the others editing the item (docs, decided
    2026-11-21: no locks, only a heads-up), or None"""
    others = [user for user in users if user.pk != viewer.pk]
    if not others:
        return None
    if len(others) > 1:
        return _("Several people are editing this.")
    name = name_for(viewer, project, others[0])
    if name is None:
        return _("Someone is editing this.")
    return _("%(name)s is editing this.") % {"name": name}


def changed_message(viewer, project, who, when):
    """Why a tick on an old text is refused: "Changed by Bob a moment ago" """
    name = name_for(viewer, project, who)
    when = ago(when)
    if viewer.pk == getattr(who, "pk", None):
        return _("Changed by you %(when)s.") % {"when": when}
    if name is None:
        return _("Changed by someone %(when)s.") % {"when": when}
    return _("Changed by %(name)s %(when)s.") % {"name": name, "when": when}


def stale_message(viewer, project, who, when):
    """Why the edit form refuses a save"""
    name = name_for(viewer, project, who)
    when = ago(when)
    if viewer.pk == getattr(who, "pk", None):
        return _(
            "You changed this %(when)s (elsewhere), so your changes weren't saved."
            " Copy your text, then reload the page."
        ) % {"when": when}
    return _(
        "%(name)s changed this %(when)s, while you were editing, so your"
        " changes weren't saved. Copy your text, then reload the page."
    ) % {"name": name or _("Someone"), "when": when}


EDITABLE = {Kind.TODO, Kind.MESSAGE, Kind.DOC, Kind.FILE, Kind.ANSWER}
