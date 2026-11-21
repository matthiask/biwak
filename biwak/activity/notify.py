"""Who gets told about an event (specs/notifications.md)

``record()`` calls ``notify()`` after the commit. It writes one
``Notification`` per person; ``./manage.py send_mails`` turns them into
mails, merged per item or as a daily digest.
"""

from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext

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
from biwak.live import announce as live


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


def _paths(items):
    """``{item ID: [root ID, …, item ID]}``, one query for all"""
    if not items:
        return {}
    return {
        item.pk: item.tree_path
        for item in Item.objects
        .with_tree_fields()
        .tree_filter(project__in={item.project_id for item in items})
        .filter(pk__in=[item.pk for item in items])
    }


def _level(overrides, path, project_id, default):
    """The override of the item or the nearest container it's in (``path``,
    the root first), else the project's, else ``default``; ``overrides``
    are one person's, ``{("item" or "project", ID): level}``"""
    for pk in reversed(path):
        if ("item", pk) in overrides:
            return overrides["item", pk]
    return overrides.get(("project", project_id), default)


def _overrides(people, items, projects):
    """``{person ID: {("item" or "project", ID): level}}``, one query"""
    found = {}
    for user, item, project, level in LevelOverride.objects.filter(
        models.Q(item__in=items) | models.Q(project__in=projects),
        user__in=people,
    ).values_list("user", "item", "project", "level"):
        key = ("item", item) if item else ("project", project)
        found.setdefault(user, {})[key] = level
    return found


def effective_levels(people, item=None, *, project=None):
    """``{person ID: level}``: for each, the override of the item or the
    nearest container it's in, else the project's, else their level"""
    project_id = project.pk if project else item.project_id
    path = _paths([item])[item.pk] if item is not None else []
    overrides = _overrides([user.pk for user in people], path, [project_id])
    return {
        user.pk: _level(
            overrides.get(user.pk, {}), path, project_id, user.notification_level
        )
        for user in people
    }


def effective_level(user, item=None, *, project=None):
    """The same for one person"""
    return effective_levels([user], item, project=project)[user.pk]


def item_levels(user, items):
    """``{item ID: level}``: the person's effective level for many items"""
    paths = _paths(items)
    overrides = _overrides(
        [user.pk],
        {pk for path in paths.values() for pk in path},
        {item.project_id for item in items},
    ).get(user.pk, {})
    return {
        item.pk: _level(
            overrides, paths[item.pk], item.project_id, user.notification_level
        )
        for item in items
    }


def concerned(event, people):
    """Those of ``people`` (IDs) the event concerns, for "only what
    concerns me": being assigned or mentioned, comments on items they
    created or commented on, their to-dos (assigned to them, or created by
    them) completed by someone else"""
    item = event.item
    ids = set(event.data.get("mentioned", ()))
    match event.action:
        case Action.ASSIGNED:
            ids |= set(event.data.get("assignees", ()))
        case Action.COMMENTED:
            ids |= {item.creator_id} | set(
                Comment.objects
                .filter(item=item, author__in=people)
                .exclude(pk=event.data.get("comment"))
                .values_list("author", flat=True)
            )
        case Action.REACTED:
            # Only the author is a candidate, and it's their text
            return set(people)
        case Action.COMPLETED:
            ids |= {item.creator_id} | set(
                item.todo.assignees.filter(pk__in=people).values_list("pk", flat=True)
            )
    return ids & set(people)


def wanting(people, event):
    """Those of ``people`` whose level lets the event through; being
    mentioned passes every level except nothing"""
    item = event.item
    levels = effective_levels(people, item)
    people = [user for user in people if levels[user.pk] != NotificationLevel.NOTHING]
    mentioned = set(event.data.get("mentioned", ()))
    if item.kind == Kind.ANSWER and event.action == Action.CREATED:
        # A check-in's answers: a mail each only for those who chose it
        # (specs/checkins.md), whatever their level; the others get the
        # summary the morning after
        from biwak.checkins.models import DEFAULT_MODE, Mode, QuestionMail

        modes = dict(
            QuestionMail.objects.filter(
                question_id=item.parent_id, user__in=people
            ).values_list("user", "mode")
        )
        return [
            user
            for user in people
            if user.pk in mentioned
            or Mode(modes.get(user.pk, DEFAULT_MODE)) == Mode.EACH
        ]
    choosy = [
        user.pk for user in people if levels[user.pk] == NotificationLevel.CONCERNS_ME
    ]
    concerns = concerned(event, choosy) if choosy else set()
    return [
        user
        for user in people
        if levels[user.pk] != NotificationLevel.CONCERNS_ME or user.pk in concerns
    ]


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
    forward, sent ones only get a new one for people mentioned since. The
    same number of queries for any number of people."""
    event = Event.objects.select_related("item", "project").filter(pk=event_pk).first()
    if event is None or event.item is None or event.action in SILENT:
        return []
    people = list(candidates(event).filter(pk__in=who_can_see(event.item).values("pk")))
    if not people:
        return []
    return _tell(wanting(people, event), event)


@transaction.atomic
def _tell(people, event):
    """One unsent notification per person and event (a constraint, so two
    notify() at once can't tell anybody twice): an unsent one moves
    forward; after a sent one, only a mention since tells again"""
    if not people:
        return []
    now = timezone.now()
    ids = [user.pk for user in people]
    existing = Notification.objects.filter(event=event, user__in=ids)
    unsent = set(existing.filter(sent_at=None).values_list("user", flat=True))
    last_sent = dict(
        existing
        .filter(sent_at__isnull=False)
        .values("user")
        .annotate(last=models.Max("created_at"))
        .values_list("user", "last")
    )
    mentioned_since = {
        user
        for user, created_at in Mention.objects.filter(
            item=event.item, comment=None, user__in=last_sent
        ).values_list("user", "created_at")
        if created_at > last_sent[user]
    }
    # Sent meanwhile (send_mails claimed it): that mail has the change
    # already, which is told before this notify() runs. Read in the lantern
    # meanwhile: unread again, the change is new (specs/lantern.md).
    existing.filter(user__in=unsent, sent_at=None).update(created_at=now, read_at=None)
    new = [
        user
        for user in people
        if user.pk not in unsent
        and (user.pk not in last_sent or user.pk in mentioned_since)
    ]
    Notification.objects.bulk_create(
        [Notification(user=user, event=event, created_at=now) for user in new],
        ignore_conflicts=True,
    )
    told = [user for user in people if user.pk in unsent or user in new]
    live.lantern_changed(
        [user.pk for user in told], item=event.item, visible=event.is_client_visible
    )
    return told


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


# The forms of the overrides ------------------------------------------------


def level_choices(default):
    return [
        (
            "",
            gettext("As usual (%(level)s)")
            % {"level": NotificationLevel(default).label},
        ),
        *NotificationLevel.choices,
    ]


def item_level_context(user, item):
    """For the form next to the subscribe button"""
    override = LevelOverride.objects.filter(user=user, item=item).first()
    default = effective_level(user, item.parent, project=item.project)
    return {
        "level": override.level if override else "",
        "level_choices": level_choices(default),
    }
