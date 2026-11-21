"""The projects page and the API's list (specs/projects-overview.md):
active projects with favorites first, ordered by activity or name, in a
fixed number of queries however many projects there are."""

from django.db import models
from django.db.models import Count, Exists, F, OuterRef, Q
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from biwak import schedules
from biwak.bookmarks.models import Bookmark
from biwak.items import due
from biwak.projects.models import Membership, Project


class ProjectOrder(models.TextChoices):
    ACTIVITY = "activity", _("Activity")
    NAME = "name", _("A–Z")


def activity_column(user):
    """Clients see and sort by the time of what they see; staff by all"""
    return "last_client_activity_at" if user.is_client else "last_activity_at"


def overview(user, order=None):
    """Active projects with ``is_bookmarked``, ``activity`` (the time
    matching the person), ``has_clients`` (staff only; always false for
    clients) and the person's ``open_count`` and ``overdue_count`` of
    to-dos, which are zero when there are none."""
    order = order or ProjectOrder.ACTIVITY
    projects = (
        Project.objects
        .accessible_to(user)
        .active()
        .annotate(
            is_bookmarked=Exists(
                Bookmark.objects.filter(user=user, project=OuterRef("pk"))
            ),
            activity=F(activity_column(user)),
            user_is_member=Exists(
                Membership.objects.filter(project=OuterRef("pk"), user=user)
            ),
        )
    )
    if user.is_client:
        has_clients = False
    else:
        projects = projects.annotate(
            has_clients=Exists(
                Membership.objects.filter(project=OuterRef("pk"), user__is_client=True)
            )
        )
    if order == ProjectOrder.NAME:
        projects = projects.order_by("-is_bookmarked", Lower("name"), "pk")
    else:
        # Projects without events last, by name
        projects = projects.order_by(
            "-is_bookmarked", F("activity").desc(nulls_last=True), Lower("name"), "pk"
        )
    projects = list(projects)
    counts = {
        row["project_id"]: row
        for row in due
        .todos(user, assignee="me")
        .order_by()
        .values("project_id")
        .annotate(
            open=Count("pk", distinct=True),
            overdue=Count(
                "pk", distinct=True, filter=Q(todo__due_on__lt=schedules.today())
            ),
        )
    }
    for project in projects:
        row = counts.get(project.pk, {})
        project.open_count = row.get("open", 0)
        project.overdue_count = row.get("overdue", 0)
        if user.is_client:
            project.has_clients = has_clients
    return projects
