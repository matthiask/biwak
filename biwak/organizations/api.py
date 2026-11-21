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
from biwak.organizations import operations as org_ops
from biwak.organizations.models import Organization


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


@router.post("organizations/{organization_id}/merge/", response=OrganizationDetailOut)
def organization_merge(request, organization_id: int, data: MergeIn):
    """Moves the people and domains into ``into_id`` and deletes this one;
    returns the one merged into. The own organization: admins only."""
    org = organization_for(request, organization_id)
    target = organization_for(request, data.into_id)
    allowed(org_ops.merge, org, target, actor=request.user)
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
