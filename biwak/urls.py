from django.conf import settings
from django.contrib import admin
from django.contrib.auth.decorators import login_not_required
from django.shortcuts import redirect
from django.templatetags.static import static
from django.urls import include, path


@login_not_required
def favicon(request):
    """Browsers ask for /favicon.ico without looking at the page"""
    return redirect(static("biwak/favicon.svg"), permanent=True)


urlpatterns = [
    path("favicon.ico", favicon),
    path("", include("biwak.projects.urls")),
    path("", include("biwak.items.urls")),
    path("accounts/", include("allauth.urls")),
    path("admin/", admin.site.urls),
]

if settings.DEBUG_TOOLBAR:  # pragma: no cover
    from debug_toolbar.toolbar import debug_toolbar_urls

    urlpatterns += debug_toolbar_urls()
