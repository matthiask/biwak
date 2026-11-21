# Copyright (c) 2026, Feinheit AG and individual contributors (Governance's
# governance/help.py, see NOTICE)
"""The user documentation in docs/ as help pages

English in ``name.md``, German in ``name.de.md`` (not written yet, the table
below keeps the place), shown in the page's language. The Markdown files link
each other relatively (``todos.md``), which works on GitHub; here the links
lead to the help pages instead.
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


def _pages(language):
    # No German files yet: they come with the German translation
    german = PAGES["de"]
    english = PAGES["en"]
    if language == "de" and all(
        (settings.BASE_DIR / "docs" / file).exists() for file in german.values()
    ):
        return german
    return english


def chapters(page, language="en"):
    """All pages in their order (the start page first), for the navigation
    above each: their titles, the current one"""
    result = []
    for key, file in _pages(language).items():
        with (settings.BASE_DIR / "docs" / file).open() as f:
            title = _title(f.readline())
        result.append({"url": url(key), "title": title, "current": key == page})
    return result


def render_page(page, language="en"):
    pages = _pages(language)
    if page not in pages:
        raise Http404
    text = (settings.BASE_DIR / "docs" / pages[page]).read_text()
    title = _title(text.split("\n", 1)[0])
    # Links relative to the page's file
    here = posixpath.dirname(pages[page])
    files = {posixpath.relpath(file, here or "."): key for key, file in pages.items()}

    def link(match):
        if match[1] not in files:
            return match[0]
        return f'href="{url(files[match[1]])}{match[2] or ""}"'

    html = _markdown.render(text)
    html = re.sub(r"^<h1>.*?</h1>\n", "", html, count=1)  # The page's title
    return title, mark_safe(_link.sub(link, html))


def help_page(request, page=""):
    language = "de" if get_language() == "de" else "en"
    if page not in _pages(language):
        raise Http404
    context = {
        "chapters": chapters(page, language),
        "shortcuts": page in WITH_SHORTCUTS,
    }
    context["title"], context["html"] = render_page(page, language)
    return render(request, "help.html", context)
