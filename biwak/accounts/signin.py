"""The settings page's sign-in section (specs/access.md, "Sign-in"): the
passkeys, the authenticator app and sessions inline. allauth does the work:
its webauthn views add and remove passkeys, its TOTP flows turn the app on
and off (specs/two-factor.md), its usersessions flows end sessions."""

import base64
import re

from allauth.account.decorators import reauthentication_required
from allauth.account.views import LoginView, RequestLoginCodeView
from allauth.mfa.adapter import get_adapter as get_mfa_adapter
from allauth.mfa.base.forms import ReauthenticateForm
from allauth.mfa.base.views import AuthenticateView
from allauth.mfa.models import Authenticator
from allauth.mfa.totp.forms import ActivateTOTPForm
from allauth.mfa.totp.internal import flows as totp_flows
from allauth.mfa.webauthn.forms import AddWebAuthnForm
from allauth.mfa.webauthn.internal import auth as webauthn_auth
from allauth.mfa.webauthn.views import AddWebAuthnView
from allauth.socialaccount.models import SocialAccount
from allauth.usersessions.internal import flows
from allauth.usersessions.models import UserSession
from allauth.usersessions.views import list_usersessions
from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _, gettext_lazy
from django.views.decorators.http import require_POST
from django.views.generic.edit import FormView

from biwak.accounts import sso
from biwak.forms import BootstrapMixin
from biwak.modals import form_response


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


def authenticator_app(user):
    """The person's authenticator app (one at most), or None"""
    return Authenticator.objects.filter(user=user, type=Authenticator.Type.TOTP).first()


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
        "authenticator_app": authenticator_app(request.user) if org is None else None,
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


class AddPasskeyForm(AddWebAuthnForm):
    """allauth's form without "Passwordless": every key added is a passkey
    (decided 2026-11-21 after a review), so ``clean()`` refuses a key that
    didn't verify the person (PIN, fingerprint)"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields.pop("passwordless", None)

    def clean(self):
        self.cleaned_data["passwordless"] = True
        return super().clean()


class AddPasskeyView(AddWebAuthnView):
    """allauth's view registering passkeys only: a discoverable credential
    with user verification required (``begin_registration(user, True)``,
    which the server checks again when the key answers); allauth's script
    reads the hidden, ticked box of ``mfa/webauthn/add_form.html``"""

    form_class = AddPasskeyForm

    def get_context_data(self, **kwargs):
        ret = FormView.get_context_data(self, **kwargs)
        ret["js_data"] = {
            "creation_options": webauthn_auth.begin_registration(
                self.request.user, passwordless=True
            )
        }
        return ret


add_webauthn = AddPasskeyView.as_view()


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


def reauthenticate(allauth_view, *, by_code=False):
    """allauth's page confirming who somebody is (by code, passkey);
    people whose organization requires single sign-on sign in through it
    again instead (specs/sso.md). People with an authenticator app confirm
    with it or a passkey, not by code (``by_code``, specs/two-factor.md)."""

    def view(request, *args, **kwargs):
        from biwak.accounts import two_factor

        if (
            by_code
            and request.user.is_authenticated
            and not two_factor.code_confirms(request.user)
        ):
            query = request.GET.urlencode()
            return redirect(
                reverse("mfa_reauthenticate") + (f"?{query}" if query else "")
            )
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


# The authenticator app (specs/two-factor.md): optional, one per person, not
# for people whose organization requires single sign-on


class ActivateAppForm(BootstrapMixin, ActivateTOTPForm):
    """allauth's: the code the app shows for the secret in the session"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["code"].label = gettext_lazy("Code from the app")


class DeactivateAppForm(BootstrapMixin, ReauthenticateForm):
    """allauth's reauthentication with the app: turning it off needs its
    code once more, not only a code by mail"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["code"].label = gettext_lazy("Code from the app")


def activate_app(request):
    """Set up an authenticator app: a QR code and the code it shows to
    confirm; allauth asks to confirm who somebody is first unless they did
    in the last five minutes: signing in doesn't count, so it asks right
    after a sign-in too"""
    if org := sso.required_organization(request.user):
        messages.error(
            request,
            _("%(message)s Authenticator apps aren't used there.")
            % {"message": sso.uses_sso_message(org)},
        )
        return back_to_the_section()
    if authenticator_app(request.user):
        return back_to_the_section()
    return _activate_app(request)


@reauthentication_required(app="allauth.mfa")
def _activate_app(request):
    form = ActivateAppForm(
        user=request.user, data=request.POST if request.method == "POST" else None
    )
    if form.is_valid():
        totp_flows.activate_totp(request, form)
        return back_to_the_section()
    adapter = get_mfa_adapter()
    totp_url = adapter.build_totp_url(request.user, form.secret)
    svg = adapter.build_totp_svg(totp_url)
    return form_response(
        request,
        form,
        title=_("Set up an authenticator app"),
        intro=_(
            "Scan the QR code with an authenticator app on your phone, then"
            " enter the code it shows. From then on, signing in by code or"
            " through Google or Microsoft asks for the app's code too; a"
            " passkey stays enough alone."
        ),
        cancel_url=reverse("settings") + "#sign-in",
        submit_label=_("Turn on"),
        template="accounts/totp_activate.html",
        help_page="sign-in",
        extra={
            "qr_code": "data:image/svg+xml;base64,"
            + base64.b64encode(svg.encode()).decode(),
            "secret": form.secret,
        },
    )


def deactivate_app(request):
    """Turn the authenticator app off, with a code from it"""
    authenticator = authenticator_app(request.user)
    if authenticator is None:
        return back_to_the_section()
    form = DeactivateAppForm(
        user=request.user, data=request.POST if request.method == "POST" else None
    )
    if form.is_valid():
        form.save()
        totp_flows.deactivate_totp(request, authenticator)
        return back_to_the_section()
    return form_response(
        request,
        form,
        title=_("Turn off the authenticator app?"),
        intro=_(
            "Signing in by code or through Google or Microsoft won't ask for"
            " its code anymore. Confirm with a code from the app."
        ),
        cancel_url=reverse("settings") + "#sign-in",
        submit_label=_("Turn off"),
        destructive=True,
    )


def two_factor_setup(request):
    """Organizations requiring a second factor (specs/two-factor.md): people
    with neither a passkey nor an app add one here before anything else
    (``two_factor.setup_middleware``)"""
    from biwak.accounts import two_factor
    from biwak.forms import next_url

    if not two_factor.setup_required(request.user, request.session):
        return redirect(next_url(request) or "/")
    return render(
        request,
        "accounts/two_factor_setup.html",
        {"organization": two_factor.required_organization(request.user)},
    )
