"""The stored effective visibility (specs/access.md)

An item is visible to clients when the switch of its top-level ancestor
(or its own, at the top level) is on. Stored on every item so that
``Item.objects.visible_to()`` is a plain filter; recomputed here for whole
subtrees whenever a switch changes, an item moves or is created, in the
same transaction. ``check()`` compares the stored values with the tree.
"""

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
    the project's active client members, invited ones included,
    deactivated ones not (decided 2026-11-28)"""
    return (
        project.memberships
        .filter(user__is_client=True, user__is_active=True)
        .values("user")
        .distinct()
        .count()
    )


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


def shown_by_moving(todos, todolist):
    """What moving the to-dos into the list ``todolist`` shows clients,
    for asking first like the switch (decided 2026-11-28): the internal
    ones going into a list clients see, their comments, and the clients
    of the list's project (``clients_of()``); None if it shows
    nothing"""
    if not todolist.is_client_visible:
        return None
    hidden = [todo.pk for todo in todos if not todo.is_client_visible]
    if not hidden:
        return None
    return {
        "items": len(hidden),
        "comments": Comment.objects.filter(item__in=hidden).count(),
        "clients": clients_of(todolist.project),
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
