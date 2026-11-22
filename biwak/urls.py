from allauth.account import views as account_views
from allauth.mfa.base import views as mfa_views
from allauth.mfa.webauthn import views as webauthn_views
from django.conf import settings
from django.contrib import admin
from django.contrib.auth.decorators import login_not_required
from django.http import Http404, JsonResponse
from django.shortcuts import redirect
from django.templatetags.static import static
from django.urls import include, path, re_path

from biwak import help as help_pages, paste
from biwak.accounts import signin
from biwak.api import api
from biwak.schedules_forms import describe


@login_not_required
def favicon(request):
    """Browsers ask for /favicon.ico without looking at the page"""
    return redirect(static("biwak/favicon.svg"), permanent=True)


@login_not_required
def manifest(request):
    """Makes Biwak installable as an app (specs/pwa.md); public, holds
    nothing secret"""
    icon = lambda name, size, purpose: {  # noqa: E731
        "src": static(f"biwak/{name}"),
        "sizes": f"{size}x{size}",
        "type": "image/png",
        "purpose": purpose,
    }
    response = JsonResponse(
        {
            "name": "Biwak",
            "short_name": "Biwak",
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "background_color": "#eeebe4",
            "theme_color": "#5b37b0",
            "icons": [
                icon("icon-192.png", 192, "any"),
                icon("icon-512.png", 512, "any"),
                icon("icon-maskable-512.png", 512, "maskable"),
            ],
        },
        json_dumps_params={"indent": 2},
    )
    response["Content-Type"] = "application/manifest+json"
    return response


@login_not_required
def no_passwords(request, *args, **kwargs):
    """Login is by code and passkeys (specs/access.md): allauth's password
    pages (set, change, reset) don't exist, nor its pages changing one's
    address"""
    raise Http404


urlpatterns = [
    path("favicon.ico", favicon),
    path("manifest.webmanifest", manifest),
    path("", include("biwak.projects.urls")),
    path("", include("biwak.organizations.urls")),
    path("", include("biwak.teams.urls")),
    path("", include("biwak.items.urls")),
    path("", include("biwak.files.urls")),
    path("", include("biwak.activity.urls")),
    path("", include("biwak.bookmarks.urls")),
    path("", include("biwak.reactions.urls")),
    path("", include("biwak.checkins.urls")),
    path("", include("biwak.search.urls")),
    path("", include("biwak.palette.urls")),
    path("", include("biwak.inbound.urls")),
    path("help/", help_pages.help_page, name="help"),
    path("help/<slug:page>/", help_pages.help_page, name="help"),
    path("paste/markdown/", paste.html_to_markdown, name="paste_markdown"),
    path("schedules/describe/", describe, name="schedules_describe"),
    path("api/v1/", api.urls),
    path("accounts/", include("biwak.accounts.urls")),
    re_path(r"^accounts/password/", no_passwords),
    # Only admins change addresses (specs/mail-sending.md, specs/sso.md):
    # an address added here could sign in elsewhere (a Gmail address with
    # Google) after leaving a company requiring single sign-on
    re_path(r"^accounts/email/", no_passwords),
    re_path(r"^accounts/confirm-email/", no_passwords),
    # Reauthenticating goes through the identity provider for people whose
    # organization requires it, not by code or passkey (specs/sso.md)
    path(
        "accounts/reauthenticate/", signin.reauthenticate(account_views.reauthenticate)
    ),
    path(
        "accounts/reauthenticate/code/",
        signin.reauthenticate(
            account_views.request_reauthentication_code, by_code=True
        ),
    ),
    path(
        "accounts/reauthenticate/code/confirm/",
        signin.reauthenticate(
            account_views.confirm_reauthentication_code, by_code=True
        ),
    ),
    path(
        "accounts/2fa/reauthenticate/", signin.reauthenticate(mfa_views.reauthenticate)
    ),
    path(
        "accounts/2fa/webauthn/reauthenticate/",
        signin.reauthenticate(webauthn_views.reauthenticate_webauthn),
    ),
    # The two-factor step asks for the authenticator app's code only
    # (specs/two-factor.md)
    path("accounts/2fa/authenticate/", signin.two_factor),
    # Passkeys and sessions are on the settings page
    path("accounts/2fa/", signin.passkeys_page),
    path("accounts/2fa/webauthn/", signin.passkeys_page),
    path("accounts/2fa/webauthn/add/", signin.add_passkey),
    path("accounts/2fa/totp/activate/", signin.activate_app),
    path("accounts/2fa/totp/deactivate/", signin.deactivate_app),
    path("accounts/sessions/", signin.sessions_page),
    path("accounts/3rdparty/", signin.connections_page),
    # People whose organization requires single sign-on go there instead
    # of asking for a code (specs/sso.md)
    path("accounts/login/", signin.login),
    path("accounts/login/code/", signin.request_login_code),
    path("accounts/", include("allauth.urls")),
    path("admin/", admin.site.urls),
]

if settings.DEBUG_TOOLBAR:  # pragma: no cover
    from debug_toolbar.toolbar import debug_toolbar_urls

    urlpatterns += debug_toolbar_urls()
