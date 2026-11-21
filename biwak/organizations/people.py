"""The People page (specs/organizations.md, decided 2026-11-21): everybody
the viewer may know, by organization: the own organization first, then the
other organizations by name, then people without one. Clients and partners
see the people they share a project with (the members rule of
specs/access.md), own staff everybody."""

from dataclasses import dataclass, field

from django.db.models.functions import Lower
from django.shortcuts import render
from django.utils.translation import gettext as _

from biwak.accounts.models import User
from biwak.activity.feed import people_visible_to
from biwak.organizations import operations as org_ops
from biwak.projects.models import knows_everybody


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


def groups_for(viewer):
    """The groups in the page's order, each person with ``role``,
    ``feed`` (whether the viewer may open their feed), ``show_email`` and
    ``can_move`` (the existing "Change organization" modal)"""
    shared = set(people_visible_to(viewer).values_list("pk", flat=True))
    people = User.objects.select_related("organization")
    if not knows_everybody(viewer):
        people = people.filter(pk__in=shared | {viewer.pk})
    people = people.order_by("-is_active", Lower("full_name"), "email")
    own, others, without = None, {}, Group(None, "none", _("Without an organization"))
    for user in people:
        user.role = role(user)
        user.feed = user.pk in shared
        # Clients don't see addresses (as on a project's people page), but
        # those of their own organization
        user.show_email = not viewer.is_client or (
            viewer.organization_id is not None
            and user.organization_id == viewer.organization_id
        )
        user.can_move = org_ops.can_touch(viewer, user.organization)
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


def people(request):
    return render(
        request,
        "organizations/people.html",
        {
            "groups": groups_for(request.user),
            "can_manage": org_ops.can_manage(request.user),
        },
    )
