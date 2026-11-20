"""The API under /api/v1/ (specs/api-cli.md): everything the web interface
does. Conventions in biwak/api_conventions.py."""

from django.contrib.auth.decorators import login_required
from ninja import NinjaAPI

from biwak.accounts.api import router as accounts_router
from biwak.accounts.api_auth import user_auth
from biwak.activity.api import (
    notifications_router,
    router as activity_router,
)
from biwak.bookmarks.api import router as bookmarks_router
from biwak.files.api import router as files_router
from biwak.items.api import router as items_router
from biwak.projects.api import router as projects_router


api = NinjaAPI(
    title="Biwak",
    version="1",
    auth=user_auth(),
    docs_decorator=login_required,
    urls_namespace="api",
)
api.add_router("/", accounts_router)
api.add_router("/", projects_router)
api.add_router("/", items_router)
api.add_router("/", files_router)
api.add_router("/", activity_router)
api.add_router("/", notifications_router)
api.add_router("/", bookmarks_router)
