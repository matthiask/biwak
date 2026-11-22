# Copyright (c) 2026, Feinheit AG and individual contributors (Governance's
# governance/help.py, see NOTICE)
"""The user documentation in docs/ as help pages

English in ``name.md``, German in ``name.de.md``, shown in the page's
language; a page without a German file is shown in English (decided
2026-11-22, specs/help.md). The Markdown files link each other relatively
(``todos.md``, ``todos.de.md``), which works on GitHub; here the links lead to
the help pages instead.
"""

import posixpath
import re

from django.conf import settings
from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.utils.translation import get_language
from markdown_it import MarkdownIt


# Page → file in docs/ per language, the README is the start page
_NAMES = {
    "": "README",
    "orientation": "orientation",
    "todos": "todos",
    "files": "files",
    "checkins": "checkins",
    "notifications": "notifications",
    "clients": "clients",
    "keyboard": "keyboard",
    "sign-in": "sign-in",
    "cli": "cli",
}
PAGES = {
    "en": {page: f"{name}.md" for page, name in _NAMES.items()},
    "de": {page: f"{name}.de.md" for page, name in _NAMES.items()},
}
# Pages ending with the shortcuts list (palette/_shortcuts.html), which is
# the one list: the "?" dialog renders it too
WITH_SHORTCUTS = {"keyboard"}
# The docs come from the repository, not from users: HTML like <kbd> is fine
_markdown = MarkdownIt("commonmark", {"html": True}).enable("table")
_link = re.compile(r'href="([^":#]+\.md)(#[^"]*)?"')


def url(page):
    return reverse("help", args=[page]) if page else reverse("help")


def _title(line):
    return re.sub(r"[*_]", "", line.removeprefix("# ")).strip()


def _file(page, language):
    """The page's file in the language, else the English one"""
    file = PAGES.get(language, {}).get(page)
    if file and (settings.BASE_DIR / "docs" / file).exists():
        return file
    return PAGES["en"][page]


def chapters(page, language="en"):
    """All pages in their order (the start page first), for the navigation
    above each: their titles, the current one"""
    result = []
    for key in PAGES["en"]:
        with (settings.BASE_DIR / "docs" / _file(key, language)).open() as f:
            title = _title(f.readline())
        result.append({"url": url(key), "title": title, "current": key == page})
    return result


def render_page(page, language="en"):
    if page not in PAGES["en"]:
        raise Http404
    file = _file(page, language)
    text = (settings.BASE_DIR / "docs" / file).read_text()
    title = _title(text.split("\n", 1)[0])
    # Links relative to the page's file, to the files of either language
    here = posixpath.dirname(file)
    files = {
        posixpath.relpath(name, here or "."): key
        for pages in PAGES.values()
        for key, name in pages.items()
    }

    def link(match):
        if match[1] not in files:
            return match[0]
        return f'href="{url(files[match[1]])}{match[2] or ""}"'

    html = _markdown.render(text)
    html = re.sub(r"^<h1>.*?</h1>\n", "", html, count=1)  # The page's title
    return title, mark_safe(_link.sub(link, html))


def help_page(request, page=""):
    language = "de" if get_language() == "de" else "en"
    if page not in PAGES["en"]:
        raise Http404
    context = {
        # A page without a German file is shown in English, with a line
        # saying so (specs/help.md)
        "english_only": _file(page, language) != PAGES[language][page],
        "chapters": chapters(page, language),
        "shortcuts": page in WITH_SHORTCUTS,
    }
    context["title"], context["html"] = render_page(page, language)
    return render(request, "help.html", context)
