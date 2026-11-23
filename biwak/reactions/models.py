"""Reactions (specs/reactions.md): an emoji or a few words on a thing
instead of a comment"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from biwak.activity.models import Action, Event
from biwak.items.models import Comment, Item, Kind
from biwak.reactions.emoji import MAX_LENGTH


# Kinds of items reactions go on directly; comments are reactable wherever
# they are (``can_react()``), and so is a to-do getting completed (its
# ``completed`` event, decided 2026-11-23).
REACTABLE = {Kind.TODO, Kind.MESSAGE, Kind.DOC, Kind.FILE, Kind.ANSWER}


def can_react(item, comment=None, event=None):
    """Whether the thing can be reacted to: a comment on any commentable
    item, a to-do's completing, or an item of a reactable kind"""
    if comment is not None:
        return comment.item_id == item.pk and item.is_commentable
    if event is not None:
        return (
            event.item_id == item.pk
            and item.kind == Kind.TODO
            and event.action == Action.COMPLETED
        )
    return item.kind in REACTABLE


class ReactionQuerySet(models.QuerySet):
    def visible_to(self, user):
        """Reactions are visible exactly when their item is, those on a
        completing when its event is (clients: if it happened while they
        saw the to-do)"""
        return self.filter(item__in=Item.objects.visible_to(user)).filter(
            Q(event__isnull=True) | Q(event__in=Event.objects.visible_to(user))
        )


class Reaction(models.Model):
    """On the item when ``comment`` and ``event`` are empty, else on the
    comment or on the to-do's ``completed`` event (whose item is kept in
    ``item``, so visibility is the item's); never on both"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reactions",
        verbose_name=_("person"),
    )
    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name="reactions",
        verbose_name=_("item"),
    )
    comment = models.ForeignKey(
        Comment,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="reactions",
        verbose_name=_("comment"),
    )
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="reactions",
        verbose_name=_("event"),
    )
    content = models.CharField(_("content"), max_length=MAX_LENGTH)
    created_at = models.DateTimeField(_("created at"), default=timezone.now)

    objects = ReactionQuerySet.as_manager()

    class Meta:
        ordering = ["created_at", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "item", "comment", "event", "content"],
                name="unique_reaction",
                nulls_distinct=False,
            ),
            models.CheckConstraint(
                condition=Q(comment__isnull=True) | Q(event__isnull=True),
                name="reaction_one_target",
            ),
        ]
        verbose_name = _("reaction")
        verbose_name_plural = _("reactions")

    def __str__(self):
        return f"{self.user}: {self.content}"

    def save(self, *args, **kwargs):
        self.full_clean(validate_unique=False, validate_constraints=False)
        super().save(*args, **kwargs)

    def clean(self):
        if self.comment_id and self.comment.item_id != self.item_id:
            raise ValidationError(_("The comment belongs to another item."))
        if self.event_id and self.event.item_id != self.item_id:
            raise ValidationError(_("The event belongs to another item."))
