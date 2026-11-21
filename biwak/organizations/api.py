"""Organizations (biwak orgs, specs/organizations.md): for the installation's
own staff, like the pages; the same operations"""

from django.db.models import Count
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404
from django.utils.translation import gettext as _
from ninja import Router, Schema, Status
from ninja.errors import HttpError

from biwak.accounts.models import User
from biwak.api_conventions import PersonOut, absolute, person_out
from biwak.organizations import activation, operations as org_ops
from biwak.organizations.models import Organization
from biwak.projects import operations as project_ops


router = Router(tags=["organizations"])


class OrganizationOut(Schema):
    id: int
    name: str
    domains: list[str]
    # The own organization: its staff see all-access projects, staff of
    # the others (partners) only the projects they're members of
    is_own: bool
    # How its people sign in (specs/sso.md): "codes", "sso_allowed" or
    # "sso_required", and the identity provider ("google", "microsoft" or
    # empty); changed by admins on the organization's page only
    signin: str
    idp: str
    # A code alone isn't enough for its people (specs/two-factor.md)
    requires_two_factor: bool
    people_count: int
    url: str


class OrganizationDetailOut(OrganizationOut):
    people: list[PersonOut]


def organization_out(org, *, people=False):
    count = getattr(org, "people_count", None)
    if count is None:
        count = org.people.count()
    out = {
        "id": org.pk,
        "name": org.name,
        "domains": org.domains,
        "is_own": org.is_own,
        "signin": org.signin,
        "idp": org.sso,
        "requires_two_factor": org.two_factor_required,
        "people_count": count,
        "url": absolute(org.get_absolute_url()),
    }
    if people:
        out["people"] = [
            person_out(user)
            for user in org.people.select_related("organization").order_by(
                "full_name", "email"
            )
        ]
    return out


def managing(request):
    if not org_ops.can_manage(request.user):
        raise HttpError(403, _("Only staff manage organizations."))


def organization_for(request, pk):
    managing(request)
    return get_object_or_404(Organization, pk=pk)


def allowed(function, *args, **kwargs):
    """The operation, its ``PermissionError`` a 403"""
    try:
        return function(*args, **kwargs)
    except PermissionError as exc:
        raise HttpError(403, str(exc)) from exc


@router.get("organizations/", response=list[OrganizationOut])
def organization_list(request):
    """All organizations by name (own staff)"""
    managing(request)
    return [
        organization_out(org)
        for org in Organization.objects.annotate(people_count=Count("people")).order_by(
            Lower("name")
        )
    ]


class OrganizationIn(Schema):
    name: str
    # e.g. ["example.org"]; free-mail domains are refused
    domains: list[str] = []


@router.post("organizations/", response={201: OrganizationDetailOut})
def organization_create(request, data: OrganizationIn):
    managing(request)
    org = allowed(
        org_ops.create_organization,
        name=data.name,
        domains=data.domains,
        actor=request.user,
    )
    return Status(201, organization_out(org, people=True))


@router.get("organizations/{organization_id}/", response=OrganizationDetailOut)
def organization_detail(request, organization_id: int):
    return organization_out(organization_for(request, organization_id), people=True)


class OrganizationPatch(Schema):
    name: str | None = None
    # Replaces the domains
    domains: list[str] | None = None


@router.patch("organizations/{organization_id}/", response=OrganizationDetailOut)
def organization_update(request, organization_id: int, data: OrganizationPatch):
    """Renames (once, for everybody) and replaces the domains"""
    org = organization_for(request, organization_id)
    allowed(
        org_ops.update_organization,
        org,
        name=data.name,
        domains=data.domains,
        actor=request.user,
    )
    return organization_out(org, people=True)


class MergeIn(Schema):
    into_id: int
    # Merging into a stricter sign-in (admins only): confirms what happens
    # to the people (specs/sso.md)
    confirm: bool = False


@router.post("organizations/{organization_id}/merge/", response=OrganizationDetailOut)
def organization_merge(request, organization_id: int, data: MergeIn):
    """Moves the people and domains into ``into_id`` and deletes this one;
    returns the one merged into. The own organization: admins only."""
    org = organization_for(request, organization_id)
    target = organization_for(request, data.into_id)
    allowed(org_ops.merge, org, target, actor=request.user, confirmed=data.confirm)
    return organization_out(target, people=True)


@router.delete("organizations/{organization_id}/", response=OrganizationOut)
def organization_delete(request, organization_id: int):
    """Only organizations nobody belongs to (400 otherwise); returns it"""
    org = organization_for(request, organization_id)
    out = organization_out(org)
    allowed(org_ops.delete_organization, org, actor=request.user)
    return out


class PersonOrganizationIn(Schema):
    # null: none
    organization_id: int | None


@router.put("people/{person_id}/organization/", response=PersonOut)
def person_organization(request, person_id: int, data: PersonOrganizationIn):
    """Moves the person to another organization (or none); in or out of the
    own: admins only"""
    managing(request)
    user = get_object_or_404(User, pk=person_id)
    org = None
    if data.organization_id is not None:
        org = organization_for(request, data.organization_id)
    allowed(org_ops.set_organization, user, org, actor=request.user)
    return person_out(user)


# Activating and deactivating (specs/activation.md): own staff change
# clients, admins everybody; several at once are all or nothing


class AccessOut(PersonOut):
    email: str
    is_active: bool
    # Activated with the invitation mail, and it was sent: not to an
    # address that bounced
    mailed: bool = False


def access_out(user, *, mailed=False):
    return person_out(user) | {
        "email": user.email,
        "is_active": user.is_active,
        "mailed": mailed,
    }


class ActivateIn(Schema):
    # Send the invitation mail (not to addresses that bounced)
    mail: bool = False


class ActivateManyIn(ActivateIn):
    ids: list[int]


class DeactivateManyIn(Schema):
    ids: list[int]


def people_for(request, ids):
    """The people with these IDs for changing their access: 404 if one
    doesn't exist, 403 for clients; the operation checks who may"""
    if not project_ops.can_manage_members(request.user):
        raise HttpError(403, _("Only staff activate and deactivate people."))
    if not ids:
        raise HttpError(400, _("Nobody given."))
    ids = list(dict.fromkeys(ids))
    users = list(User.objects.filter(pk__in=ids).select_related("organization"))
    if len(users) != len(ids):
        raise HttpError(404, _("Not found."))
    return users


def changing(function, *args, **kwargs):
    """The operation: ``PermissionError`` a 403, a refusal a 400"""
    try:
        return function(*args, **kwargs)
    except PermissionError as exc:
        raise HttpError(403, str(exc)) from exc
    except activation.ActivationError as exc:
        raise HttpError(400, str(exc)) from exc


def activated(request, users, mail):
    done = {
        user.pk: mailed
        for user, mailed in changing(
            activation.activate, users, actor=request.user, mail=mail
        )
    }
    for user in users:
        user.refresh_from_db()
    return [access_out(user, mailed=done.get(user.pk, False)) for user in users]


@router.get("people/", response=list[AccessOut])
def people_list(request, *, inactive: bool = False):
    """The active people, or with ``inactive`` those who can't sign in,
    by name (own staff)"""
    if not project_ops.can_manage_members(request.user):
        raise HttpError(403, _("Only staff list people."))
    return [
        access_out(user)
        for user in User.objects
        .filter(is_active=not inactive)
        .select_related("organization")
        .order_by(Lower("full_name"), "email")
    ]


@router.post("people/activate/", response=list[AccessOut])
def people_activate(request, data: ActivateManyIn):
    """Activates several people, optionally mailing the invitation; all or
    nothing: staff change clients, admins everybody"""
    return activated(request, people_for(request, data.ids), data.mail)


@router.post("people/deactivate/", response=list[AccessOut])
def people_deactivate(request, data: DeactivateManyIn):
    """Deactivates several people and ends their access (sessions, API
    tokens, calendar links); all or nothing, not oneself, not the last
    active admin"""
    users = people_for(request, data.ids)
    changing(activation.deactivate, users, actor=request.user)
    for user in users:
        user.refresh_from_db()
    return [access_out(user) for user in users]


@router.post("people/{person_id}/activate/", response=AccessOut)
def person_activate(request, person_id: int, data: ActivateIn | None = None):
    """Activates the person (see ``people/activate/``)"""
    users = people_for(request, [person_id])
    return activated(request, users, bool(data and data.mail))[0]


class SignInOut(Schema):
    # The authenticator app
    app: bool
    passkeys: int
    api_tokens: int


class SignInResetOut(AccessOut):
    # Whether there was anything to remove (and the person was signed out
    # and mailed)
    reset: bool
    # What was removed
    removed: SignInOut


@router.post("people/{person_id}/reset-sign-in/", response=SignInResetOut)
@router.post(
    "people/{person_id}/reset-two-factor/",
    response=SignInResetOut,
    url_name="person_reset_two_factor",
    include_in_schema=False,
)
def person_reset_sign_in(request, person_id: int):
    """Removes the person's authenticator app, passkeys and API tokens, ends
    their sessions and mails them what was removed (specs/two-factor.md);
    staff reset clients, admins everybody, not oneself. With none of them
    nothing happens (``reset`` false). ``reset-two-factor/`` is the old
    URL, kept as an alias."""
    [user] = people_for(request, [person_id])
    removed = changing(activation.reset_sign_in, user, actor=request.user)
    return access_out(user) | {"reset": bool(removed), "removed": removed._asdict()}


@router.post("people/{person_id}/deactivate/", response=AccessOut)
def person_deactivate(request, person_id: int):
    """Deactivates the person (see ``people/deactivate/``)"""
    [user] = people_for(request, [person_id])
    changing(activation.deactivate, [user], actor=request.user)
    user.refresh_from_db()
    return access_out(user)
