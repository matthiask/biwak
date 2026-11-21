"""Managing organizations (specs/organizations.md, "Managing"): the
own staff create, rename and merge client and partner
organizations and change their domains; the audit log records it (the
trigger on the tables). Deleting only organizations without people.
Anything touching the own organization (merging into or out
of it, moving people in or out, marking it) is for admins only: it decides
who sees all-access projects."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from biwak.organizations.models import (
    DOMAIN,
    FREE_MAIL_DOMAINS,
    Organization,
    normalize_domain,
    normalize_name,
)


def _access_changed(people):
    """These people (IDs) may have stopped seeing all-access projects: their
    subscriptions in projects they can't open anymore go (like
    ``remove_member()``), and their open editors and pages check their
    access again after the commit. Call it after the change."""
    from biwak.accounts.models import User
    from biwak.collab import live
    from biwak.projects.operations import forget_lost_access

    for user in User.objects.filter(pk__in=set(people) - {None}):
        forget_lost_access(user)
        live.check_access(user=user.pk)


def can_manage(user):
    """Own staff; partners and clients don't learn which
    organizations and people there are"""
    return user.is_authenticated and user.is_active and user.sees_all_access


def can_touch(user, *organizations):
    """Whether the person may change who belongs to these organizations:
    admins any, other staff all but the own organization"""
    if not can_manage(user):
        return False
    if user.is_admin:
        return True
    return not any(org is not None and org.is_own for org in organizations)


def _no_admin_partners(admins, *, own_after):
    """Admins are always own staff (decided 2026-11-21):
    ``ValidationError`` if any of these admins would be in another
    organization than the own one (``own_after``) afterwards"""
    if admins and not own_after:
        names = ", ".join(sorted(str(user) for user in admins))
        raise ValidationError(
            _(
                "Admins are always in your own organization: make %(names)s"
                " no admin first."
            )
            % {"names": names}
        )


def _admins_in(org):
    """The admins of the organization"""
    from biwak.accounts.models import User

    return list(User.objects.filter(is_admin=True, organization=org))


def _check_manage(actor):
    if not can_manage(actor):
        raise PermissionError("Only staff manage organizations.")


def _check_touch(actor, *organizations):
    _check_manage(actor)
    if not can_touch(actor, *organizations):
        raise PermissionError(
            _("Only admins change who belongs to your own organization.")
        )


def clean_name(name, *, instance=None):
    """The normalized name, ``ValidationError`` when empty or taken
    (ignoring case and spaces)"""
    name = normalize_name(name)
    if not name:
        raise ValidationError(_("Enter a name."))
    taken = Organization.objects.filter(name__iexact=name)
    if instance is not None:
        taken = taken.exclude(pk=instance.pk)
    if taken.exists():
        raise ValidationError(
            _("There is an organization called “%(name)s” already.") % {"name": name}
        )
    return name


def clean_domains(domains, *, instance=None):
    """The normalized domains without duplicates, ``ValidationError`` for
    anything not a domain, free-mail domains and domains of another
    organization"""
    if isinstance(domains, str):
        domains = domains.replace(",", " ").split()
    result = []
    for raw in domains:
        domain = normalize_domain(raw)
        if not domain or domain in result:
            continue
        if not DOMAIN.match(domain):
            raise ValidationError(_("“%(domain)s” isn't a domain.") % {"domain": raw})
        if domain in FREE_MAIL_DOMAINS:
            raise ValidationError(
                _(
                    "%(domain)s is a free-mail domain: anybody can have an address"
                    " there."
                )
                % {"domain": domain}
            )
        other = Organization.objects.filter(domains__contains=[domain])
        if instance is not None:
            other = other.exclude(pk=instance.pk)
        if other := other.first():
            raise ValidationError(
                _("%(domain)s belongs to %(organization)s already.")
                % {"domain": domain, "organization": other}
            )
        result.append(domain)
    return result


@transaction.atomic
def create_organization(*, name, domains=(), actor):
    _check_manage(actor)
    org = Organization(name=clean_name(name), domains=clean_domains(domains))
    org.save()
    return org


@transaction.atomic
def update_organization(org, *, actor, name=None, domains=None):
    """Renames (once, for everybody) and replaces the domains, what's given"""
    _check_manage(actor)
    fields = []
    if name is not None and normalize_name(name) != org.name:
        org.name = clean_name(name, instance=org)
        fields.append("name")
    if domains is not None:
        cleaned = clean_domains(domains, instance=org)
        if cleaned != org.domains:
            org.domains = cleaned
            fields.append("domains")
    if fields:
        org.save(update_fields=fields)
    return org


@transaction.atomic
def merge(source, target, *, actor):
    """Moves the people and domains of ``source`` to ``target`` and deletes
    ``source`` (the typo case); returns ``target``"""
    if source.pk == target.pk:
        raise ValidationError(_("An organization can't be merged into itself."))
    _check_touch(actor, source, target)
    if source.is_own:
        raise ValidationError(
            _(
                "Your own organization always exists: merge"
                " %(organization)s into it instead."
            )
            % {"organization": target}
        )
    _no_admin_partners(_admins_in(source), own_after=target.is_own)
    moved = list(source.people.values_list("pk", flat=True))
    source.people.update(organization=target)
    domains = [d for d in source.domains if d not in target.domains]
    if domains:
        target.domains = [*target.domains, *domains]
        target.save(update_fields=["domains"])
    source.delete()
    _access_changed(moved)
    return target


@transaction.atomic
def delete_organization(org, *, actor):
    """Only organizations nobody belongs to, never the own organization"""
    _check_touch(actor, org)
    if org.is_own:
        raise ValidationError(
            _("Your own organization always exists: rename it instead.")
        )
    if org.people.exists():
        raise ValidationError(
            _("People belong to %(organization)s: merge it instead.")
            % {"organization": org}
        )
    org.delete()


@transaction.atomic
def set_organization(user, org, *, actor):
    """Moves the person into ``org`` (or none)"""
    if user.organization_id == (org.pk if org else None):
        return user
    _check_touch(actor, user.organization if user.organization_id else None, org)
    if user.is_admin:
        # Without an organization, staff are the own organization
        _no_admin_partners([user], own_after=org is not None and org.is_own)
    user.organization = org
    user.save(update_fields=["organization"])
    _access_changed([user.pk])
    return user


@transaction.atomic
def mark_own(org, *, actor):
    """Marks the own organization (admins only); exactly one
    is marked (decided 2026-11-21), so another one loses it"""
    if not (actor.is_authenticated and actor.is_admin):
        raise PermissionError(_("Only admins mark your own organization."))
    if org is None:
        raise ValidationError(
            _("There is always your own organization: mark another one instead.")
        )
    if org.is_own:
        return org
    for old in Organization.objects.filter(is_own=True):
        _no_admin_partners(_admins_in(old), own_after=False)
    unmarked = list(
        Organization.objects.filter(is_own=True).values_list("people", flat=True)
    )
    Organization.objects.filter(is_own=True).update(is_own=False)
    org.is_own = True
    org.save(update_fields=["is_own"])
    _access_changed(unmarked)
    return org


def for_new_person(email, org=None):
    """The organization of a person invited with ``email``: the one given,
    else the one whose domains include the address's (free-mail domains
    never match)"""
    return org or Organization.objects.for_email(email)
