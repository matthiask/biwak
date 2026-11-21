"""Who gets told about an event (specs/notifications.md)

``record()`` calls ``notify()`` after the commit. It writes one
``Notification`` per person; ``./manage.py send_mails`` turns them into
mails, merged per item or as a daily digest.
"""

from django.db import models, transaction
from django.utils import timezone

from biwak.accounts.models import NotificationLevel, User
from biwak.activity.models import (
    Action,
    Event,
    LevelOverride,
    Mention,
    Notification,
    Subscription,
)
from biwak.activity.operations import subscribe
from biwak.items.models import Comment, Item, Kind, Status


# Events which tell nobody: pinning (specs/files.md)
SILENT = {Action.PINNED, Action.UNPINNED}


def can_see(user, item):
    """The one check (specs/access.md), now, not when the event happened"""
    return Item.objects.visible_to(user).filter(pk=item.pk).exists()


def people_who_see(project, visible):
    """The active people who see an item of ``project``, visible to clients
    or not, that isn't trashed (it may not exist yet):
    ``Item.objects.visible_to()`` in reverse, for everybody at once.
    ``test_notify.WhoCanSeeTest`` compares the two so they can't drift."""
    staff = models.Q(is_client=False)
    if not project.is_all_access:
        staff &= models.Q(memberships__project=project)
    can_see = staff
    if visible:
        can_see |= models.Q(is_client=True, memberships__project=project)
    return User.objects.active().filter(can_see).distinct()


def who_can_see(item):
    """The people who can see the item now: ``can_see()`` for everybody"""
    if item.status == Status.TRASHED:
        return User.objects.none()
    return people_who_see(item.project, item.is_client_visible)


def effective_level(user, item=None, *, project=None):
    """The override of the item or the nearest container it's in, else the
    project's, else the person's level"""
    project = project or item.project
    overrides = LevelOverride.objects.filter(user=user)
    if item is not None:
        ancestors = list(
            Item.objects.ancestors(item, include_self=True).values_list("pk", flat=True)
        )
        levels = dict(overrides.filter(item__in=ancestors).values_list("item", "level"))
        for pk in reversed(ancestors):
            if pk in levels:
                return levels[pk]
    if override := overrides.filter(project=project).first():
        return override.level
    return user.notification_level


def concerns(user, event):
    """What "only what concerns me" includes: being assigned or mentioned,
    comments on items they created or commented on, their to-dos (assigned
    to them, or created by them) completed by someone else"""
    item = event.item
    if user.pk in event.data.get("mentioned", ()):
        return True
    match event.action:
        case Action.ASSIGNED:
            return user.pk in event.data.get("assignees", ())
        case Action.COMMENTED:
            return (
                item.creator_id == user.pk
                or Comment.objects
                .filter(item=item, author=user)
                .exclude(pk=event.data.get("comment"))
                .exists()
            )
        case Action.REACTED:
            # Only the author is a candidate, and it's their text
            return True
        case Action.COMPLETED:
            return (
                item.creator_id == user.pk
                or item.todo.assignees.filter(pk=user.pk).exists()
            )
    return False


def wants(user, event):
    r"""Whether the person's level lets the event through; being mentioned
    passes every level except "nothing\""""
    level = effective_level(user, event.item)
    if level == NotificationLevel.NOTHING:
        return False
    if (
        event.item.kind == Kind.ANSWER
        and event.action == Action.CREATED
        and user.pk not in event.data.get("mentioned", ())
    ):
        # A check-in's answers: a mail each only for those who chose it
        # (specs/checkins.md), whatever their level; the others get the
        # summary the morning after
        from biwak.checkins.models import Mode, mail_mode

        return mail_mode(user, event.item.parent_id) == Mode.EACH
    if level == NotificationLevel.CONCERNS_ME:
        return concerns(user, event)
    return True


def reacted_author(event):
    """The ID of the author of the thing reacted to: of the comment, or the
    item's creator"""
    if comment := event.data.get("comment"):
        return (
            Comment.objects.filter(pk=comment).values_list("author", flat=True).first()
        )
    return event.item.creator_id


def candidates(event):
    """Subscribers of the item (for new items also of its container) and the
    people this event assigned or mentioned"""
    item = event.item
    if event.action == Action.REACTED:
        # Nobody else, never the subscribers (specs/reactions.md)
        author = reacted_author(event)
        if author is None or author == event.actor_id:
            return User.objects.none()
        return User.objects.active().filter(pk=author)
    items = [item.pk]
    if event.action == Action.CREATED and item.parent_id:
        items.append(item.parent_id)
    ids = set(
        Subscription.objects.filter(item__in=items).values_list("user", flat=True)
    )
    ids |= set(event.data.get("mentioned", ()))
    if event.action == Action.ASSIGNED:
        ids |= set(event.data.get("assignees", ()))
    ids.discard(event.actor_id)
    return User.objects.active().filter(pk__in=ids)


def notify(event_pk):
    """Writes the notifications of an event; returns the people told.
    Never the actor, inactive people or people who can't see the item now.
    A merged edit (``record()``) notifies again: unsent notifications move
    forward, sent ones only get a new one for people mentioned since."""
    event = Event.objects.select_related("item", "project").filter(pk=event_pk).first()
    if event is None or event.item is None or event.action in SILENT:
        return []
    now = timezone.now()
    told = []
    for user in candidates(event):
        if not can_see(user, event.item) or not wants(user, event):
            continue
        if _tell(user, event, now):
            told.append(user)
    return told


@transaction.atomic
def _tell(user, event, now):
    """One unsent notification per person and event (a constraint, so two
    notify() at once can't tell anybody twice): an unsent one moves
    forward; after a sent one, only a mention since tells again"""
    sent = (
        Notification.objects
        .filter(user=user, event=event, sent_at__isnull=False)
        .order_by("-created_at", "-pk")
        .first()
    )
    if sent is not None and not (
        Notification.objects.filter(user=user, event=event, sent_at=None).exists()
        or Mention.objects.filter(
            item=event.item, user=user, comment=None, created_at__gt=sent.created_at
        ).exists()
    ):
        return False
    # Locked: a send_mails() claiming it at the same time waits, or we wait
    # and create a new one
    notification, created = Notification.objects.select_for_update().get_or_create(
        user=user, event=event, sent_at=None, defaults={"created_at": now}
    )
    if not created:
        notification.created_at = now
        notification.save(update_fields=["created_at"])
    return True


def notify_people(item, *, whom, actor):
    """Posting a message, doc or file: whom to tell (specs/files.md):
    ``"everybody"`` (the project's members at this moment), a list of
    people, or ``"nobody"``. Those chosen who can see the item are
    subscribed, so the ``created`` event tells them. Returns them."""
    if whom == "nobody":
        return []
    if whom == "everybody":
        people = User.objects.active().filter(memberships__project=item.project)
    else:
        people = [user for user in whom if user.is_active]
    chosen = [user for user in people if user != actor and can_see(user, item)]
    for user in chosen:
        subscribe(user, item, added_by=actor)
    return chosen
