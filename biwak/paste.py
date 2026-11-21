"""Pasting rich text into Markdown fields (specs/editor.md): the page sends
the HTML of the clipboard, the answer is Markdown from the converter the
importer uses (``biwak/htmlmarkdown.py``), so there is one in Python and
none in JavaScript. Changes nothing, for every logged-in person."""

from django.http import JsonResponse
from django.views.decorators.http import require_POST

from biwak.htmlmarkdown import from_clipboard


@require_POST
def html_to_markdown(request):
    return JsonResponse({"markdown": from_clipboard(request.POST.get("html", ""))})
