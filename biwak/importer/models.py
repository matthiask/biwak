from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone


class ImportedObject(models.Model):
    """What Basecamp's recording (or person, project, attachment) became in
    Biwak: the mapping which makes a second run update instead of
    duplicating (specs/import-basecamp.md). ``basecamp_type`` is
    Basecamp's ``type`` ("Todo", "Message", ...) or one of our own labels
    for what has none ("Project", "Person", "Attachment",
    "Todolist::Group")."""

    basecamp_id = models.BigIntegerField()
    basecamp_type = models.CharField(max_length=50)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    imported_at = models.DateTimeField(default=timezone.now)
    # The recording's state when it was last read completely: a later run
    # skips it when both are the same (its comments and subscribers aren't
    # fetched again). Empty for what was imported before they were stored,
    # and for what has no ``updated_at``.
    basecamp_updated_at = models.DateTimeField(null=True, blank=True)
    basecamp_comments_count = models.PositiveIntegerField(null=True, blank=True)
    # A recording's object deleted in Biwak: never imported again (decided
    # 2026-11-28, specs/import-basecamp.md); when the import noticed
    deleted_at = models.DateTimeField(null=True, blank=True)
    # Trashed in Basecamp and so trashed in Biwak, once: restoring it in
    # Biwak sticks
    trashed_at = models.DateTimeField(null=True, blank=True)

    target = GenericForeignKey("content_type", "object_id")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["basecamp_id", "basecamp_type"],
                name="unique_imported_basecamp_object",
            )
        ]
        indexes = [models.Index(fields=["content_type", "object_id"])]

    def __str__(self):
        return f"{self.basecamp_type} {self.basecamp_id}"
