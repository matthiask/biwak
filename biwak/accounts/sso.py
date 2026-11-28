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


def idp_login_url(user, *, next_url=""):
    """Where people whose organization requires single sign-on go to sign
    in: the provider's page (allauth asks to continue there), with their
    address as a hint"""
    from django.urls import reverse
    from django.utils.http import urlencode

    org = required_organization(user)
    if org is None:
        return reverse("account_login")
    params = {"process": "login", "auth_params": urlencode({"login_hint": user.email})}
    if next_url:
        params["next"] = next_url
    return f"{reverse(f'{org.idp}_login')}?{urlencode(params)}"


# Google and Microsoft


def _google_address(data):
    """The address Google verified, or None: never an unverified one"""
    email = data.get("email")
    verified = parse_bool_safely(data.get("email_verified", data.get("verified_email")))
    return email if isinstance(email, str) and email and verified is True else None


def _microsoft_address(data):
    """The address Microsoft Entra ID gives (Graph's ``mail``, else the user
    principal name). Entra ID doesn't verify it: the tenant's administrators
    set it. It counts only together with the organization's own tenant
    (``tid``) and for the organization's domains (``check_social()``)."""
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


def address_in_domains(email, org):
    """The address's domain is exactly one of the organization's"""
    return email.rpartition("@")[2].lower() in {d.lower() for d in org.domains}


def is_google_mail(email):
    return email.rpartition("@")[2].lower() in GOOGLE_MAIL_DOMAINS


def check_social(person, provider, data):
    """Raises ``Refused`` unless signing in as ``person`` with the provider's
    data (the ID token's or user info's claims) counts:

    - the person exists and is active;
    - the provider vouches for the person's own address (Google: verified);
    - Google: the organization uses Google (allowed or required) and ``hd``
      is one of its domains, or the address is a Gmail address and the
      organization doesn't require single sign-on;
    - Microsoft: the organization uses Microsoft, ``tid`` is its tenant and
      the address is of one of its domains: Entra ID doesn't verify
      addresses, its administrators set them, so a tenant speaks only for
      its organization's domains (or anybody moved into the organization
      could be impersonated by its tenant's administrators).
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
    provider_counts(person, organization_of(person), provider, data)


def provider_counts(person, org, provider, data):
    """The provider's part of ``check_social()``: raises ``Refused`` unless
    the claims (``hd``, ``tid``) count for the person in ``org`` (their
    organization, as it is now). Also checked again for sessions."""
    sso = org.sso if org is not None else ""
    if org is not None and org.requires_sso and sso != provider:
        raise Refused(uses_sso_message(org))
    if provider == "google":
        if sso == "google" and hd_matches(data.get("hd"), org):
            return
        if (
            is_google_mail(person.email)
            and not data.get("hd")
            and not (org is not None and org.requires_sso)
        ):
            # Only where single sign-on is allowed or off: an organization
            # requiring Google means its Workspace (decided 2026-11-21)
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
        if (
            sso == "microsoft"
            and tid_matches(data.get("tid"), org)
            and address_in_domains(person.email, org)
        ):
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


def is_organization_idp(person, org, provider, data):
    """Whether the claims (``hd``, ``tid``) are of the organization's own
    identity provider, as the organization is now: its Google Workspace
    (``hd`` one of its domains) or its Entra tenant (``tid``, and the address
    of its domains). Not a personal Gmail account, which ``provider_counts()``
    lets sign in where single sign-on is allowed but isn't the organization's
    (specs/two-factor.md)."""
    if org is None or not org.sso or provider != org.sso:
        return False
    if provider == "google":
        return hd_matches(data.get("hd"), org)
    if provider == "microsoft":
        return tid_matches(data.get("tid"), org) and address_in_domains(
            person.email, org
        )
    return False


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


# What the session keeps of a sign-in through a provider (``remember_sign_in``)
SESSION_KEY = "biwak_sso"


def _sign_in_counts(record, user, org):
    """When the session's sign-in through the provider was (a timestamp), if
    it counts for the person in ``org`` as it is now, else None: the person,
    their address and organization the same, the provider the organization's,
    less than 24 hours ago, and its claims (``hd``, ``tid``) still matching
    the organization's domains and tenant. Changing those, or moving the
    person, ends the session."""
    if not isinstance(record, dict) or org is None:
        return None
    try:
        at = float(record.get("at"))
    except TypeError, ValueError:
        return None
    if not (
        record.get("user") == user.pk
        and record.get("org") == org.pk
        and isinstance(record.get("email"), str)
        and record["email"].lower() == user.email.lower()
        and record.get("provider") == org.sso
        and 0 <= time.time() - at < SSO_MAX_AGE.total_seconds()
    ):
        return None
    try:
        provider_counts(
            user,
            org,
            record["provider"],
            {"hd": record.get("hd"), "tid": record.get("tid")},
        )
    except Refused:
        return None
    return at


def session_counts(request, user):
    """Sessions of people whose organization requires single sign-on last 24
    hours after signing in through its identity provider (the time stored in
    the session on the server, which the browser can't change; "Remember me"
    and the cookie's age don't matter), while that sign-in still counts for
    the organization (``_sign_in_counts()``); others as long as Django keeps
    them"""
    org = required_organization(user)
    if org is None:
        return True
    at = _sign_in_counts(request.session.get(SESSION_KEY), user, org)
    if at is None:
        return False
    # Sessions from before the switch expire then too (``remember_sign_in``)
    expires = dt.datetime.fromtimestamp(at, tz=dt.UTC) + SSO_MAX_AGE
    if request.session.get_expiry_date() > expires + dt.timedelta(minutes=1):
        request.session.set_expiry(expires)
    return True


def signed_in_with_idp(request, user, org):
    """Whether this session signed in through the organization's identity
    provider in the last 24 hours, counting with ``org``'s settings"""
    return bool(org.sso) and (
        _sign_in_counts(request.session.get(SESSION_KEY), user, org) is not None
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


def _load_session(session_key):
    """The stored session (Django's store) and its data, ``{}`` when it
    doesn't exist or expired"""
    from importlib import import_module

    store = import_module(settings.SESSION_ENGINE).SessionStore(session_key)
    try:
        data = store.load()
    except Exception:  # noqa: BLE001 (a broken session doesn't count)
        data = {}
    return store, data


def _stored_session_counts(session_key, user, org):
    """``session_counts()`` for a stored session"""
    store, data = _load_session(session_key)
    if str(data.get("_auth_user_id")) != str(user.pk):
        return False
    at = _sign_in_counts(data.get(SESSION_KEY), user, org)
    if at is None:
        return False
    # Expiring 24 hours after signing in (``remember_sign_in``)
    store.set_expiry(dt.datetime.fromtimestamp(at, tz=dt.UTC) + SSO_MAX_AGE)
    store.save()
    return True


def session_alive(session_key, user):
    """For websockets, which read the session once when connecting: whether
    the login session still exists, hasn't expired (Django's ``exists()``
    doesn't look at the date) and is the person's, and for people whose
    organization requires single sign-on still counts (``session_counts()``)"""
    from biwak.accounts.models import User

    _store, data = _load_session(session_key)
    if not data or str(data.get("_auth_user_id")) != str(user.pk):
        return False
    user = User.objects.select_related("organization").filter(pk=user.pk).first()
    if user is None or not user.is_active:
        return False
    from biwak.accounts import two_factor

    if two_factor.setup_required(user, data):
        # A second factor to set up first (specs/two-factor.md)
        return False
    org = required_organization(user)
    return org is None or _sign_in_counts(data.get(SESSION_KEY), user, org) is not None


def enforce_required(users):
    """For people whose organization requires single sign-on (after
    switching to it or moving into it, decided 2026-11-21): their passkeys
    (and other authenticators) are removed, not only blocked, so switching
    back can't revive them; API tokens are cut to 24 hours after their
    creation; calendar links end; sessions that didn't sign in through the
    provider in the last 24 hours end (the current request's on the next
    one, ``session_middleware``)"""
    from allauth.core import context
    from allauth.mfa.models import Authenticator
    from allauth.usersessions.models import UserSession
    from django.db.models import F

    from biwak.accounts.models import APIToken, CalendarToken

    current = getattr(context.request, "session", None)
    current_key = getattr(current, "session_key", None)
    users = list(users)
    for user in users:
        org = required_organization(user)
        if org is None:
            continue
        Authenticator.objects.filter(user=user).delete()
        APIToken.objects.filter(
            user=user, expires_at__gt=F("created_at") + SSO_MAX_AGE
        ).update(expires_at=F("created_at") + SSO_MAX_AGE)
        CalendarToken.objects.filter(user=user).delete()
        for session in UserSession.objects.filter(user=user):
            if session.session_key == current_key:
                continue
            if not _stored_session_counts(session.session_key, user, org):
                session.end()
        # Open websockets check their session again (``session_alive()``)
        from biwak.collab import live

        live.check_access(user=user.pk)


def enforce_required_now_and_after_commit(user_ids):
    """``enforce_required()`` now, and again once the transaction committed:
    passkeys, calendar links, tokens and sessions made meanwhile by other
    requests (which didn't see the change yet) go too"""
    from django.db import transaction

    from biwak.accounts.models import User

    user_ids = list(user_ids)

    def run():
        enforce_required(
            User.objects.filter(pk__in=user_ids).select_related("organization")
        )

    run()
    transaction.on_commit(run)


# The session


def remember_sign_in(request, user, sociallogin=None):
    """A sign-in through a provider is kept in the session with what counted
    (provider, ``hd``, ``tid``, organization, address, time), checked again
    on every request (``session_counts()``). Sessions of people whose
    organization requires single sign-on expire 24 hours after signing in,
    as a date: saving the session on every request doesn't extend it, and
    websockets stop with it too (``session_alive()``)."""
    if sociallogin is not None:
        data = sociallogin.account.extra_data or {}
        org = organization_of(user)
        request.session[SESSION_KEY] = {
            "user": user.pk,
            "org": org.pk if org is not None else None,
            "email": user.email,
            "provider": sociallogin.account.provider,
            "hd": data.get("hd") if isinstance(data.get("hd"), str) else None,
            "tid": data.get("tid") if isinstance(data.get("tid"), str) else None,
            "at": time.time(),
        }
    else:
        request.session.pop(SESSION_KEY, None)
    if requires_sso(user):
        request.session.set_expiry(timezone.now() + SSO_MAX_AGE)


def session_middleware(get_response):
    """Signs out people whose organization requires single sign-on when
    their session didn't sign in through its provider in the last 24 hours
    (``session_counts()``); ``LoginRequired`` sends them to the login page,
    the API answers 401"""
    from django.contrib import messages
    from django.contrib.auth import logout

    def middleware(request):
        user = request.user
        if user.is_authenticated and not session_counts(request, user):
            org = required_organization(user)
            # The session ends, nobody signs out: the push device stays
            # (``views.signed_out()``, specs/web-push.md)
            request.session_ended = True
            logout(request)
            messages.info(
                request,
                _("%(message)s Sign in again, please.")
                % {"message": uses_sso_message(org)},
            )
        return get_response(request)

    return middleware
