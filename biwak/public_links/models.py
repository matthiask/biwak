"""Public links (specs/public-links.md): one item shown read only to people
without an account, for a few days"""

import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from biwak.items.models import Item, Status
from biwak.projects.models import Project


# How long a link lives, in days; nothing longer (decided 2026-11-22)
DAYS = (1, 3, 7, 30)
DEFAULT_DAYS = 7


def new_token():
    return secrets.token_urlsafe(32)


class PublicLinkQuerySet(models.QuerySet):
    def live(self, now=None):
        """Not expired; their items may still be gone (``open()``)"""
        return self.filter(expires_at__gt=now or timezone.now())

    def listed_for(self, user):
        """The live links on the page of all public links: staff see those
        in the projects they can open, admins all of them, clients none
        (decided 2026-11-22)"""
        if not user.is_authenticated or not user.is_active or user.is_client:
            return self.none()
        links = (
            self
            .live()
            .filter(item__is_draft=False)
            .exclude(item__status=Status.TRASHED)
        )
        if user.is_admin:
            return links
        return links.filter(item__project__in=Project.objects.accessible_to(user))

    def open(self, token):
        """The link of ``token`` if its page may be shown now: live, its
        item not trashed and still shareable, its project not archived;
        else None. Checked on every request, whatever the operations
        deleted already."""
        return (
            self
            .live()
            .filter(
                token=token,
                item__is_draft=False,
                item__status=Status.ACTIVE,
                item__project__archived_at__isnull=True,
                item__project__is_template=False,
            )
            .select_related("item", "item__creator")
            .first()
        )


class PublicLink(models.Model):
    """The secret is stored as is: the "Share…" modal shows the link again,
    like the calendar feed's (``CalendarToken``). Not in the audit log,
    which would repeat the secret. One per item: a new one replaces it."""

    item = models.OneToOneField(
        Item,
        on_delete=models.CASCADE,
        related_name="public_link",
        verbose_name=_("item"),
    )
    token = models.CharField(
        _("token"), max_length=64, unique=True, editable=False, default=new_token
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("created by"),
    )
    created_at = models.DateTimeField(_("created at"), default=timezone.now)
    expires_at = models.DateTimeField(_("expires at"))

    objects = PublicLinkQuerySet.as_manager()

    class Meta:
        ordering = ["expires_at", "pk"]
        verbose_name = _("public link")
        verbose_name_plural = _("public links")

    def __str__(self):
        return f"{self.item}"

    def get_absolute_url(self):
        from django.urls import reverse

        return reverse("public_page", kwargs={"token": self.token})

    @property
    def is_live(self):
        return self.expires_at > timezone.now()
