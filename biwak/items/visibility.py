"""The stored effective visibility (specs/access.md)

An item is visible to clients when the switch of its top-level ancestor
(or its own, at the top level) is on. Stored on every item so that
``Item.objects.visible_to()`` is a plain filter; recomputed here for whole
subtrees whenever a switch changes, an item moves or is created, in the
same transaction. ``check()`` compares the stored values with the tree.
"""

from biwak.accounts.models import User
from biwak.items.models import Comment, Item, Status


def expected(item):
    """The effective visibility computed from the tree"""
    if item.parent_id is None:
        return item.visible_to_clients and item.has_switch
    root = Item.objects.ancestors(item).filter(parent=None).get()
    return root.visible_to_clients and root.has_switch


def recompute(item):
    """Stores the effective visibility of the item and its descendants"""
    value = expected(item)
    pks = Item.objects.descendants(item, include_self=True).values_list("pk", flat=True)
    Item.objects.filter(pk__in=list(pks)).exclude(is_client_visible=value).update(
        is_client_visible=value
    )
    item.is_client_visible = value


def set_switch(item, *, visible):
    """Turns the switch of a top-level item on or off"""
    if not item.has_switch:
        raise ValueError(f"{item!r} has no visibility switch")
    item.visible_to_clients = visible
    item.save(update_fields=["visible_to_clients"])
    recompute(item)


def clients_of(project):
    """How many clients the "visible to N clients" of the questions counts:
    those who haven't left (``Project.client_members()``)"""
    return project.client_members().count()


def affected(item):
    """What turning the switch on would show, for the switch's question:
    the item's descendants, their comments and its own, and the clients
    among the project's members who would see them (``clients_of()``).
    Not drafts (only their creators see them) and not what's in the
    trash."""

    pks = list(
        Item.objects
        .descendants(item)
        .filter(is_draft=False)
        .exclude(status=Status.TRASHED)
        .values_list("pk", flat=True)
    )
    return {
        "items": len(pks),
        "comments": Comment.objects.filter(item__in=[item.pk, *pks]).count(),
        "clients": clients_of(item.project),
    }


def shown_by_moving_into(todos, project, *, visible):
    """What moving the to-dos into a list of ``project`` (``visible`` to
    clients or not; a new one too) shows clients,
    for asking first like the switch (decided 2026-11-28): the internal
    ones going into a list clients see, shown to the clients of the
    list's project (``clients_of()``), and visible ones from other
    projects whose clients there didn't see them (as
    ``operations.new_clients()``); their comments, and how many clients
    see something new. None if it shows nothing."""
    if not visible:
        return None
    clients = User.objects.active().filter(is_client=True, memberships__project=project)
    shown = [todo.pk for todo in todos if not todo.is_client_visible]
    new = set(clients.values_list("pk", flat=True)) if shown else set()
    sources = {
        todo.project_id
        for todo in todos
        if todo.is_client_visible and todo.project_id != project.pk
    }
    for source in sources:
        if newly := set(
            clients.exclude(memberships__project=source).values_list("pk", flat=True)
        ):
            new |= newly
            shown += [
                todo.pk
                for todo in todos
                if todo.is_client_visible and todo.project_id == source
            ]
    if not shown:
        return None
    return {
        "items": len(shown),
        "comments": Comment.objects.filter(item__in=shown).count(),
        "clients": len(new),
    }


def shown_by_moving_items(items, folder):
    """What moving folders, docs and files into ``folder`` (None: the top
    level) shows clients, asking like the switch (decided 2026-11-28):
    the internal ones going into a folder clients see and what's in them
    (``affected()``: not drafts, not the trash), their comments, and the
    clients of the project (``clients_of()``); None if it shows nothing"""
    if folder is None or not folder.is_client_visible:
        return None
    shown = [item for item in items if not item.is_client_visible and not item.is_draft]
    if not shown:
        return None
    pks = {item.pk for item in shown}
    for item in shown:
        pks.update(
            Item.objects
            .descendants(item)
            .filter(is_draft=False)
            .exclude(status=Status.TRASHED)
            .values_list("pk", flat=True)
        )
    return {
        "items": len(pks),
        "comments": Comment.objects.filter(item__in=pks).count(),
        "clients": clients_of(folder.project),
    }


def check():
    """Items whose stored visibility differs from the tree's, as a list of
    (item, stored, expected)"""
    roots = {
        root.pk: root.visible_to_clients and root.has_switch
        for root in Item.objects.filter(parent=None)
    }
    differences = []
    for item in Item.objects.with_tree_fields().select_related(None):
        value = roots[item.tree_path[0]]
        if item.is_client_visible != value:
            differences.append((item, item.is_client_visible, value))
    return differences
