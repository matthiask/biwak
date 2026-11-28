"""The trampoline of links to Basecamp recordings (``biwak.importer.links``)"""

from django.http import Http404
from django.shortcuts import redirect

from biwak.importer import links


def basecamp_link(request):
    """To what was imported from the recording if the person may see it,
    else to Basecamp; only Basecamp's addresses of recordings (no open
    redirect)"""
    href = request.GET.get("to", "")
    if links.recording(href) is None:
        raise Http404
    return redirect(links.destination(request.user, href))
