"""Notification mails (specs/notifications.md): one mail per person and
item once its newest notification is 2 minutes old, or a daily digest at
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
from django.db.models import Exists, OuterRef
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.formats import date_format
from django.utils.translation import gettext as _

from biwak.accounts.models import MailDelivery, NotificationLevel, User
from biwak.activity import mentions
from biwak.activity.models import Action, Notification
from biwak.activity.notify import can_see, item_levels
from biwak.activity.operations import is_subscribed
from biwak.api_conventions import absolute
from biwak.files.models import REFERENCE, Attachment
from biwak.inbound.tokens import reply_to
from biwak.items.models import Comment, Item, Kind


logger = logging.getLogger(__name__)

# Quick edits and several comments merge into one mail (decided 2026-11-20)
MERGE_AFTER = dt.timedelta(minutes=2)
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


def plain_text(text, item):
    """A text for the plain text part: mentions as ``@`` and the current
    name, the item's attachments (``attachment:KEY``) as their download
    URLs; the download checks access, as on the pages. References to other
    items' attachments become a plain "attachment", without their names
    (``render_markdown()``)."""
    text = mentions.plain(text, item)
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
    people = User.objects.filter(pk__in=ids)
    return ", ".join(
        _("you") if person == user else str(person)
        for person in people
        if person == user or can_see(person, item)
    )


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
            return _("%(actor)s assigned %(people)s.") % {
                "actor": actor,
                "people": _names(data.get("assignees", ()), user, event.item),
            }
        case Action.COMMENTED:
            text = _("%(actor)s commented:")
        case Action.MOVED:
            # Not to clients: the name may be internal (like the feed)
            # A group of its own list is as visible as the to-do
            to = data.get("group") or ("" if user.is_client else data.get("to"))
            text = (
                _("%(actor)s moved it to %(to)s.") if to else _("%(actor)s moved it.")
            )
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
            text = "%(actor)s " + event.get_action_display() + "."
    return text % {"actor": actor, "to": mentions.plain(to or "")}


def _reactions(notifications, user):
    """Reactions collected into one entry per thing reacted to (the item or
    a comment), oldest first: "Bea: 👍 🎉, Carl: Thanks!" (specs/reactions.md)"""
    by_target = {}
    for notification in sorted(notifications, key=lambda n: n.event.created_at):
        event = notification.event
        by_target.setdefault(event.data.get("comment"), []).append(event)
    comments = Comment.objects.in_bulk([pk for pk in by_target if pk])
    entries = []
    for comment_id, events in by_target.items():
        comment = comments.get(comment_id)
        if comment_id and comment is None:
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
            "line": _("Reactions to your comment:") if comment else _("Reactions:"),
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
        "title": mentions.plain(item.title, item),
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
            "assignees": ", ".join(str(a) for a in todo.assignees.all()),
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


def _send(message, pks):
    """After the commit; on failure the notifications wait for the next
    run"""
    try:
        message.send()
    except Exception:
        logger.exception("Sending a notification mail failed")
        failed = Notification.objects.filter(pk__in=pks)
        # Unsent again, except where a newer unsent one carries the event
        # (one per person and event)
        failed.filter(
            Exists(
                Notification.objects.filter(
                    user=OuterRef("user"), event=OuterRef("event"), sent_at=None
                )
            )
        ).delete()
        failed.update(sent_at=None)


def _deliverable(notifications, user):
    """Those the person may still get: the item visible to them now (which
    excludes the inactive), their level not "nothing" (it may have changed
    since). The same number of queries for any number of items."""
    items = {n.event.item_id: n.event.item for n in notifications if n.event.item}
    visible = set(
        Item.objects.visible_to(user).filter(pk__in=items).values_list("pk", flat=True)
    )
    levels = item_levels(user, [items[pk] for pk in visible])
    return [
        notification
        for notification in notifications
        if notification.event.item_id in visible
        and levels[notification.event.item_id] != NotificationLevel.NOTHING
    ]


def _claim(pks, now):
    """Locks and marks the notifications as sent (skipping those another
    run is sending); returns those claimed"""
    claimed = list(
        Notification.objects
        .select_for_update(skip_locked=True, of=("self",))
        .filter(pk__in=pks, sent_at__isnull=True)
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
        "settings_url": absolute(reverse("notification_settings")),
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


def digest_heading(notifications):
    """ "What happened on 19. November 2026", or the days it covers when
    there's more than one (after a downtime, or switching to digests)"""
    days = sorted({timezone.localdate(n.created_at) for n in notifications})
    first, last = date_format(days[0], "j. F Y"), date_format(days[-1], "j. F Y")
    if first == last:
        return _("What happened on %(day)s") % {"day": first}
    return _("What happened from %(first)s to %(last)s") % {
        "first": first,
        "last": last,
    }


def digest_mail(user, notifications):
    """The notifications before today, grouped by project and item; None
    when there's nothing left to say"""
    notifications = sorted(
        notifications,
        key=lambda n: (
            str(n.event.item.project).lower(),
            n.event.item.project_id,
            n.event.item_id,
        ),
    )
    projects = []
    for project, by_project in groupby(notifications, lambda n: n.event.item.project):
        items = [
            _item(item, user) | {"entries": entries}
            for item, by_item in groupby(by_project, lambda n: n.event.item)
            if (entries := _entries(list(by_item), user))
        ]
        if items:
            projects.append({"project": project, "items": items})
    if not projects:
        return None
    context = {
        "user": user,
        "heading": digest_heading(notifications),
        "projects": projects,
        "settings_url": absolute(reverse("notification_settings")),
    }
    return build_mail(
        user,
        subject=_("[Biwak] %(heading)s") % context,
        template="mails/digest",
        context=context,
        # No one-click unsubscribing from everything: the settings page
        headers=unsubscribe_headers(context["settings_url"], one_click=False),
    )


def _mail(user, pks, now, build):
    """Claims the notifications, drops those the person mustn't get any
    more, builds the mail and sends it after the commit. A mail which can't
    be built is logged and rolled back: its notifications stay unsent, and
    the others go out."""
    try:
        with transaction.atomic():
            return _prepare(user, pks, now, build)
    except Exception:
        logger.exception("Building a notification mail failed")
        return False


def _prepare(user, pks, now, build):
    claimed = _claim(pks, now)
    if not claimed:
        return False
    deliverable = _deliverable(claimed, user)
    message = None
    if deliverable:
        with (
            translation.override(user.language or settings.LANGUAGE_CODE),
            mentions.reading_as(user),
        ):
            message = build(deliverable)
    sent = [n.pk for n in deliverable] if message else []
    # Never sent: gone
    Notification.objects.filter(pk__in={n.pk for n in claimed} - set(sent)).delete()
    if message is None:
        return False
    transaction.on_commit(lambda: _send(message, sent))
    return True


def send_mails(*, now=None):
    """Sends what's due; returns how many mails"""
    now = now or timezone.now()
    unsent = Notification.objects.filter(sent_at__isnull=True)
    count = 0

    # Each change: per person and item, once the newest is 2 minutes old
    groups = {}
    for pk, user_id, item_id, created_at in unsent.filter(
        user__mail_delivery=MailDelivery.EACH
    ).values_list("pk", "user", "event__item", "created_at"):
        group = groups.setdefault((user_id, item_id), {"pks": [], "newest": created_at})
        group["pks"].append(pk)
        group["newest"] = max(group["newest"], created_at)
    users = User.objects.in_bulk({user_id for user_id, _item_id in groups})
    for (user_id, _item_id), group in groups.items():
        if group["newest"] > now - MERGE_AFTER:
            continue
        user = users[user_id]
        count += _mail(
            user,
            group["pks"],
            now,
            lambda notifications, user=user: item_mail(
                user, notifications[0].event.item, notifications
            ),
        )

    # Digests: at 07:00, the unsent notifications of the days before
    local = timezone.localtime(now)
    if local.time() >= DIGEST_AT:
        midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
        digests = {}
        for pk, user_id in unsent.filter(
            user__mail_delivery=MailDelivery.DIGEST, created_at__lt=midnight
        ).values_list("pk", "user"):
            digests.setdefault(user_id, []).append(pk)
        users = User.objects.in_bulk(digests)
        for user_id, pks in digests.items():
            user = users[user_id]
            count += _mail(
                user,
                pks,
                now,
                lambda notifications, user=user: digest_mail(user, notifications),
            )
    return count
