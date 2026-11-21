"""The People page (specs/organizations.md, decided 2026-11-21): everybody
the viewer may know, by organization: the own organization first, then the
other organizations by name, then people without one. Clients and partners
see the people they share a project with (the members rule of
specs/access.md), own staff everybody."""

from dataclasses import dataclass, field

from django.db.models import Q
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404, render
from django.utils.translation import gettext as _

from biwak.accounts import operations as accounts_ops
from biwak.accounts.models import User, own_staff
from biwak.activity.feed import people_visible_to
from biwak.organizations import operations as org_ops
from biwak.projects import operations as project_ops
from biwak.projects.models import Project, knows_everybody


@dataclass
class Group:
    organization: object  # None: people without one
    kind: str  # "own", "client", "partner" or "none"
    label: str
    people: list = field(default_factory=list)


def role(user):
    if user.is_client:
        return _("client")
    if user.is_admin:
        return _("admin")
    if user.is_partner:
        return _("partner")
    return _("staff")


def known_people(viewer):
    """The people the viewer may know (specs/people.md): everybody for the
    installation's own staff, else those they share a project with, and
    themselves; for partners also the own staff of the all-access projects
    they're in, who are among those projects' people (decided 2026-11-21,
    ``Project.people_q()``). The People page, the person's page, the
    images and the names use it."""
    people = User.objects.select_related("organization")
    if knows_everybody(viewer):
        return people
    shared = people_visible_to(viewer).values("pk")
    known = Q(pk__in=shared) | Q(pk=viewer.pk)
    if (
        viewer.is_authenticated
        and viewer.is_partner
        and Project.objects.accessible_to(viewer).filter(is_all_access=True).exists()
    ):
        known |= own_staff()
    return people.filter(known)


def decorate(user, viewer, shared):
    """What the People page and the person's page show of a person: ``role``,
    ``feed`` (whether the viewer may open their feed, ``shared`` are the
    people they share a project with), ``show_email`` and ``can_move`` (the
    existing "Change organization" modal)"""
    user.role = role(user)
    user.feed = user.pk in shared
    # Clients don't see addresses (as on a project's people page), but
    # those of their own organization
    user.show_email = not viewer.is_client or (
        viewer.organization_id is not None
        and user.organization_id == viewer.organization_id
    )
    user.can_move = org_ops.can_touch(viewer, user.organization)
    # Invited, not signed in yet (specs/ui-round-6.md): for the staff who
    # resend and withdraw invitations, with who invited them and when
    user.show_invitation = user.is_invited and project_ops.can_manage_members(viewer)
    return user


def groups_for(viewer):
    """The groups in the page's order, each person with ``role``,
    ``feed`` (whether the viewer may open their feed), ``show_email`` and
    ``can_move`` (the existing "Change organization" modal)"""
    shared = set(people_visible_to(viewer).values_list("pk", flat=True))
    people = (
        known_people(viewer)
        .select_related("invited_by")
        .order_by("-is_active", Lower("full_name"), "email")
    )
    own, others, without = None, {}, Group(None, "none", _("Without an organization"))
    for user in people:
        decorate(user, viewer, shared)
        org = user.organization
        if org is None:
            without.people.append(user)
        elif org.is_own:
            if own is None:
                own = Group(org, "own", _("Your own organization"))
            own.people.append(user)
        else:
            others.setdefault(org.pk, Group(org, "client", "")).people.append(user)
    for group in others.values():
        # A partner organization has staff, a client organization only clients
        if any(not user.is_client for user in group.people):
            group.kind, group.label = "partner", _("Partner organization")
        else:
            group.label = _("Client organization")
    ordered = sorted(others.values(), key=lambda g: g.organization.name.lower())
    return [g for g in [own, *ordered, without] if g is not None and g.people]


def invitations_for(viewer):
    """The "Invited" filter: everybody invited who hasn't signed in yet,
    the oldest invitation first (own staff, who manage members)"""
    shared = set(people_visible_to(viewer).values_list("pk", flat=True))
    return [
        decorate(user, viewer, shared)
        for user in User.objects.invited().select_related("organization", "invited_by")
    ]


def people(request):
    can_invite = project_ops.can_manage_members(request.user)
    invited = can_invite and bool(request.GET.get("invited"))
    return render(
        request,
        "organizations/people.html",
        {
            "groups": [] if invited else groups_for(request.user),
            "invited": invitations_for(request.user) if invited else None,
            "can_manage": org_ops.can_manage(request.user),
            "can_invite": can_invite,
        },
    )


def person(request, pk):
    """The person's page: the mark, name, organization, role and the
    projects both are in; for whoever may know the person (the rule of the
    People page), else 404"""
    viewer = request.user
    who = get_object_or_404(known_people(viewer).select_related("invited_by"), pk=pk)
    shared = set(people_visible_to(viewer).values_list("pk", flat=True))
    decorate(who, viewer, shared)
    projects = Project.objects.accessible_to(viewer).filter(memberships__user=who)
    if who.pk != viewer.pk:
        projects = projects.filter(memberships__user=viewer)
    return render(
        request,
        "organizations/person.html",
        {
            "person": who,
            "projects": projects.distinct(),
            "can_remove_image": bool(who.image)
            and accounts_ops.can_remove_image(viewer, who),
        },
    )
