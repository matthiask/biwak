"""Bookmarks and links (specs/feed.md): things pointing at items and
projects which aren't items themselves"""

from django.conf import settings
from django.core.validators import URLValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from biwak import links
from biwak.items.models import Item
from biwak.projects.models import Project


class BookmarkQuerySet(models.QuerySet):
    def visible_to(self, user):
        """The person's own bookmarks of what they can see now; the others
        stay in the database, hidden"""
        if not user.is_authenticated or not user.is_active:
            return self.none()
        return self.filter(user=user).filter(
            Q(item__in=Item.objects.visible_to(user))
            | Q(project__in=Project.objects.accessible_to(user))
        )


class Bookmark(models.Model):
    """Private: of one person, on an item or a project"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="bookmarks",
        verbose_name=_("person"),
    )
    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="bookmarks",
        verbose_name=_("item"),
    )
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="bookmarks",
        verbose_name=_("project"),
    )
    created_at = models.DateTimeField(_("created at"), default=timezone.now)

    objects = BookmarkQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=Q(item__isnull=True) ^ Q(project__isnull=True),
                name="bookmark_item_or_project",
            ),
            models.UniqueConstraint(
                fields=["user", "item"],
                condition=Q(item__isnull=False),
                name="unique_item_bookmark",
            ),
            models.UniqueConstraint(
                fields=["user", "project"],
                condition=Q(project__isnull=False),
                name="unique_project_bookmark",
            ),
        ]
        verbose_name = _("bookmark")
        verbose_name_plural = _("bookmarks")

    def __str__(self):
        return f"{self.user} → {self.item or self.project}"


class LinkQuerySet(models.QuerySet):
    def visible_to(self, user):
        """Links of projects the person can open; clients only those
        visible to clients"""
        if not user.is_authenticated or not user.is_active:
            return self.none()
        qs = self.filter(project__in=Project.objects.accessible_to(user))
        if user.is_client:
            qs = qs.filter(visible_to_clients=True)
        return qs


validate_url = URLValidator(schemes=["http", "https"])


class Link(models.Model):
    """A link to an outside tool on a project"""

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="links",
        verbose_name=_("project"),
    )
    url = models.URLField(_("URL"), max_length=2000, validators=[validate_url])
    title = models.CharField(_("title"), max_length=200)
    # From the URL's host (biwak/links.py)
    kind = models.CharField(
        _("kind"),
        max_length=20,
        choices=links.KINDS.items(),
        default=links.LINK,
        editable=False,
    )
    position = models.PositiveIntegerField(_("position"), default=0)
    visible_to_clients = models.BooleanField(
        _("visible to clients"),
        default=False,
        help_text=_("Internal unless you switch it."),
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("created by"),
    )
    created_at = models.DateTimeField(_("created at"), default=timezone.now)

    objects = LinkQuerySet.as_manager()

    class Meta:
        ordering = ["position", "pk"]
        indexes = [models.Index(fields=["project", "position"])]
        verbose_name = _("link")
        verbose_name_plural = _("links")

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        self.kind = links.kind_for(self.url)
        if kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = {*kwargs["update_fields"], "kind"}
        self.full_clean(validate_unique=False, validate_constraints=False)
        super().save(*args, **kwargs)
