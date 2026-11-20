"""Mentions in texts: ``[@Ada Lovelace](person:12)`` (specs/notifications.md)

The syntax of the Basecamp CLI, so agents know it. The label is only a
fallback: pages and mails show the person's current name, as long as the
person can see the item; a mention of somebody who can't (typed by hand) is
shown as plain text.
"""

import re

from django.db import models
from django.utils.translation import gettext as _

from biwak.accounts.models import User
from biwak.activity.models import Mention
from biwak.activity.operations import subscribe


MENTION = re.compile(r"\[@([^\]\n]*)\]\(person:(\d+)\)")
# What the API (and later mail replies) may write instead of the syntax:
# ``@ada@example.org``, or ``@Ada`` when exactly one person matches
MENTION_EMAIL = re.compile(r"(?<![\w@\[])@([\w.+-]+@[\w-]+(?:\.[\w-]+)+)")
MENTION_NAME = re.compile(r"(?<![\w@\[])@([^\W\d_][\w-]*)(?![\w@-])")

# How many people the list offers at most
LIMIT = 10


def syntax(user):
    return f"[@{user}](person:{user.pk})"


def mentioned_ids(text):
    return {int(match[2]) for match in MENTION.finditer(text or "")}


def mentionable_people(item):
    """Active people who can see the item, the same rules as
    ``Item.objects.visible_to()``: members of the project, all staff in
    all-access projects, clients only if they're members and the item is
    visible to clients"""
    return people_who_see(item.project, item.is_client_visible)


def people_who_see(project, visible):
    """The same for an item that doesn't exist yet"""
    staff = models.Q(is_client=False)
    if not project.is_all_access:
        staff &= models.Q(memberships__project=project)
    can_see = staff
    if visible:
        can_see |= models.Q(is_client=True, memberships__project=project)
    return User.objects.active().filter(can_see).distinct()


def visible_names(item, ids):
    """The current names of those people who can see the item, by ID"""
    if not ids:
        return {}
    return {user.pk: str(user) for user in mentionable_people(item).filter(pk__in=ids)}


def plain(text, item=None):
    """The mentions as ``@`` and the current name, for mails, titles and
    plain text; without an item (or for people who can't see it) the label"""
    text = str(text or "")
    names = visible_names(item, mentioned_ids(text)) if item is not None else {}
    return MENTION.sub(lambda m: f"@{names.get(int(m[2]), m[1])}", text)


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
    if not for_user.is_client:
        people = User.objects.active().filter(
            models.Q(memberships__project=project) | models.Q(is_client=False)
        )
    fields = ["full_name", "short_name"] + ([] if for_user.is_client else ["email"])
    for word in query.split():
        q = models.Q()
        for field in fields:
            q |= models.Q(**{f"{field}__icontains": word})
        people = people.filter(q)
    people = list(people.distinct().order_by("full_name", "email")[:200])
    available = set(
        people_who_see(project, visible)
        .filter(pk__in=[p.pk for p in people])
        .values_list("pk", flat=True)
    )
    members = set(
        project.memberships.filter(user__in=people).values_list("user", flat=True)
    )

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
            "short_name": user.get_short_name(),
            "email": "" if for_user.is_client else user.email,
            "available": user.pk in available,
            "reason": reason(user),
        }
        for user in people[:LIMIT]
    ]


def resolve(item, text):
    """Turns ``@ada@example.org`` and an unambiguous ``@Ada`` into the
    syntax, for people who can see the item; anything else stays as it
    is (the API, later mail replies)"""
    if "@" not in (text or ""):
        return text
    people = list(mentionable_people(item))
    by_email = {user.email.lower(): user for user in people}

    def email(match):
        user = by_email.get(match[1].lower())
        return syntax(user) if user else match[0]

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
        return syntax(found[0]) if len(found) == 1 else match[0]

    # Not inside the syntax: split it out first
    parts = MENTION.split(text)
    result = []
    for index in range(0, len(parts), 3):
        chunk = MENTION_EMAIL.sub(email, parts[index])
        result.append(MENTION_NAME.sub(name, chunk))
        if index + 2 < len(parts):
            result.append(f"[@{parts[index + 1]}](person:{parts[index + 2]})")
    return "".join(result)


def update(item, text, *, comment=None, actor, event=None):
    """Stores who ``text`` (an item's texts, or ``comment``) mentions, from
    the operations saving texts. Only people who can see the item count;
    those newly mentioned are subscribed (even after unsubscribing) and
    added to ``event.data["mentioned"]``, so ``notify()`` tells them.
    People no longer mentioned are forgotten: mentioning them again counts
    as new. Returns those newly mentioned."""
    ids = mentioned_ids(text)
    mentions = Mention.objects.filter(item=item, comment=comment)
    mentions.exclude(user__in=ids).delete()
    known = set(mentions.values_list("user", flat=True))
    people = [
        user
        for user in mentionable_people(item).filter(pk__in=ids)
        if user.pk not in known
    ]
    Mention.objects.bulk_create([
        Mention(item=item, comment=comment, user=user) for user in people
    ])
    newly = [user for user in people if user != actor]
    for user in newly:
        subscribe(user, item, added_by=actor)
    if event is not None and newly:
        mentioned = set(event.data.get("mentioned", []))
        event.data["mentioned"] = sorted(mentioned | {user.pk for user in newly})
        event.save(update_fields=["data"])
    return newly
