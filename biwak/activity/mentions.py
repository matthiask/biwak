"""Mentions in texts: ``[@Ada](person:12)`` (specs/notifications.md)

The syntax of the Basecamp CLI, so agents know it. The label is only a
fallback: pages and mails show the person's current name, as long as the
person can see the item; a mention of somebody who can't (typed by hand) is
shown as plain text.

Clients learn about the project's members only (specs/access.md): their
``@`` resolves and notifies members only, and they read the label as
written for anybody else, never the current name. Externals learn about the
project's people (members and the staff with access) in the projects
they're in (``known_to()``). Who reads is
``reader()``: the person of the request (the middleware, also for API
tokens) or of the mail (``reading_as()``); nobody set reads like a client.
"""

import re
from contextlib import contextmanager
from contextvars import ContextVar

from django.db import models
from django.utils.translation import gettext as _

from biwak.accounts.models import User
from biwak.activity.models import Mention
from biwak.activity.notify import people_who_see
from biwak.activity.operations import is_importing, subscribe
from biwak.organizations.names import display_name, display_names
from biwak.projects.models import knows_everybody, knows_people_of


MENTION = re.compile(r"\[@([^\]\n]*)\]\(person:(\d+)\)")
# What the API (and later mail replies) may write instead of the syntax:
# ``@ada@example.org``, or ``@Ada`` when exactly one person matches
MENTION_EMAIL = re.compile(r"(?<![\w@\[])@([\w.+-]+@[\w-]+(?:\.[\w-]+)+)")
MENTION_NAME = re.compile(r"(?<![\w@\[])@([^\W\d_][\w-]*)(?![\w@-])")

# How many people the list offers at most
LIMIT = 10

# A function returning who reads the texts rendered now (see reader())
_reader = ContextVar("mention_reader", default=None)


@contextmanager
def reading_as(person):
    """Renders texts for ``person``, or for whoever a function returns
    (the request's user, set late by the API's token authentication)"""
    token = _reader.set(person if callable(person) else lambda: person)
    try:
        yield
    finally:
        _reader.reset(token)


def reader():
    """Who reads the texts rendered now, or None"""
    get = _reader.get()
    return get() if get else None


def known_to(people, project, person):
    """Those of ``people`` (a queryset) the person may learn about:
    ``Project.people_known_to()`` for querysets"""
    if knows_everybody(person):
        return people
    if knows_people_of(person, project):
        return people.filter(project.people_q())
    return people.filter(pk__in=project.memberships.values("user"))


def syntax(user, viewer=None):
    """The mention with the name the viewer (the one typing) sees"""
    return f"[@{display_name(user, viewer)}](person:{user.pk})"


def mentioned_ids(text):
    return {int(match[2]) for match in MENTION.finditer(text or "")}


def mentionable_people(item):
    """Active people who can see the item (``notify.people_who_see()``):
    members of the project, all staff in all-access projects, clients only
    if they're members and the item is visible to clients"""
    return people_who_see(item.project, item.is_client_visible)


def visible_people(item, ids):
    """Those people who can see the item and whom the reader may know, by ID"""
    if not ids:
        return {}
    people = known_to(
        mentionable_people(item).filter(pk__in=ids), item.project, reader()
    )
    return {user.pk: user for user in people}


def plain(text, item=None):
    """The mentions as ``@`` and the current short name ("@Ada"), for
    mails, titles and plain text; without an item (or for people who can't
    see it) the label"""
    text = str(text or "")
    people = visible_people(item, mentioned_ids(text)) if item is not None else {}

    def show(match):
        user = people.get(int(match[2]))
        return f"@{display_name(user, reader()) if user else match[1]}"

    return MENTION.sub(show, text)


def title(text, item=None):
    """A title as ``plain()`` shows it; "Untitled" for a doc without one
    (stored empty, specs/files.md)"""
    return plain(text, item) or _("Untitled")


def candidates(item, query, *, for_user):
    """The ``@`` list: people matching ``query``, those who can see the item
    first; the others greyed out with the reason. Clients only find the
    project's members and not by email, and don't see addresses."""
    return candidates_for(
        item.project, item.is_client_visible, query, for_user=for_user
    )


def candidates_for(project, visible, query, *, for_user):
    """The same for a new item of ``project``, visible to clients or not"""
    people = User.objects.active().filter(memberships__project=project)
    if knows_everybody(for_user):
        people = User.objects.active().filter(
            models.Q(memberships__project=project) | models.Q(is_client=False)
        )
    elif knows_people_of(for_user, project):
        # Externals: the project's people, nobody from outside it
        people = User.objects.active().filter(project.people_q())
    fields = ["full_name", "short_name"] + ([] if for_user.is_client else ["email"])
    for word in query.split():
        q = models.Q()
        for field in fields:
            q |= models.Q(**{f"{field}__icontains": word})
        people = people.filter(q)
    people = list(
        people
        .distinct()
        .select_related("organization")
        .order_by("full_name", "email")[:200]
    )
    available = set(
        people_who_see(project, visible)
        .filter(pk__in=[p.pk for p in people])
        .values_list("pk", flat=True)
    )
    members = set(
        project.memberships.filter(user__in=people).values_list("user", flat=True)
    )

    names = display_names(for_user)

    def reason(user):
        if user.pk in available:
            return ""
        if user.pk not in members:
            return _("not a member of this project")
        return _("can't see internal items")

    people.sort(key=lambda user: user.pk not in available)
    return [
        {
            "id": user.pk,
            "name": str(user),
            "organization": user.organization_name,
            "short_name": names.get(user.pk) or user.get_short_name(),
            "avatar": user.avatar_data,
            "email": "" if for_user.is_client else user.email,
            "available": user.pk in available,
            "reason": reason(user),
        }
        for user in people[:LIMIT]
    ]


def resolve(item, text, *, author):
    """Turns ``@ada@example.org`` and an unambiguous ``@Ada`` into the
    syntax, for people who can see the item and whom the author may know;
    anything else stays as it is (the API, mail replies)"""
    if "@" not in (text or ""):
        return text
    people = list(known_to(mentionable_people(item), item.project, author))
    by_email = {user.email.lower(): user for user in people}

    def email(match):
        user = by_email.get(match[1].lower())
        return syntax(user, author) if user else match[0]

    def name(match):
        word = match[1].lower()
        found = [
            user
            for user in people
            if word
            in {
                user.get_short_name().lower(),
                (user.full_name.split(" ")[0] if user.full_name else "").lower(),
            }
        ]
        return syntax(found[0], author) if len(found) == 1 else match[0]

    # Not inside the syntax: split it out first
    parts = MENTION.split(text)
    result = []
    for index in range(0, len(parts), 3):
        chunk = MENTION_EMAIL.sub(email, parts[index])
        result.append(MENTION_NAME.sub(name, chunk))
        if index + 2 < len(parts):
            result.append(f"[@{parts[index + 1]}](person:{parts[index + 2]})")
    return "".join(result)


def update(item, text, *, comment=None, actor, event=None, previous="", credit=None):
    """Stores who ``text`` (an item's texts, or ``comment``) mentions, from
    the operations saving texts. Only people who can see the item and
    whom the one who typed the mention may know count (clients: the
    members), and only those this save adds: mentions already in
    ``previous`` (the text before) were looked at when they were written,
    also the rejected ones; those newly mentioned are subscribed (even
    after unsubscribing) and added to ``event.data["mentioned"]``, so
    ``notify()`` tells them. People no longer mentioned are forgotten:
    mentioning them again counts as new. ``credit`` gives others than
    ``actor`` and ``event`` the mentions they typed: ``{mentioned person's
    ID: (actor, event)}`` (docs edited live by several people). Returns
    those newly mentioned."""
    ids = mentioned_ids(text)
    mentions = Mention.objects.filter(item=item, comment=comment)
    mentions.exclude(user__in=ids).delete()
    known = set(mentions.values_list("user", flat=True)) | mentioned_ids(previous)
    credit = credit or {}
    known_ids = {}

    def known_by(by, user):
        """Whether ``by`` may know ``user`` (``known_to()``), once per ``by``"""
        key = by.pk if by is not None else None
        if key not in known_ids:
            known_ids[key] = set(
                known_to(User.objects.filter(pk__in=ids), item.project, by).values_list(
                    "pk", flat=True
                )
            )
        return user.pk in known_ids[key]

    people = []
    for user in mentionable_people(item).filter(pk__in=ids):
        if user.pk in known:
            continue
        by, by_event = credit.get(user.pk, (actor, event))
        if not is_importing() and not known_by(by, user):
            continue
        people.append((user, by, by_event))
    Mention.objects.bulk_create([
        Mention(item=item, comment=comment, user=user) for user, _by, _e in people
    ])
    newly = []
    # Event ID: (event, IDs of those it newly mentions)
    told = {}
    # Being mentioned subscribes (specs/notifications.md, "Subscriptions")
    for user, by, by_event in people:
        if user == by:
            continue
        newly.append(user)
        subscribe(user, item, added_by=by)
        if by_event is not None:
            told.setdefault(by_event.pk, (by_event, set()))[1].add(user.pk)
    for told_event, told_ids in told.values():
        mentioned = set(told_event.data.get("mentioned", []))
        told_event.data["mentioned"] = sorted(mentioned | told_ids)
        told_event.save(update_fields=["data"])
    return newly
