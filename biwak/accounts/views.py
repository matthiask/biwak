import re

from django import forms
from django.contrib import messages
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from biwak import cli_version
from biwak.accounts import operations, passkeys
from biwak.accounts.models import (
    API_TOKEN_LIFETIME,
    Accent,
    APIToken,
    CalendarToken,
    Theme,
)
from biwak.activity.models import LevelOverride
from biwak.activity.operations import set_notification_settings
from biwak.activity.views import SettingsForm
from biwak.forms import Form
from biwak.items.models import Item
from biwak.projects.models import Project


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


# The settings page (specs/keyboard.md): sections, each saved on its own


class KeyboardForm(Form):
    keyboard_shortcuts = forms.BooleanField(
        label=_("Single-key shortcuts"),
        required=False,
        help_text=_(
            "Ctrl+K (Cmd+K) always opens the command palette; the other keys"
            " only work with this on."
        ),
    )


class AppearanceForm(Form):
    # Only what's posted changes: the toggle in the navigation posts the
    # theme alone
    theme = forms.ChoiceField(
        label=_("Theme"),
        choices=Theme.choices,
        required=False,
        widget=forms.RadioSelect,
    )
    accent = forms.ChoiceField(
        label=_("Accent color"),
        choices=Accent.choices,
        required=False,
        widget=forms.RadioSelect,
    )


def _overrides(user):
    """The notification levels which differ per project and item, of the
    places the person still sees"""
    overrides = LevelOverride.objects.filter(user=user).select_related(
        "project", "item"
    )
    visible = set(
        Item.objects
        .visible_to(user)
        .filter(pk__in=[o.item_id for o in overrides if o.item_id])
        .values_list("pk", flat=True)
    )
    # Projects one has left: their overrides stay, but aren't shown
    projects = set(
        Project.objects
        .accessible_to(user)
        .filter(pk__in=[o.project_id for o in overrides if o.project_id])
        .values_list("pk", flat=True)
    )
    return (
        [o for o in overrides if o.project_id in projects],
        [o for o in overrides if o.item_id in visible],
    )


def _settings_page(request, *, notifications=None):
    user = request.user
    project_overrides, item_overrides = _overrides(user)
    return render(
        request,
        "accounts/settings.html",
        {
            "form": notifications
            or SettingsForm(
                initial={
                    "notification_level": user.notification_level,
                    "mail_delivery": user.mail_delivery,
                    "lantern_in_favicon": user.lantern_in_favicon,
                }
            ),
            "keyboard_form": KeyboardForm(
                initial={"keyboard_shortcuts": user.keyboard_shortcuts}
            ),
            "themes": Theme.choices,
            "accents": Accent.choices,
            "project_overrides": project_overrides,
            "item_overrides": item_overrides,
        },
    )


@never_cache
def settings(request):
    return _settings_page(request)


@never_cache
@require_POST
def settings_notifications(request):
    form = SettingsForm(request.POST)
    if not form.is_valid():
        return _settings_page(request, notifications=form)
    set_notification_settings(
        request.user,
        level=form.cleaned_data["notification_level"],
        delivery=form.cleaned_data["mail_delivery"],
        favicon=form.cleaned_data["lantern_in_favicon"],
    )
    messages.success(request, _("Your notification settings have been saved."))
    return redirect("settings")


@never_cache
@require_POST
def settings_keyboard(request):
    form = KeyboardForm(request.POST)
    form.is_valid()
    operations.set_preferences(
        request.user, keyboard_shortcuts=form.cleaned_data["keyboard_shortcuts"]
    )
    messages.success(request, _("Your keyboard settings have been saved."))
    return redirect("settings")


@never_cache
@require_POST
def settings_appearance(request):
    """The theme and the accent color; the toggle in the navigation posts the
    theme alone (and gets 204)"""
    form = AppearanceForm(request.POST)
    if not form.is_valid():
        return HttpResponseBadRequest("Invalid theme or accent color.")
    data = form.cleaned_data
    operations.set_preferences(
        request.user, theme=data["theme"] or None, accent=data["accent"] or None
    )
    if request.headers.get("X-Biwak-Fragment"):
        return HttpResponse(status=204)
    messages.success(request, _("Your appearance settings have been saved."))
    return redirect("settings")
