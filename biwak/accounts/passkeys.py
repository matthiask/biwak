"""The offer to add a passkey after logging in by code (specs/access.md,
decided 2026-11-20: once, dismissable): people without a passkey are taken to
the offer page after a login by code, until they dismiss it or add a passkey,
which is stored on the person (``User.passkey_offer_done``)."""

from allauth.account.internal.flows.login import get_authentication_records
from allauth.account.signals import user_logged_in
from allauth.mfa.models import Authenticator
from allauth.mfa.signals import authenticator_added
from django.dispatch import receiver
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils.http import urlencode

from biwak.accounts.models import User


SESSION_KEY = "passkey_offer"
OFFER_PATH = "/accounts/passkey-offer/"


def has_passkey(user):
    return Authenticator.objects.filter(
        user=user, type=Authenticator.Type.WEBAUTHN
    ).exists()


def offer_due(user):
    return not user.passkey_offer_done and not has_passkey(user)


@receiver(user_logged_in)
def remember_offer(sender, request, user, **kwargs):
    """Only logins by code: passkeys don't need the offer, Google is staff's
    own choice"""
    by_code = any(
        r.get("method") == "code" for r in get_authentication_records(request, user)
    )
    if by_code and offer_due(user):
        request.session[SESSION_KEY] = True


@receiver(authenticator_added)
def passkey_added(sender, user, authenticator, **kwargs):
    if authenticator.type == Authenticator.Type.WEBAUTHN:
        dismiss(user)


def dismiss(user):
    if not user.passkey_offer_done:
        user.passkey_offer_done = True
        User.objects.filter(pk=user.pk).update(passkey_offer_done=True)


def passkey_offer_middleware(get_response):
    """The first page somebody looks at after logging in by code becomes the
    offer, which leads on to it (``next``); not the API, htmx requests or
    allauth's own pages"""

    def middleware(request):
        if (
            request.session.get(SESSION_KEY)
            and request.user.is_authenticated
            and request.method == "GET"
            and not request.headers.get("hx-request")
            and not request.path_info.startswith(("/api/", "/accounts/", "/static/"))
        ):
            del request.session[SESSION_KEY]
            if offer_due(request.user):
                return HttpResponseRedirect(
                    f"{reverse('passkey_offer')}?{urlencode({'next': request.get_full_path()})}"
                )
        return get_response(request)

    return middleware
