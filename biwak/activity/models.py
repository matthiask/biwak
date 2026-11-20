"""Events and subscriptions (specs/notifications.md)

Every change worth telling anybody about writes an event; the activity
feed and the notifications come from them. Events respect visibility like
their item: they're filtered through ``Item.objects.visible_to()``.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from biwak.items.models import Item
from biwak.projects.models import Project


class Action(models.TextChoices):
    CREATED = "created", _("created")
    EDITED = "edited", _("edited")
    COMPLETED = "completed", _("completed")
    REOPENED = "reopened", _("reopened")
    ASSIGNED = "assigned", _("assigned")
    COMMENTED = "commented", _("commented")
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


class EventQuerySet(models.QuerySet):
    def visible_to(self, user):
        """Events of items the person can see; project events (joining)
        only for staff with access"""
        items = Item.objects.visible_to(user)
        if user.is_client:
            return self.filter(item__in=items)
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
    created_at = models.DateTimeField(_("created at"), default=timezone.now)

    objects = EventQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [models.Index(fields=["project", "-created_at"])]
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
