from django.contrib.auth.middleware import LoginRequiredMiddleware
from django.db import connections
from django.utils.translation import activate


def set_user_name(user):
    """Who the audit log (biwak/audit/) records for changes, a person or a
    name like ``Fairy tasks``"""
    if not isinstance(user, str):
        user = f"user-{user.pk}-{user.get_short_name()}"
    connections["default"].cursor().execute(
        "SET SESSION application_name TO %s", [user]
    )


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
