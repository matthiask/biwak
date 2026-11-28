"""The API under /api/v1/ (specs/api-cli.md): everything the web interface
does. Conventions in biwak/api_conventions.py."""

from django.contrib.auth.decorators import login_required
from django.core.exceptions import BadRequest, PermissionDenied, ValidationError
from django.core.validators import ProhibitNullCharactersValidator
from django.db import DataError, connection, transaction
from ninja import NinjaAPI

from biwak.accounts.api import router as accounts_router
from biwak.accounts.api_auth import user_auth
from biwak.activity.api import (
    notifications_router,
    router as activity_router,
)
from biwak.bookmarks.api import router as bookmarks_router
from biwak.checkins.api import router as checkins_router
from biwak.files.api import router as files_router
from biwak.forwarding.api import router as forwarding_router
from biwak.items.api import router as items_router
from biwak.organizations.api import router as organizations_router
from biwak.projects.api import router as projects_router
from biwak.public_links.api import router as public_links_router
from biwak.reactions.api import router as reactions_router
from biwak.search.api import router as search_router
from biwak.teams.api import router as teams_router


class API(NinjaAPI):
    def on_exception(self, request, exc):
        """A refused request changes nothing: the errors are answered
        inside the view, so ``ATOMIC_REQUESTS`` alone committed what was
        done before the refusal (found 2026-11-28, verification round 2: a
        doc's read-only option lifted by a save answered with 409)"""
        if connection.in_atomic_block:
            transaction.set_rollback(True)
        return super().on_exception(request, exc)


api = API(
    title="Biwak",
    version="1",
    auth=user_auth(),
    docs_decorator=login_required,
    urls_namespace="api",
)


@api.exception_handler(ValidationError)
def validation_error(request, exc):
    """What the models refuse (``full_clean()``) is the request's mistake"""
    return api.create_response(request, {"detail": " ".join(exc.messages)}, status=400)


@api.exception_handler(DataError)
def data_error(request, exc):
    """A NUL character in a text, which the pages' forms refuse"""
    if "NUL" not in str(exc):
        raise exc
    return api.create_response(
        request, {"detail": str(ProhibitNullCharactersValidator.message)}, status=400
    )


def _shared_check(status):
    """Checks shared with the pages (``changeable_list()``,
    ``todos_to_move()``) answer with their message"""

    def handler(request, exc):
        return api.create_response(request, {"detail": str(exc)}, status=status)

    return handler


api.add_exception_handler(PermissionDenied, _shared_check(403))
api.add_exception_handler(BadRequest, _shared_check(400))


api.add_router("/", accounts_router)
api.add_router("/", projects_router)
api.add_router("/", organizations_router)
api.add_router("/", teams_router)
api.add_router("/", items_router)
api.add_router("/", files_router)
api.add_router("/", activity_router)
api.add_router("/", notifications_router)
api.add_router("/", bookmarks_router)
api.add_router("/", public_links_router)
api.add_router("/", forwarding_router)
api.add_router("/", reactions_router)
api.add_router("/", checkins_router)
api.add_router("/", search_router)
