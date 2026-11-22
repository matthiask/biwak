"""Who gets told about an event (specs/notifications.md)

``record()`` calls ``notify()`` after the commit. It writes one
``Notification`` per person; ``./manage.py send_mails`` turns them into
mails, merged per item or as a daily digest.
"""

from django.db import models, transaction
from django.utils import timezone
from django.utils.text import get_text_list
from django.utils.translation import gettext, ngettext

from biwak.accounts.models import NotificationLevel, User, own_staff
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


# Events which tell nobody: pinning (specs/files.md), taking somebody off a
# to-do (specs/timeline.md: the timeline and the feed say it), archiving a
# list (specs/archiving.md), public links (specs/public-links.md)
SILENT = {
    Action.PINNED,
    Action.UNPINNED,
    Action.UNASSIGNED,
    Action.ARCHIVED,
    Action.UNARCHIVED,
    Action.SHARED_PUBLICLY,
    Action.STOPPED_SHARING,
}


def can_see(user, item):
    """The one check (specs/access.md), now, not when the event happened"""
    return Item.objects.visible_to(user).filter(pk=item.pk).exists()


def people_who_see(project, visible):
    """The active people who see an item of ``project``, visible to clients
    or not, that isn't trashed (it may not exist yet):
    ``Item.objects.visible_to()`` in reverse, for everybody at once.
    ``test_notify.WhoCanSeeTest`` compares the two so they can't drift."""
    members = models.Q(memberships__project=project)
    can_see = models.Q(is_client=False) & members
    if project.is_all_access:
        # Not externals: own staff (specs/access.md)
        can_see |= own_staff()
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


def wanting(people, event):
    """Those of ``people`` (the candidates) who are told (specs/notifications.md,
    "Who gets told": subscribing is the switch): everybody subscribed to the
    item, whatever their level, and those this event assigns; the people newly
    mentioned; the subscribers of the container hear about what's new in it
    (``created``) on "everything". Reactions and sharing tell on every
    level, like a mention."""
    item = event.item
    if event.action in {Action.REACTED, Action.SHARED}:
        return list(people)
    mentioned = set(event.data.get("mentioned", ()))
    if item.kind == Kind.ANSWER and event.action == Action.CREATED:
        # A check-in's answers: to the question's subscribers whatever their
        # level (decided 2026-11-21), a mail each only for those who chose
        # it (specs/checkins.md); the others get the summary the morning
        # after. "Each" counts only while subscribed to the question (a
        # stale choice doesn't override unsubscribing, decided 2026-11-21).
        # Mentioned: always.
        from biwak.checkins.models import DEFAULT_MODE, Mode, QuestionMail

        modes = dict(
            QuestionMail.objects.filter(
                question_id=item.parent_id, user__in=people
            ).values_list("user", "mode")
        )
        subscribed = set(
            Subscription.objects.filter(
                item_id=item.parent_id, user__in=people
            ).values_list("user", flat=True)
        )
        return [
            user
            for user in people
            if (
                user.pk in subscribed
                and Mode(modes.get(user.pk, DEFAULT_MODE)) == Mode.EACH
            )
            or user.pk in mentioned
        ]
    subscribed = set(
        Subscription.objects.filter(item=item, user__in=people).values_list(
            "user", flat=True
        )
    )
    if event.action == Action.ASSIGNED:
        subscribed |= set(event.data.get("assignees", ()))
    levels = effective_levels(people, item)
    # Subscribed to the item or mentioned; on "everything" subscribed to the
    # container: something new in it
    return [
        user
        for user in people
        if user.pk in subscribed
        or user.pk in mentioned
        or levels[user.pk] == NotificationLevel.EVERYTHING
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
    if event.action == Action.SHARED:
        # Only those it was shared with, never the other subscribers
        ids = set(event.data.get("people", ()))
        ids.discard(event.actor_id)
        return User.objects.active().filter(pk__in=ids)
    items = [item.pk]
    # A doc written from a draft is quiet (specs/files.md, "Docs"):
    # its creator tells people at "Done"
    if (
        event.action == Action.CREATED
        and item.parent_id
        and not event.data.get("quiet")
    ):
        items.append(item.parent_id)
    ids = set(
        Subscription.objects.filter(item__in=items).values_list("user", flat=True)
    )
    ids |= set(event.data.get("mentioned", ()))
    if event.action == Action.ASSIGNED:
        ids |= set(event.data.get("assignees", ()))
    else:
        # Assigned and mentioned by the same change: the assignment tells
        # them (``items.operations.assign()``)
        # (unless mentioned again since: a merged edit)
        ids -= set(event.data.get("assigned", ())) - set(
            event.data.get("mentioned", ())
        )
    ids.discard(event.actor_id)
    return User.objects.active().filter(pk__in=ids)


def notify(event_pk):
    """Writes the notifications of an event; returns the people told.
    Never the actor, inactive people, people who can't see the item now or
    clients when the event is internal.
    A merged edit (``record()``) notifies again: unsent notifications move
    forward, sent ones only get a new one for people mentioned since. The
    same number of queries for any number of people."""
    event = Event.objects.select_related("item", "project").filter(pk=event_pk).first()
    if event is None or event.item is None or event.action in SILENT:
        return []
    if "to_project" in event.data:
        # Moved to another project: nobody is told
        # (specs/lists-across-projects.md)
        return []
    if event.project.is_template:
        # Nothing that happens inside a template tells anybody
        # (specs/templates.md)
        return []
    seeing = who_can_see(event.item)
    if not event.is_client_visible:
        # The event happened while the item was internal: clients never
        # hear of it, whatever the item's visibility is now (specs/access.md)
        seeing = seeing.filter(is_client=False)
    people = list(candidates(event).filter(pk__in=seeing.values("pk")))
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


def everybody(project, item=None, *, visible):
    """The project's active members who see an item there (``visible`` to
    clients or not) and whose level for ``item`` is "everything"
    (specs/notifications.md, "Subscriptions"). ``item`` is the new item
    or, before it exists, the container it goes into (``None`` at the
    top): it has no level of its own yet."""
    people = list(people_who_see(project, visible).filter(memberships__project=project))
    levels = effective_levels(people, item, project=project)
    return [user for user in people if levels[user.pk] == NotificationLevel.EVERYTHING]


def told_by_default(project, container=None, *, visible, actor=None):
    """Whom something new posted into ``container`` (a folder, or ``None``
    at the top) is told about without the poster choosing (decided
    2026-11-21, notifications are additive): those who want to hear, the
    container's subscribers and the members whose level for it is
    "everything" (``everybody()``), of those who see it (``visible`` to
    clients or not); never the poster. Sorted by name. The one rule for
    posting (``notify_people()``) and for the forms' line saying who will
    be told (``files.common.NotifyForm``, ``docs.TellForm``)."""
    people = {user.pk: user for user in everybody(project, container, visible=visible)}
    if container is not None:
        for user in people_who_see(project, visible).filter(
            subscriptions__item=container
        ):
            people.setdefault(user.pk, user)
    if actor is not None:
        people.pop(actor.pk, None)
    return sorted(people.values(), key=lambda u: (u.full_name.lower(), u.email))


def told_line(people, project, user):
    """ "Ada, Bob and 3 others will be told.": the people told by default,
    by the names ``user`` may know (``people_known_to()``, the others
    counted)"""
    from biwak.organizations.names import display_name

    known = {u.pk for u in project.people_known_to(user, people)}
    names = [display_name(u, user) for u in people if u.pk in known]
    if not people:
        return gettext("Nobody is told unless you add people.")
    shown = names[:3] if len(people) <= 3 else names[:2]
    rest = len(people) - len(shown)
    if not rest:
        # The same in English; German says "wird" or "werden"
        return ngettext(
            "%(people)s will be told.", "%(people)s will be told.", len(shown)
        ) % {"people": get_text_list(shown, gettext("and"))}
    if not shown:
        return ngettext(
            "%(count)d person will be told.", "%(count)d people will be told.", rest
        ) % {"count": rest}
    return ngettext(
        "%(people)s and %(count)d other will be told.",
        "%(people)s and %(count)d others will be told.",
        rest,
    ) % {"people": ", ".join(shown), "count": rest}


def notify_people(item, *, actor, also=()):
    """Posting a message, doc or file (specs/notifications.md, decided
    2026-11-21: additive): subscribes those told by default
    (``told_by_default()``) and ``also`` (people the poster adds, whatever
    their level), of those who can see the item, so the ``created`` event
    tells them. Not inside ``importing()``: the importer brings its own
    subscriptions. Returns them."""
    from biwak.activity.operations import is_importing

    if item.project.is_template:
        # Nobody hears about a template's items (specs/templates.md)
        return []
    people = (
        []
        if is_importing()
        else told_by_default(
            item.project, item.parent, visible=item.is_client_visible, actor=actor
        )
    )
    people += [user for user in also if user.is_active]
    chosen = [
        user for user in dict.fromkeys(people) if user != actor and can_see(user, item)
    ]
    for user in chosen:
        subscribe(user, item, added_by=actor)
    return chosen


# The forms of the levels ---------------------------------------------------


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
    """For a list's form (lists have levels, other items don't)"""
    override = LevelOverride.objects.filter(user=user, item=item).first()
    default = effective_level(user, item.parent, project=item.project)
    return {
        "level": override.level if override else "",
        "level_choices": level_choices(default),
    }
