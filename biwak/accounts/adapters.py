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
        if template_prefix.endswith("/login_code") and (
            User.objects.filter(
                email__iexact=email, mail_undeliverable_at__isnull=False
            ).exists()
        ):
            messages.warning(
                request,
                _(
                    "Mail to this address bounced before, the code may not"
                    " arrive. Sign in with a passkey, or ask an admin to check"
                    " your address."
                ),
            )


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
