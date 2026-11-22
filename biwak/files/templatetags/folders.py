from django import template
from django.utils.translation import gettext, ngettext


register = template.Library()


@register.filter
def folder_counts(counts):
    """What a folder holds directly, for its tile (specs/files.md,
    "Folders"): "2 folders · 1 file", zeros left out, "Empty" for none"""
    parts = [
        ngettext("%(n)s folder", "%(n)s folders", counts["folders"])
        % {"n": counts["folders"]}
        if counts["folders"]
        else "",
        ngettext("%(n)s doc", "%(n)s docs", counts["docs"]) % {"n": counts["docs"]}
        if counts["docs"]
        else "",
        ngettext("%(n)s file", "%(n)s files", counts["files"]) % {"n": counts["files"]}
        if counts["files"]
        else "",
    ]
    return " · ".join(part for part in parts if part) or gettext("Empty")
