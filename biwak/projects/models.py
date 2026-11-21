from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from biwak.accounts.models import Color


def knows_everybody(viewer):
    """Whether the viewer may learn about people who aren't members of the
    project: the installation's own staff, not partners, not clients and
    not nobody (mails rendered for nobody in particular)"""
    return viewer is not None and viewer.is_authenticated and viewer.sees_all_access


class ProjectQuerySet(models.QuerySet):
    def accessible_to(self, user):
        """The projects a person may open (specs/access.md): the
        installation's own staff all all-access projects and those they're
        members of, partners (staff of other organizations) and clients
        only those they're members of. Admins aren't special here: they see
        limited projects in the list of all projects, not their content."""
        if not user.is_authenticated or not user.is_active:
            return self.none()
        members = Q(memberships__user=user)
        if not user.sees_all_access:
            return self.filter(members).distinct()
        return self.filter(members | Q(is_all_access=True)).distinct()

    def active(self):
        return self.filter(archived_at__isnull=True)


class Project(models.Model):
    name = models.CharField(_("name"), max_length=200)
    description = models.TextField(_("description"), blank=True)
    is_all_access = models.BooleanField(
        _("all-access"),
        default=True,
        help_text=_(
            "All staff can see all-access projects. Limited projects are only"
            " visible to their members. Clients only ever see projects they're"
            " members of."
        ),
    )
    color = models.CharField(
        _("color"),
        max_length=10,
        blank=True,
        choices=Color,
        help_text=_("Tells projects apart on cards, headers and next to names."),
    )
    created_at = models.DateTimeField(_("created at"), default=timezone.now)
    archived_at = models.DateTimeField(_("archived at"), null=True, blank=True)
    # Stored by record() and recomputed nightly (specs/projects-overview.md);
    # the client column only counts events of items visible to clients, so
    # internal work never reorders or dates a client's projects
    last_activity_at = models.DateTimeField(
        _("last activity at"), null=True, blank=True, db_index=True, editable=False
    )
    last_client_activity_at = models.DateTimeField(
        _("last client activity at"),
        null=True,
        blank=True,
        db_index=True,
        editable=False,
    )

    objects = ProjectQuerySet.as_manager()

    class Meta:
        ordering = [Lower("name")]
        verbose_name = _("project")
        verbose_name_plural = _("projects")

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("project", kwargs={"pk": self.pk})

    def is_accessible_to(self, user):
        return Project.objects.accessible_to(user).filter(pk=self.pk).exists()

    @property
    def color_label(self):
        """The color's name, empty without a color"""
        return self.get_color_display() if self.color else ""

    def is_member(self, user):
        return self.memberships.filter(user=user).exists()

    def people_known_to(self, viewer, people):
        """Those of ``people`` the viewer may see named: everybody for the
        installation's own staff, the members for clients, partners and for
        nobody in particular (as on the project page; staff of all-access
        projects needn't be members).
        ``biwak.activity.mentions.known_to()`` is the same for querysets."""
        people = list(people)
        if knows_everybody(viewer):
            return people
        members = set(self.memberships.values_list("user", flat=True))
        return [user for user in people if user.pk in members]

    @property
    def description_first_line(self):
        """For the cards of the projects page"""
        return next(
            (line for line in self.description.splitlines() if line.strip()), ""
        )


class Membership(models.Model):
    """Members are listed, mentionable by default and included when someone
    notifies "everybody in the project". Joining subscribes to nothing that
    exists already (specs/notifications.md)."""

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="memberships",
        verbose_name=_("project"),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="memberships",
        verbose_name=_("person"),
    )
    created_at = models.DateTimeField(_("created at"), default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project", "user"], name="unique_project_member"
            )
        ]
        verbose_name = _("membership")
        verbose_name_plural = _("memberships")

    def __str__(self):
        return f"{self.user} in {self.project}"
