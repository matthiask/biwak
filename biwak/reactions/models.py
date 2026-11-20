"""Reactions (specs/reactions.md): an emoji or a few words on a thing
instead of a comment"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from biwak.items.models import Comment, Item, Kind
from biwak.reactions.emoji import MAX_LENGTH


# Kinds of items reactions go on directly; comments are reactable wherever
# they are (``can_react()``).
REACTABLE = {Kind.TODO, Kind.MESSAGE, Kind.DOC, Kind.FILE, Kind.ANSWER}


def can_react(item, comment=None):
    """Whether the thing can be reacted to: a comment on any commentable
    item, or an item of a reactable kind"""
    if comment is not None:
        return comment.item_id == item.pk and item.is_commentable
    return item.kind in REACTABLE


class ReactionQuerySet(models.QuerySet):
    def visible_to(self, user):
        """Reactions are visible exactly when their item is"""
        return self.filter(item__in=Item.objects.visible_to(user))


class Reaction(models.Model):
    """On the item when ``comment`` is empty, else on the comment (whose
    item is kept in ``item``, so visibility is the item's)"""

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
    content = models.CharField(_("content"), max_length=MAX_LENGTH)
    created_at = models.DateTimeField(_("created at"), default=timezone.now)

    objects = ReactionQuerySet.as_manager()

    class Meta:
        ordering = ["created_at", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "item", "comment", "content"],
                name="unique_reaction",
                nulls_distinct=False,
            )
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
