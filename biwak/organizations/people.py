"""The People page (specs/organizations.md, decided 2026-11-21): everybody
the viewer may know, by organization: the own organization first, then the
other organizations by name, then people without one. Clients and partners
see the people they share a project with (the members rule of
specs/access.md), own staff everybody."""

from dataclasses import dataclass, field

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.db.models.functions import Lower
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _, gettext_lazy

from biwak.accounts import operations as accounts_ops
from biwak.accounts.models import User
from biwak.activity.feed import people_visible_to
from biwak.forms import Form, next_url
from biwak.modals import form_response
from biwak.organizations import activation, operations as org_ops
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
    themselves. The People page, the person's page and the images use it."""
    people = User.objects.select_related("organization")
    if knows_everybody(viewer):
        return people
    shared = people_visible_to(viewer).values("pk")
    return people.filter(Q(pk__in=shared) | Q(pk=viewer.pk))


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
    # Activating and deactivating (specs/activation.md)
    user.can_activate = not user.is_active and activation.can_change(viewer, user)
    user.can_deactivate = user.is_active and activation.can_deactivate(viewer, user)
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


def inactive_for(viewer):
    """The "Inactive" filter: people who can't sign in, by name"""
    shared = set(people_visible_to(viewer).values_list("pk", flat=True))
    return [
        decorate(user, viewer, shared)
        for user in known_people(viewer)
        .filter(is_active=False)
        .order_by(Lower("full_name"), "email")
    ]


def people(request):
    can_invite = project_ops.can_manage_members(request.user)
    invited = can_invite and bool(request.GET.get("invited"))
    inactive = can_invite and not invited and bool(request.GET.get("inactive"))
    return render(
        request,
        "organizations/people.html",
        {
            "groups": [] if invited or inactive else groups_for(request.user),
            "invited": invitations_for(request.user) if invited else None,
            "inactive": inactive_for(request.user) if inactive else None,
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


class ActivateForm(Form):
    mail = forms.BooleanField(
        label=gettext_lazy("Send the invitation mail"),
        required=False,
        help_text=gettext_lazy(
            "Names the projects they are in; they show as invited until they sign in."
        ),
    )


def person_to_change(request, pk):
    """The person whose access the actor may change: 404 for clients (as
    the people pages), 403 for staff who may not change this one"""
    if not project_ops.can_manage_members(request.user):
        raise Http404
    who = get_object_or_404(known_people(request.user), pk=pk)
    if not activation.can_change(request.user, who):
        raise PermissionDenied
    return who


def back(request, who):
    return next_url(request) or reverse("person", args=[who.pk])


def person_activate(request, pk):
    """Activate…: a modal, also a page, with the choice of the mail"""
    who = person_to_change(request, pk)
    if who.is_active:
        return redirect(back(request, who))
    form = ActivateForm(request.POST if request.method == "POST" else None)
    if form.is_valid():
        [(_user, mailed)] = activation.activate(
            [who], actor=request.user, mail=form.cleaned_data["mail"]
        )
        messages.success(
            request,
            _("%(name)s has been activated.") % {"name": who.display_name}
            + (" " + _("The invitation mail is on its way.") if mailed else ""),
        )
        if form.cleaned_data["mail"] and not mailed:
            messages.warning(
                request,
                _("Mail to %(email)s bounced: no invitation mail was sent.")
                % {"email": who.email},
            )
        return redirect(back(request, who))
    return form_response(
        request,
        form,
        title=_("Activate %(name)s?") % {"name": who.display_name},
        intro=_(
            "They can sign in again and get notifications. Nothing else"
            " changes. If their address bounced, the mail isn't sent."
        ),
        cancel_url=back(request, who),
        submit_label=_("Activate"),
    )


def person_deactivate(request, pk):
    """Deactivate…: the question, then ending their access"""
    who = person_to_change(request, pk)
    if request.method == "POST":
        try:
            activation.deactivate([who], actor=request.user)
        except activation.ActivationError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(
                request,
                _("%(name)s has been deactivated.") % {"name": who.display_name},
            )
        return redirect(back(request, who))
    return form_response(
        request,
        None,
        title=_("Deactivate %(name)s?") % {"name": who.display_name},
        intro=_(
            "They are signed out everywhere, their API tokens and calendar"
            " link are deleted, and they can't sign in until somebody"
            " activates them again. What they did stays."
        ),
        cancel_url=back(request, who),
        submit_label=_("Deactivate"),
        destructive=True,
    )
