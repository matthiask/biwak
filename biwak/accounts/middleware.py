from django.contrib.auth.middleware import LoginRequiredMiddleware
from django.utils.translation import activate


def language_middleware(get_response):
    """The interface in the person's language, if they chose one"""

    def middleware(request):
        if request.user.is_authenticated and request.user.language:
            activate(request.user.language)
        return get_response(request)

    return middleware


class LoginRequired(LoginRequiredMiddleware):
    """Django's, but the API authenticates on its own (tokens, sessions;
    biwak/accounts/api_auth.py) and answers 401 instead of redirecting"""

    def process_view(self, request, view_func, view_args, view_kwargs):
        if request.path_info.startswith("/api/"):
            return None
        return super().process_view(request, view_func, view_args, view_kwargs)
