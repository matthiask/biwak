"""The jumps of the command palette (specs/keyboard.md): projects, lists,
messages, docs, files, folders, check-in questions and people whose title or
name has every word, as the start of a word (the search's ``simple``
configuration and its word reading, ``biwak.search.queries``).

Everything goes through the same checks as everything else:
``Project.objects.accessible_to()``, ``Item.objects.visible_to()`` and, for
people, ``people_visible_to()`` (the members rule: clients only learn about
the members of their projects). Titles are shown as written: mentions with
the label, never the current name."""

from django.db.models.functions import Lower
from django.template.defaultfilters import date as date_filter
from django.urls import reverse
from django.utils.translation import gettext as _

from biwak.activity.feed import people_visible_to
from biwak.activity.mentions import plain
from biwak.bookmarks.models import Bookmark
from biwak.items import due
from biwak.items.models import Item, Kind
from biwak.projects.models import Project
from biwak.search.queries import Matches, prefixes, tsquery, vector


LIMIT = 20

# The order of the groups
KINDS = [
    "project",
    Kind.LIST,
    Kind.MESSAGE,
    Kind.DOC,
    Kind.FILE,
    Kind.FOLDER,
    Kind.QUESTION,
    "person",
]
ORDER = {kind: index for index, kind in enumerate(KINDS)}
ITEM_KINDS = [kind for kind in KINDS if kind not in {"project", "person"}]


def has_words(queryset, column, words):
    """Every word is the start of a word of the column"""
    for word in words:
        queryset = queryset.filter(Matches(vector(column), tsquery(word)))
    return queryset


def jumps(user, terms):
    """At most ``LIMIT`` results as dicts, grouped by kind, those in
    archived projects last"""
    words = prefixes(terms)
    if not words:
        return []
    results = []
    projects = has_words(Project.objects.accessible_to(user), "name", words)
    for project in projects.order_by("archived_at", "name")[:LIMIT]:
        results.append({
            "kind": "project",
            "label": _("Project"),
            "title": project.name,
            "url": project.get_absolute_url(),
            "context": "",
            **color_of(project),
            "archived": project.archived_at is not None,
            "visible_to_clients": False,
        })
    items = has_words(
        Item.objects.visible_to(user).filter(kind__in=ITEM_KINDS), "title", words
    ).select_related("project")
    for item in items.order_by("project__archived_at", Lower("title"))[:LIMIT]:
        results.append({
            "kind": item.kind,
            "label": item.get_kind_display(),
            "title": plain(item.title),
            "url": item.get_absolute_url(),
            "context": item.project.name,
            **color_of(item.project),
            "archived": item.project.archived_at is not None,
            "visible_to_clients": item.is_client_visible,
        })
    people = people_visible_to(user).filter(is_active=True)
    for word in words:
        people = people.filter(
            Matches(vector("full_name"), tsquery(word))
            | Matches(vector("short_name"), tsquery(word))
        )
    for person in people.order_by("full_name", "email")[:LIMIT]:
        results.append({
            "kind": "person",
            "label": _("Person"),
            "title": person.display_name,
            "url": person_url(person),
            "context": "",
            "archived": False,
            "visible_to_clients": False,
        })
    results.sort(key=lambda r: (r["archived"], ORDER[r["kind"]], r["title"].lower()))
    return results[:LIMIT]


def color_of(project):
    """The project's color for the dot before its name, with its label"""
    return {"color": project.color, "color_name": project.color_label}


def due_label(item):
    """ "Overdue · 19. Nov" or "Today" for an open to-do that's due, else
    nothing; the state is ``"overdue"`` or ``"today"`` (the badge's tone)"""
    todo = getattr(item, "todo", None) if item.kind == Kind.TODO else None
    state = due.badge_state(todo) if todo else ""
    if state == due.OVERDUE:
        day = date_filter(todo.due_on, "j. M")
        return {"state": state, "label": _("Overdue · %(day)s") % {"day": day}}
    if state == due.TODAY:
        return {"state": state, "label": _("Today")}
    return None


def person_url(person):
    return reverse("person_feed", args=[person.pk])


def bookmarks(user):
    """The person's bookmarks, newest first, of what they may still open
    (``Bookmark.objects.visible_to()``, like the bookmarks page), at most
    ``LIMIT``"""
    found = Bookmark.objects.visible_to(user).select_related(
        "item", "item__project", "item__answer", "item__todo", "project"
    )
    results = []
    for bookmark in found[:LIMIT]:
        if bookmark.item_id:
            item = bookmark.item
            results.append({
                "kind": item.kind,
                "label": item.get_kind_display(),
                "title": plain(item.title),
                "url": item.get_absolute_url(),
                "context": item.project.name,
                **color_of(item.project),
                "archived": item.project.archived_at is not None,
                "visible_to_clients": item.is_client_visible,
                "due": due_label(item),
            })
        else:
            project = bookmark.project
            results.append({
                "kind": "project",
                "label": _("Project"),
                "title": project.name,
                "url": project.get_absolute_url(),
                "context": "",
                **color_of(project),
                "archived": project.archived_at is not None,
                "visible_to_clients": False,
            })
    return results
