"""Authenticator apps (TOTP) as an optional second factor, passkeys as a way
in (specs/two-factor.md). Where each rule is enforced:

- the two-factor step after a sign-in by code or through Google or
  Microsoft asks for the app's code (``adapters.MFAAdapter.is_mfa_enabled``,
  allauth's ``AuthenticateStage``); a passkey sign-in is enough alone;
- confirming who one is (allauth's reauthentication) isn't a code by mail
  for people with an app (``adapters.AccountAdapter
  .get_reauthentication_methods``, ``signin.reauthenticate``): the app or a
  passkey, or a code by mail would be enough to turn the app off or add a
  passkey.

Organizations requiring a second factor (``Organization.requires_two_factor``,
moot where single sign-on is required):

- a passkey sign-in or one through the organization's identity provider is
  enough; after a code (or another provider) the two-factor step asks for
  the app's code; people with a passkey but no app are refused and sign in
  with the passkey (``refuse_login()``, from ``AccountAdapter.pre_login``,
  every way allauth signs somebody in);
- people with neither set one up before anything else: every page leads to
  the setup page, the API answers 403 and websockets don't connect
  (``setup_required()``: ``setup_middleware``, ``sso.session_alive()``).
  Checked on every request, not stored at the sign-in, so switching the
  setting on and a reset apply at once.
"""

from allauth.mfa.models import Authenticator
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.utils.http import urlencode
from django.utils.translation import gettext as _

from biwak.accounts import sso


def has_app(user):
    """Whether the person has an authenticator app"""
    return (
        user.is_authenticated
        and Authenticator.objects.filter(
            user=user, type=Authenticator.Type.TOTP
        ).exists()
    )


def code_confirms(user):
    """Whether a code by mail confirms who the person is (allauth's
    reauthentication): not for people with an app"""
    return not has_app(user)


def has_passkey(user):
    return Authenticator.objects.filter(
        user=user, type=Authenticator.Type.WEBAUTHN
    ).exists()


def required_organization(user):
    """The person's organization if it requires a second factor, else None"""
    org = sso.organization_of(user)
    return org if org is not None and org.two_factor_required else None


def _by_passkey(record):
    return (record.get("method"), record.get("type"), record.get("passwordless")) == (
        "mfa",
        "webauthn",
        True,
    )


def _through_idp(record, org):
    return (
        bool(org.sso)
        and record.get("method") == "socialaccount"
        and record.get("provider") == org.sso
    )


def refuse_login(request, user):
    """The message refusing this sign-in, or None: in organizations
    requiring a second factor, a code (or a provider other than the
    organization's) isn't enough alone. People with an app get the
    two-factor step (``MFAAdapter``), people with neither set one up
    (``setup_required()``); people with only a passkey use it."""
    org = required_organization(user)
    if org is None:
        return None
    records = sso._records(request, user)
    last = records[-1] if records else {}
    if _by_passkey(last) or _through_idp(last, org):
        return None
    if has_app(user) or not has_passkey(user):
        return None
    return _(
        "%(organization)s requires a second factor: sign in with your passkey."
    ) % {"organization": org}


def _session_through_idp(session, user, org):
    """Whether the session signed in through the organization's identity
    provider (``sso.remember_sign_in()``)"""
    record = session.get(sso.SESSION_KEY)
    return (
        isinstance(record, dict)
        and bool(org.sso)
        and record.get("user") == user.pk
        and record.get("org") == org.pk
        and record.get("provider") == org.sso
        and isinstance(record.get("email"), str)
        and record["email"].lower() == user.email.lower()
    )


def setup_required(user, session):
    """Whether the person has to add a passkey or an app before anything
    else: their organization requires a second factor, they have neither,
    and the session didn't sign in through the organization's identity
    provider"""
    org = required_organization(user)
    if org is None or _session_through_idp(session, user, org):
        return False
    return not Authenticator.objects.filter(
        user=user,
        type__in=[Authenticator.Type.TOTP, Authenticator.Type.WEBAUTHN],
    ).exists()


SETUP_PATH = "/accounts/two-factor/"
# What setting one up needs: the page, adding a passkey or an app,
# confirming who one is first, signing out; and the help
SETUP_PATHS = (
    SETUP_PATH,
    "/accounts/2fa/webauthn/add/",
    "/accounts/2fa/totp/activate/",
    "/accounts/reauthenticate/",
    "/accounts/2fa/reauthenticate/",
    "/accounts/2fa/webauthn/reauthenticate/",
    "/accounts/logout/",
    "/static/",
    "/help/",
)


def setup_middleware(get_response):
    """People who have to set up a second factor see nothing else: pages
    lead to the setup page, the API (with this session) answers 403"""

    def middleware(request):
        user = request.user
        if (
            user.is_authenticated
            and not request.path_info.startswith(SETUP_PATHS)
            and setup_required(user, request.session)
        ):
            message = _(
                "Your organization requires a second factor: add a passkey or"
                " an authenticator app first."
            )
            if request.path_info.startswith("/api/"):
                return JsonResponse({"detail": message}, status=403)
            url = SETUP_PATH
            if request.method == "GET":
                url += "?" + urlencode({"next": request.get_full_path()})
            if request.headers.get("HX-Request") == "true":
                return HttpResponse(headers={"HX-Redirect": url})
            return HttpResponseRedirect(url)
        return get_response(request)

    return middleware
