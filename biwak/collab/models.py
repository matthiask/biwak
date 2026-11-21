"""The shared state of docs edited live (specs/collaboration.md)

Machine state, not what people read: ``Doc.content`` stays the text, and
follows the state on a debounce. Neither table is in the audit log (a row
per keystroke); the changes of ``Doc.content`` are.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from biwak.items.models import Doc


class LiveState(models.Model):
    """The doc's Yjs document (``ytext.TEXT`` holds the Markdown) as of the
    last merge; its text equals ``Doc.content``"""

    doc = models.OneToOneField(
        Doc,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="live_state",
        verbose_name=_("doc"),
    )
    state = models.BinaryField(_("state"))
    updated_at = models.DateTimeField(_("updated at"), default=timezone.now)
    # Tells this history from one made later for the same doc (a row
    # deleted and made again): what editors keep in their browsers belongs
    # to one history (specs/connection.md)
    created_at = models.DateTimeField(_("created at"), default=timezone.now)

    class Meta:
        verbose_name = _("live state")
        verbose_name_plural = _("live states")

    def __str__(self):
        return f"{self.doc_id}"


class LiveUpdate(models.Model):
    """A Yjs update not merged into the state yet: what somebody typed (or
    an edit through the API), stored as it arrives so nothing is lost"""

    doc = models.ForeignKey(
        Doc,
        on_delete=models.CASCADE,
        related_name="live_updates",
        verbose_name=_("doc"),
    )
    data = models.BinaryField(_("data"))
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="+",
        verbose_name=_("user"),
    )
    created_at = models.DateTimeField(_("created at"), default=timezone.now)

    class Meta:
        ordering = ["pk"]
        verbose_name = _("live update")
        verbose_name_plural = _("live updates")

    def __str__(self):
        return f"{self.doc_id} ({self.created_at:%Y-%m-%d %H:%M:%S})"
