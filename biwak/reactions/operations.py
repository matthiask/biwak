"""Reactions (specs/reactions.md). Visibility is the caller's: it found
the item through ``item_for()``."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Prefetch, Q, prefetch_related_objects
from django.utils.translation import gettext as _

from biwak.activity.models import Action, Event, Notification
from biwak.activity.operations import record
from biwak.live import announce as live
from biwak.reactions.emoji import MAX_LENGTH
from biwak.reactions.models import Reaction, can_react


def clean_content(content):
    content = " ".join(content.split())
    if not content:
        raise ValidationError(_("The reaction is empty."))
    if len(content) > MAX_LENGTH:
        raise ValidationError(
            _("A reaction has at most %(max)d characters.") % {"max": MAX_LENGTH}
        )
    return content


def _target(item, comment):
    if (item is None) == (comment is None):
        raise ValueError("A reaction is on an item or a comment.")
    if comment is not None:
        item = comment.item
    if not can_react(item, comment):
        raise ValidationError(_("You can't react to this."))
    return item


def _event_data(content, comment):
    return {"content": content} | ({"comment": comment.pk} if comment else {})


@transaction.atomic
def add_reaction(user, content, *, item=None, comment=None):
    """Idempotent; returns whether it was added. Records the event the
    author is told about (collected into their next mail or the digest,
    biwak.activity.notify)."""
    content = clean_content(content)
    item = _target(item, comment)
    _reaction, created = Reaction.objects.get_or_create(
        user=user, item=item, comment=comment, content=content
    )
    if created:
        record(
            actor=user,
            action=Action.REACTED,
            project=item.project,
            item=item,
            **_event_data(content, comment),
        )
    return created


@transaction.atomic
def remove_reaction(user, content, *, item=None, comment=None):
    """Only your own; returns whether there was one. Records nothing and
    takes the reaction out of the feed and out of the author's mail, if it
    isn't sent yet (the event and its notifications go; a sent mail stays
    sent)."""
    content = " ".join(content.split())
    item = _target(item, comment)
    deleted, _rows = Reaction.objects.filter(
        user=user, item=item, comment=comment, content=content
    ).delete()
    if deleted:
        events = Event.objects.filter(
            actor=user, item=item, action=Action.REACTED, data__content=content
        )
        if comment is None:
            events = events.filter(data__comment__isnull=True)
        else:
            events = events.filter(data__comment=comment.pk)
        # Those who see the item, clients only about events they saw
        told = (
            Notification.objects
            .filter(event__in=events)
            .filter(Q(user__is_client=False) | Q(event__is_client_visible=True))
            .values_list("user", flat=True)
        )
        live.lantern_changed(list(told), item=item)
        events.delete()
        live.changed(item, action=Action.REACTED, actor=user)
    return bool(deleted)


@transaction.atomic
def toggle_reaction(user, content, *, item=None, comment=None):
    """The same reaction again removes it; returns whether it's there now"""
    content = clean_content(content)
    target = {"item": item, "comment": comment}
    if remove_reaction(user, content, **target):
        return False
    add_reaction(user, content, **target)
    return True


def summary(item, comment, user):
    """What's shown under the thing: one entry per distinct content, in the
    order of the first reaction: ``{content, count, people, mine, words}``
    (``words``: a few words rather than emojis, shown at the text's size)"""
    found = {}
    comment_id = comment.pk if comment else None
    rows = item.reactions.all()
    if "reactions" not in getattr(item, "_prefetched_objects_cache", {}):
        rows = rows.select_related("user__organization")
    for reaction in rows:
        if reaction.comment_id != comment_id:
            continue
        entry = found.setdefault(
            reaction.content,
            {
                "content": reaction.content,
                "count": 0,
                "people": [],
                "mine": False,
                "words": any(c.isalnum() for c in reaction.content),
            },
        )
        entry["count"] += 1
        entry["people"].append(reaction.user)
        entry["mine"] |= reaction.user_id == user.pk
    return list(found.values())


def prefetch(*items):
    """Loads the reactions of items (or of the item of its comments) with
    one query, so ``reactions_out()`` doesn't query for each"""
    prefetch_related_objects(
        items,
        Prefetch(
            "reactions", queryset=Reaction.objects.select_related("user__organization")
        ),
    )
