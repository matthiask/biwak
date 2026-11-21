"""Managing organizations (specs/organizations.md, "Managing"): the
own staff create, rename and merge client organizations and change their
domains; the audit log records it (the trigger on the tables). Deleting
only organizations without people. Anything touching the own organization
or a partner organization (merging into or out of it, moving people in or
out, inviting people into it, its domains, marking the own) and moving
staff is for admins only: admins manage the internal team and partners,
staff the clients (decided 2026-11-21); it decides who sees which
projects."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _, gettext_lazy as _lazy

from biwak.organizations.models import (
    DOMAIN,
    FREE_MAIL_DOMAINS,
    MICROSOFT_CONSUMER_TENANT,
    IdP,
    Organization,
    SignIn,
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


def is_partner_organization(org):
    """Whether staff belong to it and it isn't the own organization: a
    partner organization (as on the People page); remembered on the
    object, ``note_partners()`` does it for many at once"""
    if org is None or org.is_own:
        return False
    if getattr(org, "_is_partner", None) is None:
        org._is_partner = org.people.filter(is_client=False).exists()
    return org._is_partner


def partner_organizations():
    """The organizations ``is_partner_organization()`` is true for"""
    return Organization.objects.filter(is_own=False, pk__in=_staff_organizations())


def _staff_organizations():
    from biwak.accounts.models import User

    return User.objects.filter(is_client=False, organization__isnull=False).values(
        "organization"
    )


def note_partners(organizations):
    """``is_partner_organization()`` for these at once, one query"""
    organizations = [org for org in organizations if org is not None]
    partners = set(
        partner_organizations()
        .filter(pk__in={org.pk for org in organizations})
        .values_list("pk", flat=True)
    )
    for org in organizations:
        org._is_partner = org.pk in partners


def can_touch(user, *organizations, person=None):
    """Whether the person may change who belongs to these organizations
    (and move ``person``): admins any; other staff only client
    organizations and only clients, not the own organization, partner
    organizations or staff (decided 2026-11-21: admins manage the internal
    team and partners, staff the clients)"""
    if not can_manage(user):
        return False
    if user.is_admin:
        return True
    if person is not None and not person.is_client:
        return False
    return not any(
        org is not None and (org.is_own or is_partner_organization(org))
        for org in organizations
    )


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


TOUCH_MESSAGE = _lazy(
    "Only admins change who belongs to your own organization or a partner"
    " organization, and move staff."
)


def _check_touch(actor, *organizations, person=None):
    _check_manage(actor)
    if not can_touch(actor, *organizations, person=person):
        raise PermissionError(str(TOUCH_MESSAGE))


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


def can_change_domains(user, org):
    """The domains of an organization with single sign-on decide whose
    sign-ins count (Google's Workspace domains, the addresses Microsoft's
    tenant speaks for, specs/sso.md), those of a partner organization who
    is suggested for it (decided 2026-11-21), so only admins change them"""
    return can_manage(user) and (
        user.is_admin or not (org.sso or is_partner_organization(org))
    )


def _check_domains(actor, org, domains):
    """Admins only for organizations with single sign-on and partner
    organizations, and never none with single sign-on"""
    if not can_change_domains(actor, org) and not org.sso:
        raise PermissionError(
            _("Only admins change the domains of a partner organization.")
        )
    if not can_change_domains(actor, org):
        raise PermissionError(
            _(
                "Only admins change the domains of an organization signing in"
                " with %(provider)s."
            )
            % {"provider": org.idp_name}
        )
    if org.sso and not domains:
        raise ValidationError(
            _(
                "%(organization)s signs in with %(provider)s: it needs its email"
                " domains."
            )
            % {"organization": org, "provider": org.idp_name}
        )


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
            _check_domains(actor, org, cleaned)
            org.domains = cleaned
            fields.append("domains")
    if fields:
        org.save(update_fields=fields)
    if "domains" in fields and org.requires_sso:
        # Sign-ins through domains it doesn't have anymore end
        from biwak.accounts import sso

        sso.enforce_required_now_and_after_commit(
            org.people.values_list("pk", flat=True)
        )
    return org


# How strict a sign-in setting is (specs/sso.md)
_LEVELS = {SignIn.CODES: 0, SignIn.SSO_ALLOWED: 1, SignIn.SSO_REQUIRED: 2}


def _signin_key(org):
    """What decides how an organization's people sign in: the level, the
    provider and Microsoft's tenant"""
    return (org.signin, org.sso, org.tenant_id if org.sso == IdP.MICROSOFT else "")


def merge_direction(source, target):
    """How merging ``source`` into ``target`` changes the sign-in of
    ``source``'s people (decided 2026-11-21): ``"same"``, ``"stricter"``
    (a stricter level, or the same level with another provider or tenant)
    or ``"looser"``"""
    if _signin_key(source) == _signin_key(target):
        return "same"
    if _LEVELS[SignIn(target.signin)] < _LEVELS[SignIn(source.signin)]:
        return "looser"
    return "stricter"


def merge_warning(source, target):
    """What happens to ``source``'s people when merged into a stricter
    ``target``, for the confirmation"""
    if target.requires_sso:
        return _(
            "The people of %(source)s will sign in only with %(provider)s, as"
            " %(target)s requires: their passkeys are removed, sign-in codes"
            " are refused, their API tokens are cut to 24 hours after their"
            " creation, their sessions not signed in through %(provider)s end"
            " and their calendar links are deleted."
        ) % {"source": source, "target": target, "provider": target.idp_name}
    return _(
        "The people of %(source)s will sign in as %(target)s allows: by code,"
        " passkey or %(provider)s."
    ) % {"source": source, "target": target, "provider": target.idp_name}


@transaction.atomic
def merge(source, target, *, actor, confirmed=False):
    """Moves the people and domains of ``source`` to ``target`` and deletes
    ``source`` (the typo case); returns ``target``. Only between the same
    sign-in settings, or towards a stricter one by admins who confirmed
    ``merge_warning()``; never towards a looser one (decided 2026-11-21)."""
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
    # The domains move with the people: between the same sign-in settings
    # they counted the same way already, stricter merges are admins' anyway
    direction = merge_direction(source, target)
    if direction == "looser":
        raise ValidationError(
            _(
                "%(target)s signs in less strictly than %(source)s: change its"
                " sign-in first."
            )
            % {"source": source, "target": target}
        )
    if direction == "stricter":
        if not actor.is_admin:
            raise PermissionError(
                _(
                    "%(target)s signs in differently than %(source)s: only"
                    " admins merge them."
                )
                % {"source": source, "target": target}
            )
        if not confirmed:
            raise ValidationError(merge_warning(source, target), code="confirm")
    moved = list(source.people.values_list("pk", flat=True))
    source.people.update(organization=target)
    domains = [d for d in source.domains if d not in target.domains]
    if domains:
        target.domains = [*target.domains, *domains]
        target.save(update_fields=["domains"])
    source.delete()
    _access_changed(moved)
    if target.requires_sso:
        from biwak.accounts import sso

        sso.enforce_required_now_and_after_commit(moved)
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
    current = user.organization if user.organization_id else None
    _check_touch(actor, current, org, person=user)
    if current is not None and current.requires_sso and not actor.is_admin:
        # It would loosen how they sign in (decided 2026-11-21)
        raise PermissionError(
            _(
                "%(organization)s requires single sign-on: only admins move"
                " people out of it."
            )
            % {"organization": current}
        )
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


def can_change_signin(user):
    """How an organization's people sign in is for admins (specs/sso.md)"""
    return user.is_authenticated and user.is_active and user.is_admin


def clean_signin(org, *, signin, idp="", tenant_id=""):
    """``(signin, idp, tenant_id)`` checked, ``ValidationError`` otherwise:
    single sign-on needs a provider the installation has set up, Google the
    organization's Workspace domains, Microsoft its tenant ID (not the one of
    personal accounts)"""
    from biwak.accounts import sso

    try:
        signin = SignIn(signin)
        idp = IdP(idp) if idp else ""
    except ValueError as exc:
        raise ValidationError(_("Choose one of the options.")) from exc
    tenant_id = str(tenant_id or "").strip()
    if tenant_id:
        try:
            tenant_id = sso.normalize_tenant(tenant_id)
        except ValueError as exc:
            raise ValidationError(
                _("The tenant ID looks like 00000000-0000-0000-0000-000000000000.")
            ) from exc
        if tenant_id == MICROSOFT_CONSUMER_TENANT:
            raise ValidationError(
                _(
                    "That's the tenant of personal Microsoft accounts, not of an organization."
                )
            )
    if idp != IdP.MICROSOFT:
        tenant_id = ""
    if signin == SignIn.CODES:
        return signin, idp if idp != IdP.MICROSOFT or tenant_id else "", tenant_id
    if not idp:
        raise ValidationError(_("Choose the identity provider."))
    if not sso.provider_configured(idp):
        raise ValidationError(
            _(
                "Signing in with %(provider)s isn't set up on this installation"
                " yet (see the help)."
            )
            % {"provider": IdP(idp).label}
        )
    if not org.domains:
        raise ValidationError(
            _(
                "Add the organization's email domains first: sign-ins count only"
                " for them (Google Workspace's domains, the addresses of the"
                " Microsoft tenant)."
            )
        )
    if idp == IdP.MICROSOFT and not tenant_id:
        raise ValidationError(_("Enter the organization's Microsoft tenant ID."))
    return signin, idp, tenant_id


@transaction.atomic
def set_signin(org, *, signin, idp="", tenant_id="", two_factor=None, actor):
    """How the organization's people sign in (admins only, specs/sso.md).
    Requiring single sign-on removes their passkeys, cuts their API tokens
    and ends their other sessions (``sso.enforce_required()``).
    ``two_factor`` (unchanged if None) requires a second factor
    (specs/two-factor.md): people without a passkey or an app set one up at
    their next request (``two_factor.setup_middleware``)."""
    if not can_change_signin(actor):
        raise PermissionError(_("Only admins change how an organization signs in."))
    signin, idp, tenant_id = clean_signin(
        org, signin=signin, idp=idp, tenant_id=tenant_id
    )
    before = (org.signin, org.idp, org.tenant_id)
    org.signin, org.idp, org.tenant_id = signin, idp, tenant_id
    if two_factor is not None:
        org.requires_two_factor = bool(two_factor)
    org.save(update_fields=["signin", "idp", "tenant_id", "requires_two_factor"])
    if org.requires_sso and before != (signin, idp, tenant_id):
        from biwak.accounts import sso

        sso.enforce_required_now_and_after_commit(
            org.people.values_list("pk", flat=True)
        )
    return org


def for_new_person(email, org=None):
    """The organization of a person invited with ``email``: the one given,
    else the one whose domains include the address's (free-mail domains
    never match)"""
    return org or Organization.objects.for_email(email)
