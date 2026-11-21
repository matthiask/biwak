"""Who may do what, where pages and the API ask the same"""

from django.core.exceptions import PermissionDenied
from ninja.errors import HttpError


def staff_only(request):
    """Pages: clients get 403"""
    if request.user.is_client:
        raise PermissionDenied


def api_staff_only(request, message):
    """The API: clients get 403 with ``message``"""
    if request.user.is_client:
        raise HttpError(403, message)
