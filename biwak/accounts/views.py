import re

from django import forms
from django.conf import settings as django_settings
from django.contrib import messages
from django.core.files.storage import default_storage
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.cache import patch_cache_control
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _, gettext_lazy
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from biwak import cli_version
from biwak.accounts import languages, operations, passkeys, signin, sso
from biwak.accounts.models import (
    API_TOKEN_LIFETIME,
    Accent,
    APIToken,
    CalendarToken,
    Theme,
)
from biwak.accounts.quiet import NOTE_LENGTH, short_date
from biwak.activity.models import LevelOverride
from biwak.activity.operations import set_notification_settings
from biwak.activity.views import SettingsForm
from biwak.forms import Form
from biwak.items.models import Item
from biwak.modals import form_response
from biwak.projects.models import Project


IMAGE_MAX_AGE = 365 * 24 * 3600


@require_GET
def person_image(request, pk, version):
    """A person's image, for those who may know the person (the rule of the
    People page), else 404. The version is in the URL, so it's cached for
    good; an old version is gone with the image. Streamed through the app
    also from a bucket: it's small, and a presigned URL (``file_urls``)
    changes every hour, while this one is cached for a year (decided
    2026-11-22, when pages moved to presigned URLs for files)."""
    from biwak.organizations.people import known_people

    person = get_object_or_404(known_people(request.user), pk=pk)
    if not person.image or person.image_version != version:
        raise Http404("No image")
    try:
        with default_storage.open(person.image, "rb") as file:
            data = file.read()
    except FileNotFoundError as exc:
        raise Http404("No image") from exc
    response = HttpResponse(data, content_type="image/webp")
    response["X-Content-Type-Options"] = "nosniff"
    patch_cache_control(response, private=True, max_age=IMAGE_MAX_AGE, immutable=True)
    return response


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
            "sso_organization": sso.required_organization(request.user),
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
            "sso_organization": sso.required_organization(request.user),
            "access": APIToken.Access(access),
        },
    )


@never_cache
def calendar_link(request):
    """The secret link to the iCal feed of the person's to-dos (specs/todos.md);
    "Make a new link" replaces it, the old one stops working. None for
    organizations requiring single sign-on (specs/sso.md)."""
    if org := sso.required_organization(request.user):
        return render(request, "accounts/calendar.html", {"sso_organization": org})
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


class NameForm(Form):
    full_name = forms.CharField(label=gettext_lazy("full name"), max_length=200)
    short_name = forms.CharField(
        label=gettext_lazy("short name"),
        max_length=30,
        required=False,
        help_text=gettext_lazy(
            "How you're listed (mentions, assignees); empty: your first name."
        ),
    )


class KeyboardForm(Form):
    keyboard_shortcuts = forms.BooleanField(
        label=gettext_lazy("Single-key shortcuts"),
        required=False,
        help_text=gettext_lazy(
            "Ctrl+K (Cmd+K) always opens the command palette; the other keys"
            " only work with this on."
        ),
    )


class LanguageForm(Form):
    language = forms.ChoiceField(
        label=gettext_lazy("Language"),
        choices=languages.choices,
        required=False,
        widget=forms.RadioSelect,
    )


class AppearanceForm(Form):
    # Only what's posted changes: the toggle in the navigation posts the
    # theme alone
    theme = forms.ChoiceField(
        label=gettext_lazy("Theme"),
        choices=Theme.choices,
        required=False,
        widget=forms.RadioSelect,
    )
    accent = forms.ChoiceField(
        label=gettext_lazy("Accent color"),
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


def _settings_page(request, *, notifications=None, name_form=None, away_form=None):
    user = request.user
    project_overrides, item_overrides = _overrides(user)
    return render(
        request,
        "accounts/settings.html",
        {
            "form": notifications or SettingsForm.for_user(user),
            "away_form": away_form or AwayForm.for_user(user),
            "time_zone": django_settings.TIME_ZONE,
            "language_form": LanguageForm(initial={"language": user.language}),
            "keyboard_form": KeyboardForm(
                initial={"keyboard_shortcuts": user.keyboard_shortcuts}
            ),
            "name_form": name_form
            or NameForm(
                initial={"full_name": user.full_name, "short_name": user.short_name}
            ),
            "themes": Theme.choices,
            "image_help": _("JPEG, PNG or WebP, at most 5 MB."),
            "accents": Accent.choices,
            "project_overrides": project_overrides,
            "item_overrides": item_overrides,
            **signin.context(request),
        },
    )


@never_cache
def settings(request):
    return _settings_page(request)


@never_cache
@require_POST
def settings_notifications(request):
    form = SettingsForm(request.POST, user=request.user)
    if not form.is_valid():
        return _settings_page(request, notifications=form)
    data = form.cleaned_data
    set_notification_settings(
        request.user,
        level=data["notification_level"],
        delivery=data["mail_delivery"],
        favicon=data["lantern_in_favicon"],
        quiet_hours=data["quiet_hours"],
        working_days=data["working_days"],
        working_from=data["working_from"],
        working_until=data["working_until"],
    )
    messages.success(request, _("Your notification settings have been saved."))
    return redirect("settings")


class AwayForm(Form):
    """Out of office (specs/quiet-hours.md): the person's own in the
    settings, admins' for others on the person's page"""

    away_until = forms.DateField(
        label=gettext_lazy("Away until"),
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        help_text=gettext_lazy(
            "The last day away. Nothing is mailed meanwhile; the day after,"
            " one mail says what happened."
        ),
    )
    away_note = forms.CharField(
        label=gettext_lazy("Note"),
        max_length=NOTE_LENGTH,
        required=False,
        help_text=gettext_lazy(
            "Optional, one line shown with the name: when back, whom to ask meanwhile."
        ),
    )

    def clean_away_until(self):
        day = self.cleaned_data["away_until"]
        if day < timezone.localdate():
            raise forms.ValidationError(_("Choose today or a later day."))
        return day

    def clean_away_note(self):
        return operations.one_line(self.cleaned_data["away_note"])

    @classmethod
    def for_user(cls, user):
        if not user.is_away:
            return cls()
        return cls(initial={"away_until": user.away_until, "away_note": user.away_note})


@never_cache
@require_POST
def settings_away(request):
    """Away until a day, with a note"""
    form = AwayForm(request.POST)
    if not form.is_valid():
        return _settings_page(request, away_form=form)
    operations.set_away(
        request.user,
        until=form.cleaned_data["away_until"],
        note=form.cleaned_data["away_note"],
        actor=request.user,
    )
    messages.success(
        request,
        _("You're away until %(date)s.")
        % {"date": short_date(request.user.away_until)},
    )
    return redirect(reverse("settings") + "#away")


@never_cache
@require_POST
def settings_back(request):
    """ "I'm back": ends being away early"""
    operations.end_away(request.user, actor=request.user)
    messages.success(request, _("Welcome back."))
    return redirect(reverse("settings") + "#away")


@never_cache
@require_POST
def settings_name(request):
    """One's own name (specs/people.md, "Names")"""
    form = NameForm(request.POST)
    if not form.is_valid():
        return _settings_page(request, name_form=form)
    operations.set_name(request.user, **form.cleaned_data)
    messages.success(request, _("Your name has been saved."))
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
def settings_language(request):
    """The language of the pages and mails; the page comes back in it"""
    form = LanguageForm(request.POST)
    if not form.is_valid():
        return HttpResponseBadRequest("Invalid language.")
    operations.set_preferences(request.user, language=form.cleaned_data["language"])
    # The message in the new language, the next page shows it
    with translation.override(
        request.user.language or translation.get_language_from_request(request)
    ):
        messages.success(request, _("Your language has been saved."))
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


@never_cache
@require_POST
def settings_image(request):
    """Uploading one's own profile image"""
    upload = request.FILES.get("image")
    if upload is None:
        messages.error(request, _("Please choose an image."))
        return redirect("settings")
    try:
        operations.set_image(
            request.user,
            upload.read(operations.IMAGE_MAX_BYTES + 1),
            actor=request.user,
        )
    except operations.InvalidImage as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, _("Your profile image has been saved."))
    return redirect("settings")


@never_cache
def person_image_remove(request, pk):
    """Back to the initials: people remove their own image, admins anybody's
    (an unfitting one); the audit log has it. A question, as a modal or a
    page."""
    from biwak.organizations.people import known_people

    person = get_object_or_404(known_people(request.user), pk=pk)
    if not person.image or not operations.can_remove_image(request.user, person):
        raise Http404("No image to remove")
    own = person.pk == request.user.pk
    back = reverse("settings") if own else reverse("person", args=[person.pk])
    if request.method == "POST":
        operations.remove_image(person, actor=request.user)
        messages.success(
            request,
            _("Your profile image has been removed.")
            if own
            else _("The profile image of %(name)s has been removed.")
            % {"name": person},
        )
        return redirect(back)
    return form_response(
        request,
        None,
        title=_("Remove the profile image?")
        if own
        else _("Remove the profile image of %(name)s?") % {"name": person},
        intro=_("The initials are shown instead."),
        cancel_url=back,
        submit_label=_("Remove"),
        destructive=True,
    )
