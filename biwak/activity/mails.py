"""Notification mails (specs/notifications.md): one mail per person and
item once its newest notification is 10 minutes old, or a daily digest at
07:00. ``./manage.py send_mails`` runs ``send_mails()`` every minute."""

import datetime as dt
import logging
import re
from email.utils import formataddr, make_msgid, parseaddr
from itertools import groupby
from urllib.parse import urlsplit

from django.conf import settings
from django.core import signing
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.db.models import Q
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.formats import date_format
from django.utils.translation import gettext as _, ngettext

from biwak.accounts.languages import language_for
from biwak.accounts.models import MailDelivery, User
from biwak.activity import digest, feed, mentions
from biwak.activity.models import Action, Notification
from biwak.activity.operations import is_subscribed
from biwak.api_conventions import absolute
from biwak.files.models import REFERENCE, Attachment
from biwak.inbound.tokens import reply_to
from biwak.items.models import Comment, Item, Kind
from biwak.outbox import sending as outbox
from biwak.outbox.models import Kind as MailKind


logger = logging.getLogger(__name__)

# Quick edits and several comments merge into one mail (decided 2026-11-20;
# 10 minutes since 2026-11-21: urgent things get a call, the lantern is
# immediate)
MERGE_AFTER = dt.timedelta(minutes=10)
# Files of a batch still going up (``more`` on the newest one's event):
# its mail waits for them, but no longer than this after the newest
# arrived (the rest failed, or the tab was closed)
BATCH_WAIT = dt.timedelta(hours=1)
# Digests in the installation's time zone (decided 2026-11-20)
DIGEST_AT = dt.time(7, 0)

_SALT = "biwak.unsubscribe"


# Unsubscribing with one click, without logging in -------------------------


def unsubscribe_token(user, item):
    return signing.dumps([user.pk, item.pk], salt=_SALT)


def read_unsubscribe_token(token):
    """``(person ID, item ID)``, or None for a token we didn't sign"""
    try:
        user_pk, item_pk = signing.loads(token, salt=_SALT)
    except signing.BadSignature, ValueError, TypeError:
        return None
    return user_pk, item_pk


def unsubscribe_url(user, item):
    """For the item the person follows: the item, or for a new item the
    container they're subscribed to"""
    if not is_subscribed(user, item) and item.parent_id:
        parent = item.parent
        if is_subscribed(user, parent):
            item = parent
    return absolute(reverse("unsubscribe", args=[unsubscribe_token(user, item)]))


# What the mails show --------------------------------------------------------


def host():
    return urlsplit(settings.BASE_URL).hostname or "localhost"


def sender(name):
    """``"Ada Lovelace (Biwak)" <DEFAULT_FROM_EMAIL>``"""
    return formataddr((name, parseaddr(settings.DEFAULT_FROM_EMAIL)[1]))


# ``[name](attachment:KEY)`` and ``![name](attachment:KEY)`` as a whole
LABELLED_REFERENCE = re.compile(rf"!?\[(?:\\.|[^\]\\])*\]\({REFERENCE.pattern}\)")


_TASK = re.compile(
    r"^((?:[ \t]|>)*(?:[-*+]|\d+[.)])[ \t]+)\[([ xX])\](?=[ \t])", re.MULTILINE
)


def _task_glyphs(text):
    """Task lists in the plain text part: ``- [ ] a`` as ``- ☐ a``"""
    return _TASK.sub(lambda m: m[1] + ("\u2610" if m[2] == " " else "\u2611"), text)


def plain_text(text, item):
    """A text for the plain text part: mentions as ``@`` and the current
    name, the item's attachments (``attachment:KEY``) as their download
    URLs; the download checks access, as on the pages. References to other
    items' attachments become a plain "attachment", without their names
    (``render_markdown()``)."""
    text = _task_glyphs(mentions.plain(text, item))
    keys = set(REFERENCE.findall(text))
    if not keys:
        return text
    urls = {
        a.key: absolute(a.get_absolute_url())
        for a in Attachment.objects.filter(key__in=keys, item=item)
    }

    def foreign(match):
        if match[1] in urls:
            return match[0]
        return _("attachment")

    text = LABELLED_REFERENCE.sub(foreign, text)
    return REFERENCE.sub(lambda m: urls.get(m[1], _("attachment")), text)


def _names(ids, user, item):
    """The people the reader may know (clients and externals: members,
    specs/access.md)"""
    people = item.project.people_known_to(user, User.objects.filter(pk__in=ids))
    return ", ".join(_("you") if person == user else str(person) for person in people)


def _moved(event, user):
    """The text of a move and where to: the list only if the viewer may see
    it now (like the feed); a group of its own list is as visible as the
    to-do"""
    if not hasattr(event, "target_list"):
        feed.add_target_lists([event], user)
    to = event.data.get("group") or event.target_list
    if to:
        return _("%(actor)s moved it to %(to)s."), to
    if "group" in event.data:
        return _("%(actor)s moved it out of its group."), ""
    return _("%(actor)s moved it."), ""


def describe(event, user):
    """The line saying what happened"""
    data = event.data
    actor = str(event.actor)
    to = data.get("to", "")
    match event.action:
        case Action.CREATED if event.item.kind == Kind.ANSWER:
            text = _("%(actor)s answered.")
        case Action.CREATED:
            text = _("%(actor)s added it.")
        case Action.EDITED:
            text = _("%(actor)s changed it.")
        case Action.COMPLETED:
            text = _("%(actor)s completed it.")
        case Action.REOPENED:
            text = _("%(actor)s reopened it.")
        case Action.ASSIGNED:
            # Assigned and mentioned by the same change: one line
            text = (
                _("%(actor)s assigned %(people)s (and mentioned you).")
                if user.pk in data.get("mentioned", ())
                else _("%(actor)s assigned %(people)s.")
            )
            return text % {
                "actor": actor,
                "people": _names(data.get("assignees", ()), user, event.item),
            }
        case Action.UNASSIGNED:
            return _("%(actor)s removed %(people)s.") % {
                "actor": actor,
                "people": _names(data.get("assignees", ()), user, event.item),
            }
        case Action.SHARED:
            text = (
                _("%(actor)s wants you to see this: %(note)s")
                if data.get("note")
                else _("%(actor)s wants you to see this.")
            )
            return text % {"actor": actor, "note": data.get("note", "")}
        case Action.COMMENTED:
            text = _("%(actor)s commented:")
        case Action.MOVED:
            text, to = _moved(event, user)
        case Action.VISIBILITY_CHANGED:
            text = (
                _("%(actor)s made it visible to clients.")
                if data.get("visible")
                else _("%(actor)s hid it from clients.")
            )
        case Action.ARCHIVED:
            text = _("%(actor)s archived it.")
        case Action.UNARCHIVED:
            text = _("%(actor)s brought it back from the archive.")
        case Action.RESTORED:
            text = _("%(actor)s restored it from the trash.")
        case _:
            return _other(event, actor)
    return text % {"actor": actor, "to": mentions.plain(to or "")}


def _other(event, actor):
    """``describe()`` of the rest: to-dos added from text
    (specs/todos-from-text.md), else the action's name"""
    if event.action == Action.ADDED_TODOS:
        count = event.data.get("todos", 0)
        return ngettext(
            "%(actor)s added %(count)d to-do.",
            "%(actor)s added %(count)d to-dos.",
            count,
        ) % {"actor": actor, "count": count}
    return f"{actor} {event.get_action_display()}."


def _reactions(notifications, user):
    """Reactions collected into one entry per thing reacted to (the item, a
    comment or completing the to-do), oldest first: "Bea: 👍 🎉, Carl:
    Thanks!" (specs/reactions.md)"""
    by_target = {}
    for notification in sorted(notifications, key=lambda n: n.event.created_at):
        event = notification.event
        if comment_id := event.data.get("comment"):
            target = ("comment", comment_id)
        elif completed := event.data.get("event"):
            target = ("event", completed)
        else:
            target = ("item", None)
        by_target.setdefault(target, []).append(event)
    comments = Comment.objects.in_bulk([
        pk for kind, pk in by_target if kind == "comment"
    ])
    entries = []
    for (kind, pk), events in by_target.items():
        comment = comments.get(pk) if kind == "comment" else None
        if kind == "comment" and comment is None:
            continue
        item = events[0].item
        people = {}
        for event in events:
            people.setdefault(event.actor, []).append(event.data["content"])
        reactions = ", ".join(
            f"{person}: {' '.join(contents)}" for person, contents in people.items()
        )
        entries.append({
            "event": events[-1],
            "line": {
                "comment": _("Reactions to your comment:"),
                "event": _("Reactions to you completing it:"),
            }.get(kind, _("Reactions:")),
            "reactions": reactions,
            "comment": comment,
            "comment_text": plain_text(comment.content, item) if comment else "",
        })
    return entries


def _entries(notifications, user):
    """What happened, oldest first, comments with their text; the reactions
    at the end, one entry per thing reacted to"""
    reacted = [n for n in notifications if n.event.action == Action.REACTED]
    notifications = [n for n in notifications if n.event.action != Action.REACTED]
    comment_ids = [
        n.event.data.get("comment")
        for n in notifications
        if n.event.action == Action.COMMENTED
    ]
    comments = Comment.objects.in_bulk([pk for pk in comment_ids if pk])
    feed.add_target_lists([n.event for n in notifications], user)
    entries = []
    for notification in sorted(notifications, key=lambda n: n.event.created_at):
        event = notification.event
        comment = comments.get(event.data.get("comment"))
        entries.append({
            "event": event,
            "line": describe(event, user),
            "comment": comment,
            "comment_text": plain_text(comment.content, event.item) if comment else "",
        })
    return entries + _reactions(reacted, user)


def _item(item, user):
    """The item with its full text"""
    context = {
        "item": item,
        "title": mentions.title(item.title, item),
        "url": absolute(item.get_absolute_url()),
        "project": item.project,
        "kind": Kind(item.kind).label,
        "text": "",
        "unsubscribe_url": unsubscribe_url(user, item),
    }
    if item.kind == Kind.TODO:
        todo = item.todo
        context |= {
            "text": todo.notes,
            "todo": todo,
            "assignees": ", ".join(
                str(a) for a in item.project.people_known_to(user, todo.assignees.all())
            ),
            "list": mentions.plain(item.parent.title, item.parent),
        }
    elif item.kind == Kind.LIST:
        context["text"] = item.todolist.description
    elif item.kind in {Kind.MESSAGE, Kind.DOC, Kind.ANSWER}:
        context["text"] = item.detail.content
    elif item.kind == Kind.FILE:
        context["text"] = item.upload.description
    context["text_plain"] = plain_text(context["text"], item)
    return context


DONE = (Action.COMPLETED, Action.REOPENED)


def done_neighbours(queryset, notifications):
    """The unread notifications of ``queryset`` completing or reopening the
    items completed or reopened among the unread ``notifications``, but
    not those: what cancels out may be split by a page's edge, a menu's
    limit or a digest's midnight (``_deliverable(others=)``)"""
    items = {
        n.event.item_id
        for n in notifications
        if n.read_at is None and n.event.action in DONE
    }
    if not items:
        return []
    return list(
        queryset
        .filter(read_at__isnull=True, event__item__in=items, event__action__in=DONE)
        .exclude(pk__in=[n.pk for n in notifications])
        .select_related("event")
    )


def _cancelled(notifications, others):
    """The events not to tell of the unread ones: completing and reopening
    which cancel out, and moves between a list's groups back to where the
    to-do was (``timeline.moved_back()``, decided 2026-11-26)"""
    from biwak.activity.timeline import cancelled, moved_back

    events = [n.event for n in [*notifications, *others] if n.read_at is None]
    return cancelled(events) | moved_back(events)


def _deliverable(notifications, user, *, others=()):
    """Those the person may still get: the item visible to them now (which
    excludes the inactive), and for clients only events which were visible
    to clients when they happened (the same rule as ``notify()``, in case a
    notification exists anyway). Levels decided who was told
    (``notify()``); subscribing is the switch (specs/notifications.md,
    "Subscriptions"), so a level changed since doesn't hold the mail back. Item
    mails and digests both pass here, and the lantern (``lantern.wanted()``).
    Of the unread ones, those of completing and reopening which cancel out
    aren't (``timeline.cancelled()``, decided 2026-11-21), nor moves back
    to where the to-do was (``_cancelled()``): the net change,
    if any, is the last one; ``others`` (``done_neighbours()``) are the
    neighbours to count with, outside ``notifications``. The same number of
    queries for any number of items."""
    items = {n.event.item_id: n.event.item for n in notifications if n.event.item}
    visible = set(
        Item.objects.visible_to(user).filter(pk__in=items).values_list("pk", flat=True)
    )
    hidden = _cancelled(notifications, others)
    return [
        notification
        for notification in notifications
        if notification.event.item_id in visible
        and (notification.event.is_client_visible or not user.is_client)
        and not (notification.read_at is None and notification.event_id in hidden)
    ]


# Notifications still to mail: not sent, not read in the lantern, not
# marked unread by hand there (specs/lantern.md)
MAILABLE = {
    "sent_at__isnull": True,
    "read_at__isnull": True,
    "marked_unread_at__isnull": True,
}


def _claim(pks, now):
    """Locks and marks the notifications as sent (skipping those another
    run is sending, and those read or marked unread in the lantern
    meanwhile); returns those claimed"""
    claimed = list(
        Notification.objects
        .select_for_update(skip_locked=True, of=("self",))
        .filter(pk__in=pks, **MAILABLE)
        .select_related("event__item__project", "event__actor", "user")
    )
    Notification.objects.filter(pk__in=[n.pk for n in claimed]).update(sent_at=now)
    return claimed


def build_mail(user, *, subject, template, context, from_name="Biwak", headers=None):
    """A mail to the person, plain text and HTML (``template`` plus ``.txt``
    and ``.html``), from ``"from_name" <DEFAULT_FROM_EMAIL>``, with a
    ``Message-ID`` (unless ``headers`` bring one) and ``Auto-Submitted``.
    The templates' ``can_reply`` says whether it has a ``Reply-To``."""
    headers = {
        "Message-ID": make_msgid(domain=host()),
        "Auto-Submitted": "auto-generated",
    } | (headers or {})
    context = context | {"can_reply": "Reply-To" in headers}
    message = EmailMultiAlternatives(
        subject,
        render_to_string(f"{template}.txt", context),
        sender(from_name),
        [user.email],
        headers=headers,
    )
    message.attach_alternative(
        render_to_string(f"{template}.html", context), "text/html"
    )
    return message


def unsubscribe_headers(url, *, one_click=True):
    """``List-Unsubscribe``, with ``List-Unsubscribe-Post`` (RFC 8058) when
    a POST to the URL unsubscribes"""
    headers = {"List-Unsubscribe": f"<{url}>"}
    if one_click:
        headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    return headers


def item_mail(user, item, notifications):
    """One mail about one item, threaded per item; None when there's nothing
    left to say (reactions to comments deleted since)"""
    entries = _entries(notifications, user)
    if not entries:
        return None
    context = _item(item, user) | {
        "user": user,
        "entries": entries,
        "settings_url": absolute(reverse("settings")),
    }
    thread = f"<item-{item.pk}@{host()}>"
    return build_mail(
        user,
        subject=_("[%(project)s] %(title)s") % context,
        template="mails/notification",
        context=context,
        from_name=_("%(name)s (Biwak)") % {"name": entries[-1]["event"].actor},
        headers={"In-Reply-To": thread, "References": thread}
        | unsubscribe_headers(context["unsubscribe_url"])
        | (reply_to(user, item) if item.is_commentable else {}),
    )


def _batch(notifications, user):
    """Files uploaded together (``lantern.Batch``) for a mail: the line and
    the files, each linked; None when none is left"""
    from biwak.activity.lantern import Batch

    if not notifications:
        return None
    batch = Batch(
        sorted(notifications, key=lambda n: (n.created_at, n.pk), reverse=True)
    )
    return {
        "batch": batch,
        "title": batch.title,
        "subject": batch.subject,
        "url": absolute(batch.url),
        # To-dos assigned together may be of several projects
        "project": batch.project or "Biwak",
        "line": batch.line,
        "files": [
            {
                "title": mentions.title(item.title, item),
                "url": absolute(item.get_absolute_url()),
            }
            for item in batch.files
        ],
        "is_client_visible": any(item.is_client_visible for item in batch.files),
        "entries": [],
    }


def batch_mail(user, notifications):
    """One mail about files uploaded together (specs/files.md, "Uploading files"):
    "Ada uploaded 5 files to Minutes", the files linked; or about the to-dos
    of one "Assign…" or "Due date…" (specs/handover.md): "Ada assigned you
    23 to-dos", "Ada changed the dates of 23 to-dos" """
    context = _batch(notifications, user)
    if context is None:
        return None
    context |= {"user": user, "settings_url": absolute(reverse("settings"))}
    return build_mail(
        user,
        subject=_("[%(project)s] %(subject)s") % context,
        template="mails/batch",
        context=context,
        from_name=_("%(name)s (Biwak)") % {"name": notifications[0].event.actor},
        # No item to unsubscribe from: the settings
        headers=unsubscribe_headers(context["settings_url"], one_click=False),
    )


def digest_heading(notifications):
    """ "What happened on 19. November 2026", or the days it covers when
    there's more than one (after a downtime, or switching to digests)"""
    days = sorted({timezone.localdate(n.created_at) for n in notifications})
    first, last = (
        date_format(days[0], "DATE_FORMAT"),
        date_format(days[-1], "DATE_FORMAT"),
    )
    if first == last:
        return _("What happened on %(day)s") % {"day": first}
    return _("What happened from %(first)s to %(last)s") % {
        "first": first,
        "last": last,
    }


def digest_mail(user, notifications, *, todos=None, short=True):
    """The digest (specs/notifications.md, "Digest"): with ``todos``
    (``digest.todos()``, the daily digest's) the person's to-dos needing
    them today and those they wait on first; then the notifications,
    those mentioning or assigning them in full (``digest.for_you()``),
    the rest one line per item (``short``; in full for the mail after
    quiet hours or being away of people getting a mail per change),
    grouped by project. None when there's nothing to say."""
    from biwak.activity.lantern import group_batches

    def key(notification):
        entry = getattr(notification, "batch_entry", None)
        batch = repr(entry) if entry else ""
        return (batch, 0 if batch else notification.event.item_id)

    group_batches(notifications)
    notifications = sorted(
        notifications,
        key=lambda n: (
            str(n.event.item.project).lower(),
            n.event.item.project_id,
            *key(n),
        ),
    )
    for_you = []
    projects = []
    for project, by_project in groupby(notifications, lambda n: n.event.item.project):
        items = []
        for (batch, _item_id), by_key in groupby(by_project, key):
            group = list(by_key)
            mine = any(digest.for_you(n) for n in group)
            if batch:
                # Files uploaded or to-dos assigned together: one entry
                entry = _batch(group, user) | {"short": short and not mine}
                (for_you if mine else items).append(entry)
                continue
            item = group[0].event.item
            if short and not mine:
                if line := digest.summary(group, user):
                    items.append({
                        "short": True,
                        "title": mentions.title(item.title, item),
                        "url": absolute(item.get_absolute_url()),
                        "line": line,
                        "is_client_visible": item.is_client_visible,
                    })
            elif entries := _entries(group, user):
                entry = _item(item, user) | {"entries": entries}
                (for_you if mine else items).append(entry)
        if items:
            projects.append({"project": project, "items": items})
    # The to-do sections only enrich a digest with notifications (decided
    # 2026-11-23): nothing happened, no mail
    if not (for_you or projects):
        return None
    heading = digest_heading(notifications)
    context = {
        "user": user,
        "heading": heading,
        "for_you": for_you,
        "projects": projects,
        "settings_url": absolute(reverse("settings")),
        **(todos or {}),
    }
    return build_mail(
        user,
        subject=_("[Biwak] %(heading)s") % context,
        template="mails/digest",
        context=context,
        # No one-click unsubscribing from everything: the settings page
        headers=unsubscribe_headers(context["settings_url"], one_click=False),
    )


def _mail(user, pks, now, build, kind):
    """Claims the notifications, drops those the person mustn't get any
    more, builds the mail and puts it into the outbox in the same
    transaction, which sends it after the commit (specs/mail-sending.md).
    A mail which can't be built is logged and rolled back: its
    notifications stay unsent, and the others go out."""
    try:
        with transaction.atomic():
            return _prepare(user, pks, now, build, kind)
    except Exception:
        logger.exception("Building a notification mail failed")
        return False


def _prepare(user, pks, now, build, kind):
    claimed = _claim(pks, now)
    if not claimed:
        return False
    # Completing and reopening not mailed yet, after the digest's midnight
    # too: what cancels out is never mailed, today or tomorrow
    others = done_neighbours(
        Notification.objects.filter(user=user, **MAILABLE), claimed
    )
    deliverable = _deliverable(claimed, user, others=others)
    if others:
        hidden = _cancelled(claimed, others)
        Notification.objects.filter(
            pk__in=[n.pk for n in others if n.event_id in hidden], **MAILABLE
        ).delete()
    message = None
    if deliverable:
        with (
            translation.override(language_for(user)),
            mentions.reading_as(user),
        ):
            message = build(deliverable)
    sent = [n.pk for n in deliverable] if message else []
    # Never sent: gone
    Notification.objects.filter(pk__in={n.pk for n in claimed} - set(sent)).delete()
    if message is None:
        return False
    outbox.send(message, kind)
    return True


def _groups(notifications):
    """The mails of ``notifications`` for people getting a mail per change:
    per person and item, or one person's files uploaded into one folder
    (specs/files.md) chained as the lantern does (``lantern.chain()``);
    ``{(user ID, ("item" or "batch", key)): {"pks", "newest", "more"}}``"""
    from biwak.activity.lantern import chain, todo_batch

    groups = {}
    chains = {}
    for (
        pk,
        user_id,
        item_id,
        batch,
        more,
        action,
        actor,
        project,
        parent,
        created_at,
    ) in notifications.order_by("created_at", "pk").values_list(
        "pk",
        "user",
        "event__item",
        "event__data__batch",
        "event__data__more",
        "event__action",
        "event__actor",
        "event__project",
        "event__item__parent",
        "created_at",
    ):
        if batch and (todo_batch(action) or action == Action.CREATED):
            # To-dos of one "Assign…" or "Due date…" across projects
            # (specs/handover.md), else files uploaded together
            key = (
                (user_id, todo_batch(action), actor)
                if todo_batch(action)
                else (user_id, actor, project, parent)
            )
            what = ("batch", (*key, chain(chains, key, batch, created_at)))
        else:
            what = ("item", item_id)
        group = groups.setdefault(
            (user_id, what), {"pks": [], "newest": (created_at, pk), "more": False}
        )
        group["pks"].append(pk)
        if (created_at, pk) >= group["newest"]:
            group["newest"], group["more"] = (created_at, pk), bool(more)
    return groups


def _builder(user, kind):
    """What builds the mail of a group (``_groups()``)"""
    if kind == "batch":
        return lambda notifications: batch_mail(user, notifications)
    return lambda notifications: item_mail(
        user, notifications[0].event.item, notifications
    )


def hold(now):
    """Notifications of people whose mails wait now (quiet hours, away;
    specs/quiet-hours.md) are marked as held; returns those people's IDs,
    whose mails don't go now"""
    from biwak.accounts.quiet import mails_held

    people = User.objects.filter(
        Q(quiet_hours=True) | Q(away_until__gte=timezone.localdate(now)),
        mail_delivery__in=[MailDelivery.EACH, MailDelivery.DIGEST],
        mail_undeliverable_at__isnull=True,
        pk__in=Notification.objects.filter(**MAILABLE).values("user"),
    )
    held = {user.pk for user in people if mails_held(user, now)}
    if held:
        Notification.objects.filter(
            user__in=held, held_at__isnull=True, **MAILABLE
        ).update(held_at=now)
    return held


def _send_held(unsent, now):
    """What waited for the working time or the return (specs/quiet-hours.md)
    of people getting a mail per change: one mail, the digest's form, or
    the usual mail when it's about one item (or batch) only"""
    count = 0
    by_user = {}
    for (user_id, what), group in _groups(
        unsent.filter(held_at__isnull=False, user__mail_delivery=MailDelivery.EACH)
    ).items():
        by_user.setdefault(user_id, []).append((what, group))
    users = User.objects.in_bulk(by_user)
    for user_id, groups in by_user.items():
        user = users[user_id]
        if len(groups) == 1:
            ((kind, _key), group) = groups[0]
            count += _mail(
                user, group["pks"], now, _builder(user, kind), MailKind.NOTIFICATION
            )
        else:
            count += _mail(
                user,
                [pk for _what, group in groups for pk in group["pks"]],
                now,
                lambda notifications, user=user: digest_mail(
                    user, notifications, short=False
                ),
                MailKind.DIGEST,
            )
    return count


def _digest_due(user, local):
    """At 07:00, or with quiet hours at the start of the working time
    (``hold()`` keeps them back outside it)"""
    return user.quiet_hours or local.time() >= DIGEST_AT


def send_mails(*, now=None):
    """Sends what's due; returns how many mails. Notifications read in the
    lantern before they're due are left out (and kept, the lantern lists
    them); a mail with nothing left isn't sent (specs/lantern.md). Those of
    people in quiet hours or away wait (specs/quiet-hours.md)."""
    now = now or timezone.now()
    # Not to addresses which bounced (specs/mail-sending.md): their
    # notifications wait, like those of people who want no mails
    unsent = Notification.objects.filter(
        **MAILABLE, user__mail_undeliverable_at__isnull=True
    ).exclude(user__in=hold(now))
    count = _send_held(unsent, now)

    # Each change, once the newest of its group is 10 minutes old
    groups = _groups(
        unsent.filter(held_at__isnull=True, user__mail_delivery=MailDelivery.EACH)
    )
    users = User.objects.in_bulk({user_id for user_id, _item_id in groups})
    for (user_id, (kind, _key)), group in groups.items():
        newest = group["newest"][0]
        if newest > now - MERGE_AFTER:
            continue
        if group["more"] and newest > now - BATCH_WAIT:
            # More files of the batch are still going up
            continue
        user = users[user_id]
        count += _mail(
            user, group["pks"], now, _builder(user, kind), MailKind.NOTIFICATION
        )

    # Digests: at 07:00 (with quiet hours: at the start of the working
    # time), the unsent notifications of the days before and what waited
    local = timezone.localtime(now)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    waiting = unsent.filter(
        Q(created_at__lt=midnight) | Q(held_at__isnull=False),
        user__mail_delivery=MailDelivery.DIGEST,
    )
    if local.time() < DIGEST_AT:
        waiting = waiting.filter(user__quiet_hours=True)
    digests = {}
    for pk, user_id in waiting.values_list("pk", "user"):
        digests.setdefault(user_id, []).append(pk)
    users = User.objects.in_bulk(digests)
    today = local.date()
    for user_id, pks in digests.items():
        user = users[user_id]
        if not _digest_due(user, local):
            continue
        count += _mail(
            user,
            pks,
            now,
            lambda notifications, user=user: digest_mail(
                user, notifications, todos=digest.todos(user, today)
            ),
            MailKind.DIGEST,
        )
    return count
