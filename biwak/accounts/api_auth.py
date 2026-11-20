"""Who calls the API: personal tokens (the biwak CLI, scripts) or the
browser's session (specs/api-cli.md)"""

from django.utils.translation import activate, gettext as _
from ninja.errors import HttpError
from ninja.security import HttpBearer, SessionAuth

from biwak.accounts.models import APIToken


SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class UserToken(HttpBearer):
    def __init__(self, *, allow_read_only=False):
        super().__init__()
        self.allow_read_only = allow_read_only

    def authenticate(self, request, token):
        if not (token := APIToken.objects.for_secret(token)):
            return None
        user = token.user
        request.user = user
        request.api_token = token
        # The language middleware only does this for sessions
        if user.language:
            activate(user.language)
        if (
            token.access == APIToken.Access.READ
            and not self.allow_read_only
            and request.method not in SAFE_METHODS
        ):
            raise HttpError(403, _("This API token only allows reading, not changes."))
        # Only allowed uses extend the token
        APIToken.objects.extend(token)
        return user


class UserSession(SessionAuth):
    def __call__(self, request):
        # Invalid tokens are a 401, not the CSRF failure which the session
        # authentication checks first
        if request.headers.get("authorization", "").lower().startswith("bearer "):
            return None
        return super().__call__(request)


def user_auth(*, allow_read_only=False):
    """Tokens first: the session authentication fails without a CSRF token.
    Read-only tokens only GET unless ``allow_read_only``, e.g. for revoking
    themselves."""
    return [UserToken(allow_read_only=allow_read_only), UserSession()]
