"""The settings page's sign-in section (specs/ui-round-2.md part E): the
passkeys and sessions inline. allauth does the work: its webauthn views add
and remove passkeys, its usersessions flows end sessions."""

import re

from allauth.account.views import LoginView, RequestLoginCodeView
from allauth.mfa.base.views import AuthenticateView
from allauth.mfa.models import Authenticator
from allauth.mfa.webauthn.views import add_webauthn
from allauth.socialaccount.models import SocialAccount
from allauth.usersessions.internal import flows
from allauth.usersessions.models import UserSession
from allauth.usersessions.views import list_usersessions
from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from biwak.accounts import sso


BROWSERS = [
    ("Edg", "Edge"),
    ("OPR", "Opera"),
    ("Firefox", "Firefox"),
    ("Chrome", "Chrome"),
    ("Chromium", "Chromium"),
    ("Safari", "Safari"),
]
SYSTEMS = [
    ("iPhone", "iPhone"),
    ("iPad", "iPad"),
    ("Android", "Android"),
    ("Windows", "Windows"),
    ("Mac OS X", "macOS"),
    ("CrOS", "ChromeOS"),
    ("Linux", "Linux"),
]


def describe_agent(user_agent):
    """ "Firefox on Linux" from a User-Agent header; the header itself is the
    fallback, it's all there is"""
    browser = next((name for token, name in BROWSERS if token in user_agent), "")
    system = next((name for token, name in SYSTEMS if token in user_agent), "")
    if browser and system:
        return _("%(browser)s on %(system)s") % {"browser": browser, "system": system}
    return browser or system or re.sub(r"\s+", " ", user_agent).strip()


def passkeys(user):
    return Authenticator.objects.filter(
        user=user, type=Authenticator.Type.WEBAUTHN
    ).order_by("created_at")


def sessions(request):
    """The person's live sessions, the current one first"""
    ret = []
    for session in UserSession.objects.purge_and_list(request.user):
        session.current = session.is_current()
        session.browser = describe_agent(session.user_agent)
        ret.append(session)
    return sorted(ret, key=lambda s: (not s.current, -s.last_seen_at.timestamp()))


def connected_accounts(user):
    """Google and Microsoft accounts connected to the person's"""
    ret = []
    for account in SocialAccount.objects.filter(user=user).order_by("pk"):
        data = account.extra_data or {}
        account.address = sso.claimed_address(account.provider, data) or data.get(
            "email", ""
        )
        account.provider_name = {"google": "Google", "microsoft": "Microsoft"}.get(
            account.provider, account.provider
        )
        ret.append(account)
    return ret


def context(request):
    org = sso.required_organization(request.user)
    return {
        "sso_organization": org,
        "connected_accounts": connected_accounts(request.user),
        "passkeys": passkeys(request.user) if org is None else [],
        "sessions": sessions(request),
    }


def back_to_the_section():
    return redirect(reverse("settings") + "#sign-in")


def passkeys_page(request):
    """The pages allauth lists passkeys on (and returns to after adding or
    removing one) are the settings page's section now"""
    return back_to_the_section()


def sessions_page(request):
    """Likewise for sessions; "Sign out everywhere else" posts to allauth's
    view, which ends them and comes back here"""
    if request.method == "GET":
        return back_to_the_section()
    return list_usersessions(request)


@require_POST
def end_session(request, pk):
    """One other session; this one ends with "Sign out" in the Me menu"""
    session = get_object_or_404(UserSession, pk=pk, user=request.user)
    if session.is_current():
        raise Http404("Not the current session")
    flows.sessions.end_sessions(request, [session])
    messages.info(request, _("That session has been signed out."))
    return back_to_the_section()


class SSOViewMixin:
    """allauth's sign-in pages send people whose organization requires
    single sign-on to their identity provider (``biwak.accounts.forms``)"""

    def form_invalid(self, form):
        if url := getattr(form, "sso_url", None):
            for error in form.non_field_errors() or [
                e for errors in form.errors.values() for e in errors
            ]:
                messages.info(self.request, error)
                break
            return redirect(url)
        return super().form_invalid(form)


class SSOLoginView(SSOViewMixin, LoginView):
    pass


class SSORequestLoginCodeView(SSOViewMixin, RequestLoginCodeView):
    pass


login = SSOLoginView.as_view()
request_login_code = SSORequestLoginCodeView.as_view()


class TwoFactorView(AuthenticateView):
    """allauth's two-factor step (specs/two-factor.md): only the code of the
    authenticator app, no passkey there; a passkey signs in alone, from the
    sign-in page. Posts without a code are a missing code, not a passkey."""

    template_name = "mfa/authenticate.html"

    def _build_forms(self):
        user = self.stage.login.user
        form_class = self.get_form_class()
        self.webauthn_form = None
        if self.request.method == "POST":
            self.auth_form = form_class(user=user, data=self.request.POST)
            return self.auth_form
        self.auth_form = form_class(user=user)
        return None


two_factor = TwoFactorView.as_view()


def add_passkey(request):
    """allauth's page adding a passkey, not for people whose organization
    requires single sign-on (specs/sso.md)"""
    if org := sso.required_organization(request.user):
        messages.error(
            request,
            _("%(message)s Passkeys aren't used there.")
            % {"message": sso.uses_sso_message(org)},
        )
        return back_to_the_section()
    return add_webauthn(request)


def connections_page(request):
    """The connected accounts are on the settings page (``disconnect``)"""
    return back_to_the_section()


@require_POST
def disconnect(request, pk):
    """Ends the connection to a Google or Microsoft account; signing in with
    it again connects it again. allauth's own view refuses the last one of
    people without passwords, but here codes work. Not for people whose
    organization requires single sign-on: it's their way in."""
    account = get_object_or_404(SocialAccount, pk=pk, user=request.user)
    if org := sso.required_organization(request.user):
        messages.error(
            request,
            _("%(message)s The account stays connected.")
            % {"message": sso.uses_sso_message(org)},
        )
        return back_to_the_section()
    account.delete()
    messages.info(
        request,
        _("The %(provider)s account has been disconnected.")
        % {"provider": account.get_provider_account().get_brand()["name"]},
    )
    return back_to_the_section()


def reauthenticate(allauth_view):
    """allauth's page confirming who somebody is (by code, passkey);
    people whose organization requires single sign-on sign in through it
    again instead (specs/sso.md)"""

    def view(request, *args, **kwargs):
        if request.user.is_authenticated and (
            org := sso.required_organization(request.user)
        ):
            messages.info(request, sso.uses_sso_message(org))
            next_url = request.GET.get("next", "")
            if not url_has_allowed_host_and_scheme(
                next_url,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure(),
            ):
                next_url = ""
            return redirect(
                sso.idp_login_url(
                    request.user, next_url=next_url or reverse("settings")
                )
            )
        return allauth_view(request, *args, **kwargs)

    return view
