"""Teams (specs/teams.md): named sets of people for picking several at
once. A team is a shortcut, not a thing items point at: picking it adds its
members, and only the people are stored. Only staff (own staff and
partners) see teams; own staff manage them."""

from django.conf import settings
from django.db import models
from django.db.models.functions import Lower
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Team(models.Model):
    name = models.CharField(_("name"), max_length=100)
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="TeamMember",
        related_name="teams",
        verbose_name=_("members"),
    )
    created_at = models.DateTimeField(_("created at"), default=timezone.now)

    class Meta:
        verbose_name = _("team")
        verbose_name_plural = _("teams")
        constraints = [
            # Unique ignoring case (stored with single spaces)
            models.UniqueConstraint(Lower("name"), name="teams_team_name_unique")
        ]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("team", args=[self.pk])


class TeamMember(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="memberships")
    # Deleting a person's account removes them; deactivating keeps them
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="team_memberships",
    )
    created_at = models.DateTimeField(_("created at"), default=timezone.now)

    class Meta:
        verbose_name = _("team member")
        verbose_name_plural = _("team members")
        constraints = [
            models.UniqueConstraint(
                fields=["team", "user"], name="teams_teammember_unique"
            )
        ]

    def __str__(self):
        return f"{self.user} in {self.team}"
