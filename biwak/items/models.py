"""Items: everything other features point at (specs/core.md)

Delegated types like Basecamp's recordings and recordables: ``Item`` holds
what every item has, one detail model per kind the rest, sharing the
item's primary key. Create items through ``biwak.items.operations``, which
writes both rows, the event and the subscriptions.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from tree_queries.models import TreeNode
from tree_queries.query import TreeQuerySet

from biwak import schedules
from biwak.projects.models import Project


class Kind(models.TextChoices):
    LIST = "list", _("to-do list")
    TODO = "todo", _("to-do")
    MESSAGE = "message", _("message")
    FOLDER = "folder", _("folder")
    DOC = "doc", _("doc")
    FILE = "file", _("file")


# Allowed parents per kind; None is the project's top level (lists, the
# message board, the root folder)
ALLOWED_PARENTS = {
    Kind.LIST: {None},
    Kind.TODO: {Kind.LIST},
    Kind.MESSAGE: {None},
    Kind.FOLDER: {None, Kind.FOLDER},
    Kind.DOC: {None, Kind.FOLDER},
    Kind.FILE: {None, Kind.FOLDER},
}

# Kinds with a "visible to clients" switch when at the top level; their
# descendants inherit it (specs/access.md)
SWITCHABLE = {Kind.LIST, Kind.MESSAGE, Kind.FOLDER, Kind.DOC, Kind.FILE}

# Kinds people can comment on (no comments on lists and folders)
COMMENTABLE = {Kind.TODO, Kind.MESSAGE, Kind.DOC, Kind.FILE}


class Status(models.TextChoices):
    ACTIVE = "active", _("active")
    ARCHIVED = "archived", _("archived")
    TRASHED = "trashed", _("trashed")


class ItemQuerySet(TreeQuerySet):
    def visible_to(self, user, *, with_trashed=False):
        """The only place deciding who sees which item (specs/access.md):
        items of accessible projects, not trashed (unless ``with_trashed``,
        for the trash), and for clients only those visible to clients. A
        filter on stored columns, no recursive query."""
        if not user.is_authenticated or not user.is_active:
            return self.none()
        qs = self.filter(project__in=Project.objects.accessible_to(user))
        if not with_trashed:
            qs = qs.exclude(status=Status.TRASHED)
        if user.is_client:
            qs = qs.filter(is_client_visible=True)
        return qs


class Item(TreeNode):
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name=_("project"),
    )
    kind = models.CharField(_("kind"), max_length=20, choices=Kind)
    # Within the parent; to-dos within their list and group
    position = models.PositiveIntegerField(_("position"), default=0)
    title = models.CharField(_("title"), max_length=500)
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("creator"),
    )
    created_at = models.DateTimeField(_("created at"), default=timezone.now)
    updated_at = models.DateTimeField(_("updated at"), default=timezone.now)
    status = models.CharField(
        _("status"), max_length=20, choices=Status, default=Status.ACTIVE
    )
    trashed_at = models.DateTimeField(_("trashed at"), null=True, blank=True)
    # The switch, only meaningful on SWITCHABLE kinds at the top level
    visible_to_clients = models.BooleanField(_("visible to clients"), default=False)
    # The effective visibility, stored (biwak.items.visibility)
    is_client_visible = models.BooleanField(
        _("is visible to clients"), default=False, editable=False
    )

    objects = ItemQuerySet.as_manager()

    class Meta:
        ordering = ["position", "pk"]
        indexes = [
            models.Index(fields=["project", "kind", "status"]),
            models.Index(fields=["parent", "position"]),
        ]
        verbose_name = _("item")
        verbose_name_plural = _("items")

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse(self.kind, kwargs={"pk": self.pk})

    @property
    def has_switch(self):
        """Whether the item has a visibility switch of its own"""
        return self.kind in SWITCHABLE and self.parent_id is None

    @property
    def is_commentable(self):
        return self.kind in COMMENTABLE

    @property
    def detail(self):
        """The kind's detail model"""
        return getattr(
            self, {Kind.LIST: "todolist", Kind.FILE: "upload"}.get(self.kind, self.kind)
        )

    def clean(self):
        super().clean()
        parent_kind = self.parent.kind if self.parent_id else None
        if parent_kind not in ALLOWED_PARENTS[self.kind]:
            raise ValidationError(
                _("A %(kind)s can't be inside a %(parent)s.")
                % {
                    "kind": Kind(self.kind).label,
                    "parent": Kind(parent_kind).label if parent_kind else _("project"),
                }
            )
        if self.parent_id and self.parent.project_id != self.project_id:
            raise ValidationError(_("The parent belongs to another project."))
        if self.visible_to_clients and not self.has_switch:
            raise ValidationError(
                _(
                    "Only top-level lists, folders, messages, docs and files have"
                    " a switch."
                )
            )

    def save(self, *args, **kwargs):
        # Enforced in the model, not only in forms (specs/core.md)
        self.full_clean(validate_unique=False, validate_constraints=False)
        super().save(*args, **kwargs)


class Detail(models.Model):
    """Shares the item's primary key"""

    item = models.OneToOneField(
        Item,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="%(class)s",
        verbose_name=_("item"),
    )

    class Meta:
        abstract = True

    def __str__(self):
        return str(self.item)


class TodoList(Detail):
    class View(models.TextChoices):
        LIST = "list", _("list")
        BOARD = "board", _("board")

    description = models.TextField(_("description"), blank=True)
    view = models.CharField(
        _("view"), max_length=10, choices=View.choices, default=View.LIST
    )

    class Meta:
        verbose_name = _("to-do list")
        verbose_name_plural = _("to-do lists")


class Group(models.Model):
    """A heading within a list; not an item (specs/core.md). To-dos point at
    it and are ordered within it; ungrouped to-dos come first."""

    todolist = models.ForeignKey(
        TodoList,
        on_delete=models.CASCADE,
        related_name="groups",
        verbose_name=_("to-do list"),
    )
    title = models.CharField(_("title"), max_length=200)
    position = models.PositiveIntegerField(_("position"), default=0)

    class Meta:
        ordering = ["position", "pk"]
        verbose_name = _("group")
        verbose_name_plural = _("groups")

    def __str__(self):
        return self.title


class Todo(Detail):
    notes = models.TextField(_("notes"), blank=True)
    group = models.ForeignKey(
        Group,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="todos",
        verbose_name=_("group"),
    )
    starts_on = models.DateField(_("starts on"), null=True, blank=True)
    due_on = models.DateField(_("due on"), null=True, blank=True)
    completed_at = models.DateTimeField(_("completed at"), null=True, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("completed by"),
    )
    assignees = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="assigned_todos",
        verbose_name=_("assignees"),
    )
    # Recurrence (specs/todos.md): an RRULE (biwak.schedules), empty for
    # none; completing creates the next to-do
    recurrence = models.CharField(_("repeats"), max_length=200, blank=True)
    recurrence_ends_on = models.DateField(_("repeats until"), null=True, blank=True)
    # How many more to-dos are created after this one, None: no limit
    recurrence_count = models.PositiveIntegerField(
        _("repeats left"), null=True, blank=True
    )
    previous = models.ForeignKey(
        Item,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="following",
        verbose_name=_("previous"),
    )

    class Meta:
        verbose_name = _("to-do")
        verbose_name_plural = _("to-dos")

    @property
    def is_completed(self):
        return self.completed_at is not None

    @property
    def recurrence_description(self):
        return schedules.describe(self.recurrence)


class MessageCategory(models.Model):
    """One list for the installation, edited by admins (specs/files.md)"""

    name = models.CharField(_("name"), max_length=100)
    emoji = models.CharField(_("emoji"), max_length=20, blank=True)
    position = models.PositiveIntegerField(_("position"), default=0)

    class Meta:
        ordering = ["position", "name", "pk"]
        verbose_name = _("message category")
        verbose_name_plural = _("message categories")

    def __str__(self):
        return f"{self.emoji} {self.name}".strip()


class Message(Detail):
    content = models.TextField(_("content"), blank=True)
    category = models.ForeignKey(
        MessageCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="messages",
        verbose_name=_("category"),
    )
    # Pinned for everybody, by staff; the latest pinned first. Kept when
    # the message is trashed, so restoring brings the pin back.
    pinned_at = models.DateTimeField(_("pinned at"), null=True, blank=True)

    class Meta:
        verbose_name = _("message")
        verbose_name_plural = _("messages")

    @property
    def is_pinned(self):
        return self.pinned_at is not None


class Folder(Detail):
    class Meta:
        verbose_name = _("folder")
        verbose_name_plural = _("folders")


class Doc(Detail):
    content = models.TextField(_("content"), blank=True)
    # The lock until real-time editing (specs/files.md): who is editing,
    # renewed every minute, expiring 5 minutes after the last renewal
    locked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name=_("locked by"),
    )
    locked_at = models.DateTimeField(_("locked at"), null=True, blank=True)

    class Meta:
        verbose_name = _("doc")
        verbose_name_plural = _("docs")


class DocVersion(models.Model):
    """What a doc said at some point; the newest equals the doc's content"""

    doc = models.ForeignKey(
        Doc,
        on_delete=models.CASCADE,
        related_name="versions",
        verbose_name=_("doc"),
    )
    title = models.CharField(_("title"), max_length=500)
    content = models.TextField(_("content"), blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("created by"),
    )
    created_at = models.DateTimeField(_("created at"), default=timezone.now)

    class Meta:
        ordering = ["-created_at", "-pk"]
        verbose_name = _("doc version")
        verbose_name_plural = _("doc versions")

    def __str__(self):
        return f"{self.title} ({self.created_at:%Y-%m-%d %H:%M})"


class Upload(Detail):
    """The detail of a file; its versions (``biwak.files.models.FileVersion``)
    hold the files themselves, the newest is the current one"""

    description = models.TextField(_("description"), blank=True)

    class Meta:
        verbose_name = _("file")
        verbose_name_plural = _("files")


class Comment(models.Model):
    """On to-dos, messages and docs; visible wherever the item is"""

    item = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name="comments",
        verbose_name=_("item"),
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        verbose_name=_("author"),
    )
    content = models.TextField(_("content"))
    created_at = models.DateTimeField(_("created at"), default=timezone.now)
    updated_at = models.DateTimeField(_("updated at"), default=timezone.now)

    class Meta:
        ordering = ["created_at", "pk"]
        verbose_name = _("comment")
        verbose_name_plural = _("comments")

    def __str__(self):
        return f"{self.author} on {self.item}"

    def save(self, *args, **kwargs):
        self.full_clean(validate_unique=False, validate_constraints=False)
        super().save(*args, **kwargs)

    def clean(self):
        if not self.item.is_commentable:
            raise ValidationError(_("Lists and folders have no comments."))
