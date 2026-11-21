from allauth.account.adapter import DefaultAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.mfa.adapter import DefaultMFAAdapter
from allauth.mfa.models import Authenticator
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.providers.base import AuthProcess
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext as _

from biwak.accounts import sso
from biwak.accounts.models import User


class AccountAdapter(DefaultAccountAdapter):
    """Nobody signs up: people are invited (specs/access.md)"""

    def is_open_for_signup(self, request):
        return False

    def get_from_email(self):
        """ "Biwak" <DEFAULT_FROM_EMAIL>, like the other mails without a
        person acting"""
        from biwak.activity.mails import sender

        return sender("Biwak")

    def send_mail(self, template_prefix, email, context):
        """Through the outbox (specs/mail-sending.md): login codes, and the
        mail to an address without an account asking for one, aren't sent
        any more once a code would have expired"""
        from allauth.core import context as allauth_context
        from django.contrib.sites.shortcuts import get_current_site

        from biwak.outbox import sending as outbox
        from biwak.outbox.models import Kind

        request = allauth_context.request
        message = self.render_mail(
            template_prefix,
            email,
            {
                "request": request,
                "email": email,
                "current_site": get_current_site(request),
            }
            | context,
        )
        kind = (
            Kind.LOGIN_CODE
            if template_prefix.rsplit("/", 1)[-1] in {"login_code", "unknown_account"}
            else Kind.ACCOUNT
        )
        outbox.send(message, kind)

    def get_reauthentication_methods(self, user):
        """Confirming who one is: not by a code by mail for people with an
        authenticator app (specs/two-factor.md), the app or a passkey"""
        from biwak.accounts import two_factor

        methods = super().get_reauthentication_methods(user)
        if user.is_authenticated and not two_factor.code_confirms(user):
            methods = [m for m in methods if m["id"] != "reauthenticate_by_code"]
        return methods

    def pre_login(self, request, user, **kwargs):
        """People whose organization requires single sign-on sign in only
        through its identity provider (specs/sso.md): every way allauth signs
        somebody in comes here, after recording the method (codes, passkeys,
        social logins); deactivated people are allauth's (``super()``). The
        same for organizations requiring a second factor
        (specs/two-factor.md): a code isn't enough for people with only a
        passkey."""
        response = super().pre_login(request, user, **kwargs)
        if response is not None:
            return response
        from allauth.account.internal.flows.login import clear_authentication_records
        from allauth.account.internal.stagekit import clear_login

        from biwak.accounts import two_factor

        if (message := sso.refuse_login(request, user)) is not None:
            clear_login(request)
            clear_authentication_records(request)
            messages.error(request, message)
            return redirect(sso.idp_login_url(user))
        # Organizations requiring a second factor (specs/two-factor.md)
        if (message := two_factor.refuse_login(request, user)) is not None:
            clear_login(request)
            clear_authentication_records(request)
            messages.error(request, message)
            return redirect(reverse("account_login"))
        return None


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    """Google and Microsoft sign-in per organization (specs/sso.md): only for
    existing, active people, matched by the address the provider vouches
    for; whether it counts is ``sso.check_social()``'s"""

    def is_open_for_signup(self, request, sociallogin):
        return False

    def authenticate_by_email(self, sociallogin):
        """The person with the provider's address: Google's only verified,
        Microsoft's as given (Entra ID doesn't verify it), which counts only
        with the organization's tenant (``pre_social_login``)"""
        address = sso.claimed_address(
            sociallogin.account.provider, sociallogin.account.extra_data
        )
        if address and (
            user := User.objects.filter(email__iexact=address.strip()).first()
        ):
            return user, user.email
        return None

    def pre_social_login(self, request, sociallogin):
        """Every social login allauth completes comes here after looking the
        person up (by the connected account, else by address): signing in,
        Google's token login, connecting an account to oneself"""
        process = sociallogin.state.get("process")
        # Also allauth's "redirect" process, which signs nobody in but
        # updates the connected account: checked like signing in
        if process == AuthProcess.CONNECT:
            person = request.user if request.user.is_authenticated else None
        else:
            person = sociallogin.user if sociallogin.is_existing else None
        try:
            sso.check_social(
                person, sociallogin.account.provider, sociallogin.account.extra_data
            )
        except sso.Refused as exc:
            messages.error(request, exc.message)
            if process == AuthProcess.CONNECT and person is not None:
                raise ImmediateHttpResponse(
                    redirect(reverse("settings") + "#sign-in")
                ) from exc
            raise ImmediateHttpResponse(redirect(reverse("account_login"))) from exc

    def validate_disconnect(self, account, accounts):
        """Not for people whose organization requires single sign-on: it's
        their only way in (the settings page doesn't offer it either)"""
        if sso.requires_sso(account.user):
            raise ValidationError(
                _("Your organization signs in with %(provider)s: it stays connected.")
                % {"provider": sso.required_organization(account.user).idp_name}
            )


class MFAAdapter(DefaultMFAAdapter):
    """Passkeys are a way in, not a second factor; authenticator apps (TOTP)
    are the optional second factor (specs/two-factor.md, decided 2026-11-21)"""

    def is_mfa_enabled(self, user, types=None):
        """Whether the person has a second factor, the question of the
        two-factor step after signing in by code or through Google or
        Microsoft (``AuthenticateStage``, its page): an authenticator app
        only, never a passkey. Asked about passkeys alone (allauth's
        reauthentication offering them), passkeys count. People whose
        organization requires single sign-on have none: the identity
        provider does that (``sso.enforce_required()`` deletes them)."""
        if user.is_anonymous:
            return False
        wanted = set(types) if types is not None else set(Authenticator.Type)
        if wanted == {Authenticator.Type.WEBAUTHN}:
            return super().is_mfa_enabled(user, types=list(wanted))
        wanted.discard(Authenticator.Type.WEBAUTHN)
        if not wanted or sso.requires_sso(user):
            return False
        return super().is_mfa_enabled(user, types=sorted(wanted))
