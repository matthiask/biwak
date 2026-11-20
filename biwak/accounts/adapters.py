from allauth.account.adapter import DefaultAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext as _

from biwak.accounts.models import User


class AccountAdapter(DefaultAccountAdapter):
    """Nobody signs up: people are invited (specs/access.md)"""

    def is_open_for_signup(self, request):
        return False


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    """Google sign-in only for existing, active staff, matched by email
    (specs/access.md): clients use codes or passkeys, even when their
    address matches"""

    def is_open_for_signup(self, request, sociallogin):
        return False

    def pre_social_login(self, request, sociallogin):
        if sociallogin.is_existing:
            person = sociallogin.user
        else:
            addresses = [a.email for a in sociallogin.email_addresses]
            person = next(
                (
                    user
                    for address in addresses
                    if (user := User.objects.filter(email__iexact=address).first())
                ),
                None,
            )
        if person is not None and person.is_client:
            messages.error(
                request,
                _(
                    "Clients can't sign in with Google. Sign in with a code sent"
                    " to your address or with a passkey."
                ),
            )
            raise ImmediateHttpResponse(redirect(reverse("account_login")))
