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
    pages (set, change, reset) don't exist"""
    raise Http404


urlpatterns = [
    path("favicon.ico", favicon),
    path("manifest.webmanifest", manifest),
    path("", include("biwak.projects.urls")),
    path("", include("biwak.organizations.urls")),
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
    # Passkeys and sessions are on the settings page
    path("accounts/2fa/", signin.passkeys_page),
    path("accounts/2fa/webauthn/", signin.passkeys_page),
    path("accounts/sessions/", signin.sessions_page),
    path("accounts/", include("allauth.urls")),
    path("admin/", admin.site.urls),
]

if settings.DEBUG_TOOLBAR:  # pragma: no cover
    from debug_toolbar.toolbar import debug_toolbar_urls

    urlpatterns += debug_toolbar_urls()
