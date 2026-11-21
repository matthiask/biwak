"""The command palette's jumps (specs/keyboard.md); the actions of a page
come with the page (``biwak.palette.actions``)"""

from django.http import JsonResponse
from django.views.decorators.cache import never_cache

from biwak.palette import queries


@never_cache
def palette(request):
    """``GET /palette/?q=``: at most 20 projects, lists, messages, docs, files,
    folders, check-in questions and people the person may open, matched by
    title or name"""
    terms = request.GET.get("q", "").strip()
    return JsonResponse({"results": queries.jumps(request.user, terms)})
