"""All projects, for admins (specs/handover.md): every project with counts,
also those the admin can't open, to find what somebody who left leaves
behind. Counts only, no titles of to-dos and no people of projects the admin
can't open: joining is how an admin gets in. Four queries for any number
of projects."""

from django import forms
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Exists, IntegerField, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce, Lower
from django.http import Http404
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _

from biwak.forms import Form
from biwak.items.models import Assignment, Item, Kind, Status
from biwak.projects import operations as project_ops
from biwak.projects.models import Membership, Project


class AllProjectsFilter(Form):
    """The filters, each off by default (the empty choice, specs/ui.md)"""

    no_staff = forms.BooleanField(label=_("No active staff member"), required=False)
    limited = forms.BooleanField(label=_("Limited"), required=False)
    inactive = forms.BooleanField(
        label=_("With to-dos of inactive people"), required=False
    )
    archived = forms.BooleanField(label=_("Include archived"), required=False)


def _count(qs):
    """A subquery counting the rows of ``qs`` per project (0 for none)"""
    return Coalesce(
        Subquery(
            qs.order_by().values("project").annotate(n=Count("pk")).values("n"),
            output_field=IntegerField(),
        ),
        0,
    )


def can_see(user):
    """Who sees "All projects": admins (always the own staff)"""
    return user.is_authenticated and user.is_admin


def all_projects(
    user, *, no_staff=False, limited=False, inactive=False, archived=False
):
    """Every project (not archived ones unless ``archived``) by name, with
    ``active_staff`` (active staff and externals among the members),
    ``client_organizations`` (of the active client members, by name),
    ``open_todos`` and ``inactive_todos`` (open, with assignees who are
    all inactive) in lists not archived, ``can_open`` and ``joinable``
    (limited, not archived, the admin not a member: the projects page's
    joining); filtered as the arguments say"""
    open_todos = Item.objects.filter(
        project=OuterRef("pk"),
        kind=Kind.TODO,
        todo__completed_at__isnull=True,
        parent__status=Status.ACTIVE,
    ).exclude(status=Status.TRASHED)
    left_behind = open_todos.filter(
        Exists(Assignment.objects.filter(todo=OuterRef("pk"))),
        ~Exists(Assignment.objects.filter(todo=OuterRef("pk"), user__is_active=True)),
    )
    projects = Project.objects.annotate(
        active_staff=_count(
            Membership.objects.filter(
                project=OuterRef("pk"), user__is_active=True, user__is_client=False
            )
        ),
        open_todos=_count(open_todos),
        inactive_todos=_count(left_behind),
    ).order_by(Lower("name"), "pk")
    # Templates have their own page (specs/templates.md)
    projects = projects.filter(is_template=False)
    if not archived:
        projects = projects.filter(archived_at__isnull=True)
    if no_staff:
        projects = projects.filter(active_staff=0)
    if limited:
        projects = projects.filter(is_all_access=False)
    if inactive:
        projects = projects.filter(inactive_todos__gt=0)
    projects = list(projects)
    pks = [project.pk for project in projects]
    organizations = {}
    for project_id, name in (
        Membership.objects
        .filter(
            project__in=pks,
            user__is_active=True,
            user__is_client=True,
            user__organization__isnull=False,
        )
        .values_list("project", "user__organization__name")
        .distinct()
        .order_by("project", Lower("user__organization__name"))
    ):
        organizations.setdefault(project_id, []).append(name)
    can_open = set(
        Project.objects
        .accessible_to(user)
        .filter(Q(pk__in=pks))
        .values_list("pk", flat=True)
    )
    for project in projects:
        project.client_organizations = organizations.get(project.pk, [])
        project.can_open = project.pk in can_open
        project.joinable = (
            not project.can_open
            and not project.is_all_access
            and project.archived_at is None
        )
    return projects


def all_projects_page(request):
    """``/projects/all/``: the table with its filters; 404 for clients and
    externals, 403 for other staff (as activation's pages)"""
    user = request.user
    if not can_see(user):
        if user.is_client or not project_ops.can_manage_members(user):
            raise Http404
        raise PermissionDenied
    form = AllProjectsFilter(request.GET)
    data = form.cleaned_data if form.is_valid() else {}
    return render(
        request,
        "projects/all.html",
        {
            "form": form,
            "projects": all_projects(user, **data),
            # How many filters are set (the phones' "Filters" says it)
            "filtered": sum(1 for value in data.values() if value),
        },
    )
