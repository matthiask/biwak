"""Events and subscriptions (specs/notifications.md)

Every change worth telling anybody about writes an event; the activity
feed and the notifications come from them. Events respect visibility like
their item: they're filtered through ``Item.objects.visible_to()``, and
clients only see events of the time the item was visible to them
(``Event.is_client_visible``, specs/access.md).
"""

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from biwak.accounts.models import NotificationLevel
from biwak.items.models import Item
from biwak.projects.models import Project


class Action(models.TextChoices):
    CREATED = "created", _("created")
    EDITED = "edited", _("edited")
    COMPLETED = "completed", _("completed")
    REOPENED = "reopened", _("reopened")
    ASSIGNED = "assigned", _("assigned")
    COMMENTED = "commented", _("commented")
    REACTED = "reacted", _("reacted")
    MOVED = "moved", _("moved")
    VISIBILITY_CHANGED = "visibility_changed", _("visibility changed")
    ARCHIVED = "archived", _("archived")
    UNARCHIVED = "unarchived", _("unarchived")
    EDITED_PROJECT = "edited_project", _("edited the project")
    TRASHED = "trashed", _("trashed")
    RESTORED = "restored", _("restored")
    JOINED = "joined", _("joined")
    ADDED = "added", _("added")
    REMOVED = "removed", _("removed")
    LEFT = "left", _("left")
    PINNED = "pinned", _("pinned")
    UNPINNED = "unpinned", _("unpinned")


class EventQuerySet(models.QuerySet):
    def visible_to(self, user):
        """Events of items the person can see; for clients only those of
        the time the item was visible to them (they store the title at the
        time, assignees, people mentioned); project events (joining) only
        for staff with access"""
        items = Item.objects.visible_to(user)
        if user.is_client:
            return self.filter(item__in=items, is_client_visible=True)
        return self.filter(
            models.Q(item__in=items)
            | models.Q(
                item__isnull=True, project__in=Project.objects.accessible_to(user)
            )
        )


class Event(models.Model):
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="events",
        verbose_name=_("project"),
    )
    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="events",
        verbose_name=_("item"),
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("actor"),
    )
    action = models.CharField(_("action"), max_length=30, choices=Action)
    # The item's title at the time, and what changed (e.g. assignees)
    data = models.JSONField(_("data"), default=dict, blank=True)
    # Whether the item was visible to clients when it happened; clients
    # only see these (decided 2026-11-20, specs/access.md)
    is_client_visible = models.BooleanField(_("visible to clients"), default=False)
    created_at = models.DateTimeField(_("created at"), default=timezone.now)

    objects = EventQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [
            models.Index(fields=["project", "-created_at"]),
            # The feed across projects, newest first (specs/feed.md)
            models.Index(fields=["-created_at", "-id"], name="event_created_idx"),
        ]
        verbose_name = _("event")
        verbose_name_plural = _("events")

    def __str__(self):
        return f"{self.actor} {self.action} {self.data.get('title', '')}"


class Subscription(models.Model):
    """A person following an item; for lists and folders also the items
    created in them later. Automatic for authors, assignees, people
    mentioned and commenting; cancellable any time."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="subscriptions",
        verbose_name=_("person"),
    )
    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name="subscriptions",
        verbose_name=_("item"),
    )
    created_at = models.DateTimeField(_("created at"), default=timezone.now)
    # Who subscribed them, if somebody else
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("added by"),
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "item"], name="unique_subscription")
        ]
        verbose_name = _("subscription")
        verbose_name_plural = _("subscriptions")

    def __str__(self):
        return f"{self.user} → {self.item}"


class Unsubscription(models.Model):
    """Somebody unsubscribed: automatic subscriptions (commenting) don't
    bring them back, only being mentioned or assigned again"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="+",
        verbose_name=_("person"),
    )
    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name="+",
        verbose_name=_("item"),
    )
    created_at = models.DateTimeField(_("created at"), default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "item"], name="unique_unsubscription"
            )
        ]

    def __str__(self):
        return f"{self.user} ↛ {self.item}"


class Mention(models.Model):
    """Somebody mentioned in an item's text (``comment`` empty: the item's
    own texts, e.g. a to-do's title and notes) or in a comment
    (biwak.activity.mentions). Only people who could see the item when it
    was written."""

    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name="mentions",
        verbose_name=_("item"),
    )
    comment = models.ForeignKey(
        "items.Comment",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="mentions",
        verbose_name=_("comment"),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="+",
        verbose_name=_("person"),
    )
    created_at = models.DateTimeField(_("created at"), default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["item", "comment", "user"],
                name="unique_mention",
                nulls_distinct=False,
            )
        ]
        verbose_name = _("mention")
        verbose_name_plural = _("mentions")

    def __str__(self):
        return f"@{self.user} in {self.item}"


class LevelOverride(models.Model):
    """A person's notification level for one project or one item (and
    what's in it), instead of ``User.notification_level``"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="level_overrides",
        verbose_name=_("person"),
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("project"),
    )
    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("item"),
    )
    level = models.CharField(
        _("notifications"), max_length=20, choices=NotificationLevel
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(project__isnull=True) ^ models.Q(item__isnull=True),
                name="override_project_or_item",
            ),
            models.UniqueConstraint(
                fields=["user", "project"],
                condition=models.Q(project__isnull=False),
                name="unique_project_override",
            ),
            models.UniqueConstraint(
                fields=["user", "item"],
                condition=models.Q(item__isnull=False),
                name="unique_item_override",
            ),
        ]
        verbose_name = _("notification level override")
        verbose_name_plural = _("notification level overrides")

    def __str__(self):
        return f"{self.user}: {self.level} for {self.project or self.item}"


class Notification(models.Model):
    """An event a person is told about (biwak.activity.notify): in the
    lantern (biwak.activity.lantern, specs/lantern.md) and by mail, which
    ``send_mails`` sends and marks; read in the lantern before that, it
    isn't mailed"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name=_("person"),
    )
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name=_("event"),
    )
    # Moved forward when a merged edit notifies again before sending
    created_at = models.DateTimeField(_("created at"), default=timezone.now)
    sent_at = models.DateTimeField(_("sent at"), null=True, blank=True)
    # Read in the lantern, or the item opened (null: unread)
    read_at = models.DateTimeField(_("read at"), null=True, blank=True)

    class Meta:
        ordering = ["created_at", "pk"]
        indexes = [
            models.Index(
                fields=["user", "created_at"],
                condition=models.Q(sent_at__isnull=True),
                name="unsent_notifications",
            ),
            # The lantern, newest first
            models.Index(
                fields=["user", "-created_at", "-id"], name="lantern_notifications"
            ),
        ]
        constraints = [
            # One unsent notification per person and event, even when two
            # notify() run at once (biwak.activity.notify)
            models.UniqueConstraint(
                fields=["user", "event"],
                condition=models.Q(sent_at__isnull=True),
                name="one_unsent_notification",
            )
        ]
        verbose_name = _("notification")
        verbose_name_plural = _("notifications")

    def __str__(self):
        return f"{self.user}: {self.event}"
