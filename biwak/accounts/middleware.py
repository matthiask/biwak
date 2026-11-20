from django.utils.translation import activate


def language_middleware(get_response):
    """The interface in the person's language, if they chose one"""

    def middleware(request):
        if request.user.is_authenticated and request.user.language:
            activate(request.user.language)
        return get_response(request)

    return middleware
