import re

from django.contrib import messages
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from biwak import cli_version
from biwak.accounts import passkeys
from biwak.accounts.models import API_TOKEN_LIFETIME, APIToken, CalendarToken


@never_cache
def api_tokens(request):
    """Personal API tokens for scripts and the biwak CLI; the secret is shown
    once"""
    secret = None
    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        access = request.POST.get("access")
        if title and access in APIToken.Access.values:
            _token, secret = APIToken.create_for(
                user=request.user, title=title[:100], access=access
            )
    return render(
        request,
        "accounts/api_tokens.html",
        {
            "tokens": request.user.api_tokens.all(),
            "secret": secret,
            "days": API_TOKEN_LIFETIME.days,
            "access_choices": APIToken.Access.choices,
            "api_url": request.build_absolute_uri("/api/v1/"),
            "cli_install": cli_version.UPGRADE,
            "base_url": request.build_absolute_uri("/"),
        },
    )


@never_cache
@require_POST
def api_token_delete(request, pk):
    token = get_object_or_404(request.user.api_tokens, pk=pk)
    token.delete()
    messages.success(
        request, _("The API token %(title)s has been revoked.") % {"title": token}
    )
    return redirect("api_tokens")


@never_cache
def cli_login(request):
    """Authorize the biwak CLI on this computer: biwak waits on a local port
    for the token (cli/biwak/core.py). Logging in first goes through the
    usual login and back here."""
    try:
        port = int(request.GET["port"])
    except KeyError, ValueError:
        port = 0
    state = request.GET.get("state", "")
    if not 1024 <= port <= 65535 or not re.fullmatch(r"[\w-]{16,100}", state):
        return HttpResponseBadRequest("Invalid port or state.")
    # biwak has to ask for the access explicitly
    if (access := request.GET.get("access")) not in APIToken.Access.values:
        return HttpResponseBadRequest(
            "Invalid access, use biwak login --read or --write."
        )
    name = request.GET.get("name", "")[:50]
    if request.method == "POST":
        _token, secret = APIToken.create_for(
            user=request.user,
            title=f"biwak ({name})" if name else "biwak",
            access=access,
        )
        return render(
            request,
            "accounts/cli_login_redirect.html",
            {"action": f"http://127.0.0.1:{port}/", "token": secret, "state": state},
        )
    return render(
        request,
        "accounts/cli_login.html",
        {
            "name": name,
            "days": API_TOKEN_LIFETIME.days,
            "access": APIToken.Access(access),
        },
    )


@never_cache
def calendar_link(request):
    """The secret link to the iCal feed of the person's to-dos (specs/todos.md);
    "Make a new link" replaces it, the old one stops working"""
    if request.method == "POST":
        CalendarToken.renew(request.user)
        messages.success(
            request, _("There's a new link. The old one doesn't work any more.")
        )
        return redirect("calendar_link")
    link = CalendarToken.objects.filter(user=request.user).first()
    return render(
        request,
        "accounts/calendar.html",
        {
            "url": request.build_absolute_uri(
                reverse("calendar_feed", kwargs={"token": link.token})
            )
            if link
            else None
        },
    )


@never_cache
def passkey_offer(request):
    """Add a passkey (allauth's page) or not now: dismissing stops the offer
    for good (specs/access.md)"""
    target = request.GET.get("next", "")
    if not url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        target = "/"
    if request.method == "POST":
        passkeys.dismiss(request.user)
        return redirect(target)
    return render(
        request,
        "accounts/passkey_offer.html",
        {"next": target, "has_passkey": passkeys.has_passkey(request.user)},
    )
