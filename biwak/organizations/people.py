"""The People page (specs/organizations.md, decided 2026-11-21): everybody
the viewer may know, by organization: the own organization first, then the
other organizations by name, then people without one. Clients and partners
see the people they share a project with (the members rule of
specs/access.md), own staff everybody."""

from dataclasses import dataclass, field

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.db.models.functions import Lower
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _, gettext_lazy

from biwak.accounts import operations as accounts_ops, two_factor
from biwak.accounts.models import User, own_staff
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
    addable: int = 0  # project_groups(): active people who aren't members


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
    user.can_move = org_ops.can_touch(viewer, user.organization, person=user)
    # Invited, not signed in yet (specs/activation.md, "Invitations"): for the staff who
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
    people = list(
        known_people(viewer)
        .select_related("invited_by")
        .order_by("-is_active", Lower("full_name"), "email")
    )
    _note_partners(viewer, people)
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


def project_groups(project, rows, *, can_add):
    """A project's members by organization (specs/organizations.md, decided
    2026-11-21): the own staff first, then the client organizations, then
    the partner organizations (by name; partner: a member is staff), then
    people without one. ``rows`` are ``(membership, anything)`` pairs in
    the order shown within a group. With ``can_add`` each organization's
    group says how many of its active people aren't members yet
    (``group.addable``, for "Add people from …")."""
    own, clients, partners = None, {}, {}
    without = Group(None, "none", _("Without an organization"))
    for row in rows:
        org = row[0].user.organization
        if org is None:
            without.people.append(row)
        elif org.is_own:
            if own is None:
                own = Group(org, "own", _("Your own organization"))
            own.people.append(row)
        else:
            clients.setdefault(org.pk, Group(org, "client", "")).people.append(row)
    for pk, group in list(clients.items()):
        if any(not m.user.is_client for m, *_rest in group.people):
            group.kind, group.label = "partner", _("Partner organization")
            partners[pk] = clients.pop(pk)
        else:
            group.label = _("Client organization")

    def by_name(groups):
        return sorted(groups.values(), key=lambda g: g.organization.name.lower())

    groups = [own, *by_name(clients), *by_name(partners)]
    groups = [g for g in groups if g is not None]
    if can_add and groups:
        addable = dict(
            project_ops
            .addable_people(project)
            .filter(organization__in=[g.organization for g in groups])
            .values_list("organization")
            .annotate(count=Count("pk"))
            .order_by()
        )
        for group in groups:
            group.addable = addable.get(group.organization.pk, 0)
    if without.people:
        groups.append(without)
    return groups


def invitations_for(viewer):
    """The "Invited" filter: everybody invited who hasn't signed in yet,
    the oldest invitation first (own staff, who manage members)"""
    shared = set(people_visible_to(viewer).values_list("pk", flat=True))
    people = list(User.objects.invited().select_related("organization", "invited_by"))
    _note_partners(viewer, people)
    return [decorate(user, viewer, shared) for user in people]


def _note_partners(viewer, people):
    """Which of their organizations are partners', one query instead of
    one per person for ``can_move`` (staff who aren't admins)"""
    if org_ops.can_manage(viewer) and not viewer.is_admin:
        org_ops.note_partners([user.organization for user in people])


def inactive_for(viewer):
    """The "Inactive" filter: people who can't sign in, by name"""
    shared = set(people_visible_to(viewer).values_list("pk", flat=True))
    people = list(
        known_people(viewer)
        .filter(is_active=False)
        .select_related("organization")
        .order_by(Lower("full_name"), "email")
    )
    _note_partners(viewer, people)
    return [decorate(user, viewer, shared) for user in people]


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
    # Reset two-factor… (specs/two-factor.md): only for somebody with an app
    who.can_reset_two_factor = activation.can_reset_two_factor(
        viewer, who
    ) and two_factor.has_app(who)
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


def person_reset_two_factor(request, pk):
    """Reset two-factor…: the question, then deleting their authenticator
    app, ending their sessions and mailing them (specs/two-factor.md)"""
    who = person_to_change(request, pk)
    if not two_factor.has_app(who):
        messages.info(
            request,
            _("%(name)s has no authenticator app.") % {"name": who.display_name},
        )
        return redirect(back(request, who))
    if request.method == "POST":
        try:
            activation.reset_two_factor(who, actor=request.user)
        except activation.ActivationError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(
                request,
                _(
                    "The authenticator app of %(name)s has been removed; they"
                    " got a mail about it."
                )
                % {"name": who.display_name},
            )
        return redirect(back(request, who))
    return form_response(
        request,
        None,
        title=_("Reset two-factor for %(name)s?") % {"name": who.display_name},
        intro=_(
            "Removes their authenticator app and signs them out everywhere."
            " They sign in with a code or a passkey then and can set up an"
            " app again. They get a mail about it."
        ),
        cancel_url=back(request, who),
        submit_label=_("Reset"),
        destructive=True,
        help_page="sign-in",
    )
