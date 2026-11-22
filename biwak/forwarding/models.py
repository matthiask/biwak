"""Forwarded mails (specs/forwarding.md): what staff forward to
``inbox@REPLY_DOMAIN``, kept for the forwarder only until they file it as a
message or a to-do, delete it, or 30 days have passed. Not items: nobody
but the forwarder sees them, and filing makes the item."""

import re

from django.conf import settings
from django.db import models, transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from biwak.files.models import KEY_CHARS, KEY_LENGTH, ContentTypeMixin, storage_name


# Unfiled mails are deleted after this many days by fairy_tasks
# (decided 2026-11-22)
KEEP_DAYS = 30
# How the text references the mail's files until it's filed:
# ![name](forwarded:KEY), [name](forwarded:KEY)
REFERENCE = re.compile(rf"\(forwarded:([{KEY_CHARS}]{{{KEY_LENGTH}}})\)")


class ForwardedMail(models.Model):
    """A forwarded mail: the original's subject, sender, date and
    recipients as far as they could be read from the forward (else the
    forwarder's mail as it is), its text as Markdown"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="forwarded_mails",
        verbose_name=_("forwarded by"),
    )
    received_at = models.DateTimeField(_("received at"), default=timezone.now)
    subject = models.CharField(_("subject"), max_length=500, blank=True)
    sender_name = models.CharField(_("sender's name"), max_length=300, blank=True)
    sender_email = models.CharField(_("sender's address"), max_length=300, blank=True)
    sent_on = models.DateField(_("sent on"), null=True, blank=True)
    to = models.TextField(_("to"), blank=True)
    cc = models.TextField(_("cc"), blank=True)
    # Markdown; the files as ``forwarded:KEY`` until filed
    text = models.TextField(_("text"), blank=True)

    class Meta:
        ordering = ["-received_at", "-pk"]
        indexes = [models.Index(fields=["user", "received_at"])]
        verbose_name = _("forwarded mail")
        verbose_name_plural = _("forwarded mails")

    def __str__(self):
        return self.subject or str(self.pk)

    @property
    def sender(self):
        """ "Ada Example <ada@example.org>", or whichever of the two is known"""
        if self.sender_name and self.sender_email:
            return f"{self.sender_name} <{self.sender_email}>"
        return self.sender_name or self.sender_email


def file_path(file, filename):
    """forwarded/<person>/<key>/<name>: paths can't be guessed"""
    return f"forwarded/{file.mail.user_id}/{file.key}/{storage_name(filename)}"


class ForwardedFile(ContentTypeMixin, models.Model):
    """An attachment of a forwarded mail (inline images too); filing copies
    it into an attachment of the item"""

    mail = models.ForeignKey(
        ForwardedMail,
        on_delete=models.CASCADE,
        related_name="files",
        verbose_name=_("forwarded mail"),
    )
    key = models.CharField(_("key"), max_length=KEY_LENGTH, unique=True)
    file = models.FileField(_("file"), upload_to=file_path, max_length=500)
    name = models.CharField(_("name"), max_length=255)
    size = models.PositiveBigIntegerField(_("size"))
    content_type = models.CharField(_("content type"), max_length=200)

    class Meta:
        ordering = ["pk"]
        verbose_name = _("forwarded file")
        verbose_name_plural = _("forwarded files")

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse(
            "forwarded_download",
            kwargs={"pk": self.mail_id, "key": self.key, "name": self.name},
        )

    @property
    def markdown(self):
        """What the text gets until it's filed: an image or a link"""
        name = re.sub(r"([\\\[\]])", r"\\\1", " ".join(self.name.split()))
        return f"{'!' if self.is_image else ''}[{name}](forwarded:{self.key})"


@receiver(post_delete, sender=ForwardedFile)
def delete_file(sender, instance, **kwargs):
    """Deleting the row (also through its mail) deletes the file, once the
    transaction commits"""
    name, storage = instance.file.name, instance.file.storage
    if name:
        transaction.on_commit(lambda: storage.delete(name))
