"""Single sign-on per organization (specs/sso.md): who may sign in how.

Every rule is decided here, the places checking them call these functions:

- ``check_social()``: whether a Google or Microsoft sign-in counts for the
  person (``SocialAccountAdapter.pre_social_login``, every way allauth
  completes a social login: the callback, Google's token login, connecting);
- ``refuse_login()``: codes and passkeys of people whose organization
  requires single sign-on (``AccountAdapter.pre_login``, every way allauth
  signs somebody in, after the method has been recorded);
- ``session_counts()``: sessions of those people end 24 hours after the
  last sign-in through their identity provider (``session_middleware``);
- ``token_counts()``: their API tokens expire 24 hours after creation
  (``APIToken.objects.for_secret``);
- ``enforce_required()``: switching to "required" or moving into such an
  organization removes passkeys, cuts API tokens, ends sessions and
  calendar links.
"""

import datetime as dt
import time
import uuid

from allauth.account.internal.flows.login import get_authentication_records
from allauth.core.internal.datakit import parse_bool_safely
from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext as _


# Sessions and API tokens of people whose organization requires single
# sign-on (decided 2026-11-21): the identity provider is asked again daily
SSO_MAX_AGE = dt.timedelta(hours=24)

# Google owns these mailboxes: a Google sign-in proves them like a code would
GOOGLE_MAIL_DOMAINS = frozenset({"gmail.com", "googlemail.com"})


class Refused(Exception):
    """A sign-in that doesn't count, with the message saying why"""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


def organization_of(user):
    """The person's organization, or None"""
    if user is None or not getattr(user, "organization_id", None):
        return None
    return user.organization


def required_organization(user):
    """The person's organization if it requires single sign-on, else None"""
    org = organization_of(user)
    return org if org is not None and org.requires_sso else None


def requires_sso(user):
    return required_organization(user) is not None


def provider_configured(provider):
    """Whether the installation has an app (client ID and secret) for the
    provider, from ``SOCIALACCOUNT_PROVIDERS``"""
    config = getattr(settings, "SOCIALACCOUNT_PROVIDERS", {}).get(provider, {})
    return any(app.get("client_id") for app in config.get("APPS", []))


def normalize_tenant(tenant_id):
    """The tenant ID as a lowercase UUID, or ValueError"""
    return str(uuid.UUID(str(tenant_id).strip()))


def uses_sso_message(org):
    """ "Example Ltd signs in with Google." """
    return _("%(organization)s signs in with %(provider)s.") % {
        "organization": org,
        "provider": org.idp_name,
    }


# Google and Microsoft


def _google_address(data):
    """The address Google verified, or None: never an unverified one"""
    email = data.get("email")
    verified = parse_bool_safely(data.get("email_verified", data.get("verified_email")))
    return email if isinstance(email, str) and email and verified is True else None


def _microsoft_address(data):
    """The address Microsoft Entra ID gives (Graph's ``mail``, else the user
    principal name). Entra ID doesn't verify it: the organization's
    administrators set it. It counts only together with the organization's
    own tenant (``tid``), whose administrators speak for its people."""
    email = data.get("mail") or data.get("userPrincipalName")
    return email if isinstance(email, str) and email else None


def claimed_address(provider, data):
    """The address the provider vouches for, or None"""
    if provider == "google":
        return _google_address(data)
    if provider == "microsoft":
        return _microsoft_address(data)
    return None


def hd_matches(hd, org):
    """Google's ``hd`` (the Workspace domain managing the account) is exactly
    one of the organization's domains, ignoring case: no suffixes, no
    subdomains, no spaces; missing for personal accounts"""
    if not isinstance(hd, str) or not hd or hd != hd.strip():
        return False
    return hd.lower() in {domain.lower() for domain in org.domains}


def tid_matches(tid, org):
    """Microsoft's ``tid`` is the organization's tenant"""
    if not isinstance(tid, str) or not org.tenant_id:
        return False
    try:
        return normalize_tenant(tid) == normalize_tenant(org.tenant_id)
    except ValueError:
        return False


def is_google_mail(email):
    return email.rpartition("@")[2].lower() in GOOGLE_MAIL_DOMAINS


def check_social(person, provider, data):
    """Raises ``Refused`` unless signing in as ``person`` with the provider's
    data (the ID token's or user info's claims) counts:

    - the person exists and is active;
    - the provider vouches for the person's own address (Google: verified);
    - Google: the organization uses Google (allowed or required) and ``hd``
      is one of its domains, or the address is a Gmail address and the
      organization doesn't require another provider;
    - Microsoft: the organization uses Microsoft and ``tid`` is its tenant.
    """
    generic = _(
        "There's no active account for this %(provider)s address. Sign in with"
        " a code sent to your address."
    ) % {"provider": _provider_name(provider)}
    if person is None or not person.is_active:
        raise Refused(generic)
    address = claimed_address(provider, data)
    if address is None or address.strip().lower() != person.email.lower():
        raise Refused(generic)
    org = organization_of(person)
    sso = org.sso if org is not None else ""
    if org is not None and org.requires_sso and sso != provider:
        raise Refused(uses_sso_message(org))
    if provider == "google":
        if sso == "google" and hd_matches(data.get("hd"), org):
            return
        if is_google_mail(person.email) and not data.get("hd"):
            return
        if sso == "google":
            raise Refused(
                _(
                    "This Google account isn't managed by the Google Workspace"
                    " of %(organization)s (%(domains)s). Sign in with your"
                    " account there."
                )
                % {"organization": org, "domains": ", ".join(org.domains)}
            )
    elif provider == "microsoft":
        if sso == "microsoft" and tid_matches(data.get("tid"), org):
            return
        if sso == "microsoft":
            raise Refused(
                _(
                    "This Microsoft account doesn't belong to the organization"
                    " %(organization)s. Sign in with your account there."
                )
                % {"organization": org}
            )
    raise Refused(
        _(
            "You can't sign in with %(provider)s. Sign in with a code sent to"
            " your address or with a passkey."
        )
        % {"provider": _provider_name(provider)}
    )


def _provider_name(provider):
    return {"google": "Google", "microsoft": "Microsoft"}.get(provider, provider)


# Codes, passkeys and sessions


def _records(request, user):
    return [r for r in get_authentication_records(request, user) if isinstance(r, dict)]


def _signed_in_with(record, provider, *, now):
    try:
        at = float(record.get("at"))
    except TypeError, ValueError:
        return False
    return (
        record.get("method") == "socialaccount"
        and record.get("provider") == provider
        and 0 <= now - at < SSO_MAX_AGE.total_seconds()
    )


def refuse_login(request, user):
    """The message refusing this sign-in, or None: people whose organization
    requires single sign-on sign in only through its identity provider, the
    method allauth recorded last (codes and passkeys are refused)"""
    org = required_organization(user)
    if org is None:
        return None
    records = _records(request, user)
    if records and _signed_in_with(records[-1], org.idp, now=time.time()):
        return None
    return uses_sso_message(org)


def session_counts(request, user):
    """Sessions of people whose organization requires single sign-on last 24
    hours after signing in through its identity provider (the time allauth
    recorded in the session, which the browser can't change; "Remember me"
    and the cookie's age don't matter); others as long as Django keeps them"""
    org = required_organization(user)
    if org is None:
        return True
    now = time.time()
    return any(_signed_in_with(r, org.idp, now=now) for r in _records(request, user))


def signed_in_with_idp(request, user, org):
    """Whether this session signed in through the organization's identity
    provider in the last 24 hours"""
    now = time.time()
    return bool(org.sso) and any(
        _signed_in_with(r, org.sso, now=now) for r in _records(request, user)
    )


def token_counts(token):
    """API tokens of people whose organization requires single sign-on expire
    24 hours after creation, whatever ``expires_at`` says"""
    if not requires_sso(token.user):
        return True
    return token.created_at > timezone.now() - SSO_MAX_AGE


def token_expiry(user, *, created_at):
    """When a token of the person made at ``created_at`` expires at the
    latest, or None without a limit"""
    return created_at + SSO_MAX_AGE if requires_sso(user) else None
