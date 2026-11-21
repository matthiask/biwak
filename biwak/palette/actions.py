"""The actions of the command palette and the shortcuts of a page
(specs/keyboard.md).

The server decides what a person may do and renders the actions of every
page as JSON (``{% palette %}`` in ``base.html``); ``frontend/palette.js``
and ``frontend/shortcuts.js`` only run them, they never decide permissions.
The same rules as the buttons of the pages: ``ops.can_create()``,
``ops.can_change()``, staff only where the views are.

An action is a dict with ``label``, ``type`` and what the type needs, and
optionally a ``shortcut`` ("x", or "g p" for two keys):

- ``link``: go to ``url``;
- ``modal``: open the form at ``url`` in a modal (``frontend/modal.js``);
  the form's own page where JavaScript isn't there to run it;
- ``post``: POST ``data`` to ``url``, then follow the answer;
- ``focus``: focus the first element matching ``selector`` (opening the
  ``<details>`` around it); on another page ``url`` has the page of the
  element, which gets focused when it loads (``#id`` of a field);
- ``copy``: copy ``text`` to the clipboard;
- ``theme``: cycle the theme.
"""

from django.urls import reverse
from django.utils.translation import gettext as _

from biwak.activity.operations import is_assigned, is_subscribed
from biwak.bookmarks.operations import can_manage_links, is_bookmarked
from biwak.items import operations as ops
from biwak.items.models import Item, Kind
from biwak.organizations import operations as org_ops
from biwak.organizations.models import Organization
from biwak.projects import operations as project_ops
from biwak.projects.models import Project


# Pages of a project, which show its actions
PROJECT_PAGES = {
    "project",
    "project_messages",
    "project_files",
    "project_checkins",
    "project_feed",
    "project_people",
    "project_todos",
    "folder",
}
# Pages of an item, with the kind they show
ITEM_PAGES = {
    "todo": Kind.TODO,
    "list": Kind.LIST,
    "message": Kind.MESSAGE,
    "doc": Kind.DOC,
    "file": Kind.FILE,
    "question": Kind.QUESTION,
    "folder": Kind.FOLDER,
}

COMMENT_FORM = 'form:has(> input[name="form"][value="comment"]) textarea'
EDIT_OPEN = "[data-edit-open]"
ADD_TODO = ".wb-add-todo-form [name=title]"

# Kinds with an edit page (to-dos, messages and files edit on their page)
EDIT_URLS = {
    Kind.LIST: "list_edit",
    Kind.MESSAGE: "message_edit",
    Kind.DOC: "doc_edit",
    Kind.FILE: "file_edit",
}


def link(label, url, shortcut="", *, exact=False):
    """``exact``: the URL's own query, not the one remembered for the page
    (frontend/filters.js)"""
    action = {"label": label, "type": "link", "url": url, "shortcut": shortcut}
    if exact:
        action["exact"] = True
    return action


def modal(label, url, shortcut=""):
    return {"label": label, "type": "modal", "url": url, "shortcut": shortcut}


def post(label, url, data=None, shortcut=""):
    return {
        "label": label,
        "type": "post",
        "url": url,
        "data": data or {},
        "shortcut": shortcut,
    }


def focus(label, selector, url="", shortcut=""):
    return {
        "label": label,
        "type": "focus",
        "selector": selector,
        "url": url,
        "shortcut": shortcut,
    }


def click(label, selector, url, shortcut=""):
    """Clicks the page's element (the "Edit" link, which swaps in the form
    in place, frontend/view-edit.js) or, without one, opens ``url``"""
    return {
        "label": label,
        "type": "click",
        "selector": selector,
        "url": url,
        "shortcut": shortcut,
    }


def everywhere(user):
    """What every page offers"""
    actions = [
        link(_("Go home"), reverse("dashboard"), "g h"),
        link(_("Go to projects"), reverse("projects"), "g p"),
        link(_("Go to the activity"), reverse("feed"), "g f"),
        link(_("Go to to-dos"), reverse("todos"), "g t"),
        link(
            _("To-dos I assigned"),
            reverse("todos") + "?assignee=&assigned_by=me",
            exact=True,
        ),
        link(_("Go to bookmarks"), reverse("bookmarks"), "g b"),
        link(_("Go to people"), reverse("people")),
        link(_("Settings"), reverse("settings")),
        link(_("Search"), reverse("search")),
        link(_("Help"), reverse("help")),
        link(_("Keyboard shortcuts"), reverse("help", args=["keyboard"])),
        {"label": _("Switch the theme"), "type": "theme", "shortcut": ""},
    ]
    if project_ops.can_create_project(user):
        actions.append(modal(_("New project"), reverse("project_create")))
    if org_ops.can_manage(user):
        actions.append(link(_("Go to organizations"), reverse("organizations")))
    return actions


def in_project(user, project, folder=None):
    """What a project's pages offer"""
    actions = []
    if ops.can_create(user, Kind.LIST):
        actions.append(modal(_("New list"), reverse("list_new", args=[project.pk])))
    if ops.can_create(user, Kind.MESSAGE):
        actions.append(
            link(_("New message"), reverse("message_new", args=[project.pk]))
        )
    where = f"?folder={folder.pk}" if folder else ""
    if ops.can_create(user, Kind.DOC):
        actions.append(
            link(_("New doc"), reverse("doc_new", args=[project.pk]) + where)
        )
    if ops.can_create(user, Kind.FILE):
        actions.append(
            link(_("Upload a file"), reverse("file_new", args=[project.pk]) + where)
        )
    if not user.is_client:
        actions.append(
            link(_("New check-in"), reverse("question_new", args=[project.pk]))
        )
    if can_manage_links(user):
        actions.append(
            modal(_("Add a link"), reverse("project_link_new", args=[project.pk]))
        )
    actions += [
        link(_("The project's activity"), reverse("project_feed", args=[project.pk])),
        link(_("People"), reverse("project_people", args=[project.pk])),
        link(_("Docs and files"), reverse("project_files", args=[project.pk])),
        link(_("All to-dos"), reverse("project_todos", args=[project.pk])),
    ]
    return actions


def on_item(request, item, context):
    """What an item's page offers; ``context`` is the page's"""
    user = request.user
    url = item.get_absolute_url()
    actions = []
    if item.kind == Kind.TODO:
        # Everybody who sees a to-do completes it (specs/access.md)
        completed = item.todo.is_completed
        actions.append(
            post(
                _("Reopen") if completed else _("Complete"),
                reverse("todo_toggle", args=[item.pk]),
                {"next": url},
                "x",
            )
        )
    if item.kind == Kind.LIST:
        view = context.get("view")
        actions.append(focus(_("New to-do"), ADD_TODO))
        if view == "board":
            actions.append(link(_("List view"), f"{url}?view=list"))
        else:
            actions.append(link(_("Board view"), f"{url}?view=board"))
    if item.is_commentable:
        actions.append(focus(_("Comment"), COMMENT_FORM, shortcut="c"))
    if item.kind == Kind.TODO:
        edit_url = reverse("todo_edit", args=[item.pk])
        actions.append(click(_("Edit"), EDIT_OPEN, edit_url, "e"))
    elif item.kind in EDIT_URLS and ops.can_change(user, item):
        edit_url = reverse(EDIT_URLS[item.kind], args=[item.pk])
        if item.kind in {Kind.MESSAGE, Kind.FILE}:
            actions.append(click(_("Edit"), EDIT_OPEN, edit_url, "e"))
        else:
            actions.append(link(_("Edit"), edit_url, "e"))
    elif item.kind == Kind.QUESTION and not user.is_client:
        actions.append(link(_("Edit"), reverse("question_edit", args=[item.pk]), "e"))
    bookmarked = is_bookmarked(user, item=item)
    actions.append(
        post(
            _("Remove the bookmark") if bookmarked else _("Bookmark"),
            reverse("item_bookmark", args=[item.pk]),
            {} if bookmarked else {"bookmark": "1"},
            "b",
        )
    )
    subscribed = is_subscribed(user, item)
    if is_assigned(user, item):
        # Assigned means subscribed: the way out is unassigning
        actions.append(
            post(
                _("Unassign me"),
                reverse("subscription", args=[item.pk]),
                {"unassign": "1"},
                "s",
            )
        )
    else:
        actions.append(
            post(
                _("Unsubscribe") if subscribed else _("Subscribe"),
                reverse("subscription", args=[item.pk]),
                {} if subscribed else {"subscribe": "1"},
                "s",
            )
        )
    actions.append(
        modal(_("Subscribers…"), reverse("item_subscribers", args=[item.pk]))
    )
    if not user.is_client:
        actions.append(link(_("History"), reverse("item_history", args=[item.pk])))
    actions.append({
        "label": _("Copy the link"),
        "type": "copy",
        "text": request.build_absolute_uri(url),
        "shortcut": "",
    })
    return actions


def on_organizations(user, name, organization):
    """The organizations' pages (staff, as their buttons)"""
    if name not in {"organizations", "organization"} or not org_ops.can_manage(user):
        return []
    actions = [modal(_("New organization"), reverse("organization_create"))]
    if name == "organization" and isinstance(organization, Organization):
        actions.append(
            modal(_("Edit"), reverse("organization_edit", args=[organization.pk]), "e")
        )
        if org_ops.can_touch(user, organization):
            actions.append(
                modal(
                    _("Merge…"), reverse("organization_merge", args=[organization.pk])
                )
            )
    return actions


def on_people(user, name):
    """The People page: inviting, for the staff who manage members
    (specs/ui-round-6.md)"""
    if name != "people" or not project_ops.can_manage_members(user):
        return []
    return [modal(_("Invite people"), reverse("invite_people"))]


def for_page(request, context):
    """The actions of the page: ``[{..., "group": "page"|"everywhere"}]``,
    those of the page first. ``context`` is the template's: the page's
    project or item (only of the pages listed above, not of forms) decide."""
    user = request.user
    name = request.resolver_match.url_name if request.resolver_match else None
    page = []
    item = context.get("item")
    project = context.get("project")
    if name in ITEM_PAGES and isinstance(item, Item) and item.kind == ITEM_PAGES[name]:
        project = item.project
    else:
        item = None
    if name in PROJECT_PAGES and isinstance(project, Project):
        page += in_project(user, project, folder=item if name == "folder" else None)
    if item is not None:
        page += on_item(request, item, context)
    page += on_organizations(user, name, context.get("organization"))
    page += on_people(user, name)
    return [{**a, "group": "page"} for a in page] + [
        {**a, "group": "everywhere"} for a in everywhere(user)
    ]
