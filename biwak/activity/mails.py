"""Notification mails (specs/notifications.md): one mail per person and
item once its newest notification is 2 minutes old, or a daily digest at
07:00. ``./manage.py send_mails`` runs ``send_mails()`` every minute."""

import datetime as dt
import logging
from email.utils import formataddr, make_msgid, parseaddr
from itertools import groupby
from urllib.parse import urlsplit

from django.conf import settings
from django.core import signing
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.formats import date_format
from django.utils.translation import gettext as _

from biwak.accounts.models import MailDelivery, NotificationLevel, User
from biwak.activity import mentions
from biwak.activity.models import Action, Notification
from biwak.activity.notify import can_see, effective_level
from biwak.activity.operations import is_subscribed
from biwak.files.models import REFERENCE, Attachment
from biwak.items.models import Comment, Kind


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


def absolute(url):
    return settings.BASE_URL + url


def host():
    return urlsplit(settings.BASE_URL).hostname or "localhost"


def sender(name):
    """``"Ada Lovelace (Biwak)" <DEFAULT_FROM_EMAIL>``"""
    return formataddr((name, parseaddr(settings.DEFAULT_FROM_EMAIL)[1]))


def plain_text(text, item):
    """A text for the plain text part: mentions as ``@`` and the current
    name, attachments (``attachment:KEY``) as their download URLs. The
    download checks access, as on the pages."""
    text = mentions.plain(text, item)
    keys = set(REFERENCE.findall(text))
    if not keys:
        return text
    urls = {
        a.key: absolute(a.get_absolute_url())
        for a in Attachment.objects.filter(key__in=keys)
    }
    return REFERENCE.sub(lambda m: urls.get(m[1], m[0]), text)


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
    match event.action:
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
            text = (
                _("%(actor)s moved it to %(to)s.")
                if data.get("to") and not user.is_client
                else _("%(actor)s moved it.")
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
    return text % {"actor": actor, "to": mentions.plain(data.get("to", ""))}


def _entries(notifications, user):
    """What happened, oldest first, comments with their text"""
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
    return entries


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
            "list": item.parent,
        }
    elif item.kind == Kind.LIST:
        context["text"] = item.todolist.description
    elif item.kind in {Kind.MESSAGE, Kind.DOC}:
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
        Notification.objects.filter(pk__in=pks).update(sent_at=None)


def _deliverable(notifications, user):
    """Those the person may still get: active, the item visible to them now,
    their level not "nothing" (it may have changed since)"""
    if not user.is_active:
        return []
    result = []
    for notification in notifications:
        item = notification.event.item
        if item is None or not can_see(user, item):
            continue
        if effective_level(user, item) == NotificationLevel.NOTHING:
            continue
        result.append(notification)
    return result


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


def item_mail(user, item, notifications):
    """One mail about one item, threaded per item"""
    entries = _entries(notifications, user)
    context = _item(item, user) | {
        "user": user,
        "entries": entries,
        "settings_url": absolute(reverse("notification_settings")),
    }
    subject = f"[{item.project}] {context['title']}"
    actor = entries[-1]["event"].actor
    thread = f"<item-{item.pk}@{host()}>"
    message = EmailMultiAlternatives(
        subject,
        render_to_string("mails/notification.txt", context),
        sender(_("%(name)s (Biwak)") % {"name": actor}),
        [user.email],
        headers={
            "Message-ID": make_msgid(domain=host()),
            "In-Reply-To": thread,
            "References": thread,
            "List-Unsubscribe": f"<{context['unsubscribe_url']}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
            "Auto-Submitted": "auto-generated",
        },
    )
    message.attach_alternative(
        render_to_string("mails/notification.html", context), "text/html"
    )
    return message


def digest_mail(user, notifications, *, day):
    """The day's notifications, grouped by project and item"""
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
            _item(item, user) | {"entries": _entries(list(by_item), user)}
            for item, by_item in groupby(by_project, lambda n: n.event.item)
        ]
        projects.append({"project": project, "items": items})
    context = {
        "user": user,
        "day": day,
        "projects": projects,
        "settings_url": absolute(reverse("notification_settings")),
    }
    message = EmailMultiAlternatives(
        _("[Biwak] What happened on %(day)s") % {"day": date_format(day, "j. F Y")},
        render_to_string("mails/digest.txt", context),
        sender("Biwak"),
        [user.email],
        headers={
            "Message-ID": make_msgid(domain=host()),
            # No one-click unsubscribing from everything: the settings page
            "List-Unsubscribe": f"<{context['settings_url']}>",
            "Auto-Submitted": "auto-generated",
        },
    )
    message.attach_alternative(
        render_to_string("mails/digest.html", context), "text/html"
    )
    return message


def _mail(user, pks, now, build):
    """Claims the notifications, drops those the person mustn't get any
    more, builds the mail and sends it after the commit"""
    with transaction.atomic():
        claimed = _claim(pks, now)
        if not claimed:
            return False
        deliverable = _deliverable(claimed, user)
        # Never sent: gone
        Notification.objects.filter(
            pk__in={n.pk for n in claimed} - {n.pk for n in deliverable}
        ).delete()
        if not deliverable:
            return False
        with translation.override(user.language or settings.LANGUAGE_CODE):
            message = build(deliverable)
        sent = [n.pk for n in deliverable]
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
        day = (midnight - dt.timedelta(days=1)).date()
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
                lambda notifications, user=user: digest_mail(
                    user, notifications, day=day
                ),
            )
    return count
