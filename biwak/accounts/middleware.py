import unicodedata

from django.contrib.auth.middleware import LoginRequiredMiddleware
from django.db import connections
from django.utils.translation import activate, deactivate


def set_user_name(user):
    """Who the audit log (biwak/audit/) records for changes, a person or a
    name like ``Fairy tasks``"""
    if not isinstance(user, str):
        user = f"user-{user.pk}-{user.get_short_name()}"
    # PostgreSQL keeps only ASCII in application_name (others become
    # escapes like \xc3\xbc) and 63 bytes: "Jürg" is written "Jurg"
    user = unicodedata.normalize("NFKD", user).encode("ascii", "ignore").decode()
    connections["default"].cursor().execute(
        "SET SESSION application_name TO %s", [user]
    )


def language_middleware(get_response):
    """Outside of ``LocaleMiddleware``: back to the default language once
    the response is done, so that what runs next in the thread (a test,
    the next task) doesn't go on in the request's"""

    def middleware(request):
        try:
            return get_response(request)
        finally:
            deactivate()

    return middleware


def user_middleware(get_response):
    """The person's language, if they chose one, their name for the audit
    log, and who reads the mentions' names (``biwak.activity.mentions``;
    late, the API's token authentication sets ``request.user`` itself)"""
    from biwak.activity.mentions import reading_as

    def middleware(request):
        if request.user.is_authenticated:
            set_user_name(request.user)
            if request.user.language:
                activate(request.user.language)
        else:
            set_user_name("user-0-anonymous")
        with reading_as(lambda: request.user):
            return get_response(request)

    return middleware


class LoginRequired(LoginRequiredMiddleware):
    """Django's, but the API authenticates on its own (tokens, sessions;
    biwak/accounts/api_auth.py) and answers 401 instead of redirecting"""

    def process_view(self, request, view_func, view_args, view_kwargs):
        if request.path_info.startswith("/api/"):
            return None
        return super().process_view(request, view_func, view_args, view_kwargs)
