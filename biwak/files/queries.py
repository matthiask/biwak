"""What the project page, the message board and the API list (specs/files.md):
everything through ``Item.objects.visible_to()``"""

from django.db.models import Count, F, Q

from biwak.items.glance import with_checklist
from biwak.items.models import Item, Kind
from biwak.projects.models import MessagesOrder


# The project page shows this many messages, unless more are pinned
FRONT_MESSAGES = 5
# ... and this many of the latest changed docs and files
FRONT_FILES = 5


def board(project, user):
    """The project's messages (``None``: of all projects) as the person
    sees them (the one check), with comment counts"""
    messages = Item.objects.visible_to(user).filter(kind=Kind.MESSAGE)
    if project is not None:
        messages = messages.filter(project=project)
    return messages.select_related("creator", "message__category").annotate(
        comment_count=Count("comments")
    )


def pinned_messages(messages):
    """The latest pinned first"""
    return messages.filter(message__pinned_at__isnull=False).order_by(
        "-message__pinned_at", "-pk"
    )


def messages_order(project, wanted=None):
    """The order to show: ``wanted`` (``?order=``) if it is one, else the
    board's setting"""
    if wanted in MessagesOrder.values:
        return MessagesOrder(wanted)
    return MessagesOrder(project.messages_order)


def in_order(messages, order):
    """In the board's ``order``, the latest first, with ``sort_at`` (the
    time they're sorted by, for cursors)"""
    sort_at = (
        F("message__last_activity_at")
        if order == MessagesOrder.LATEST
        else F("created_at")
    )
    return messages.annotate(sort_at=sort_at).order_by("-sort_at", "-pk")


def latest_messages(messages, order):
    """The unpinned ones in the board's ``order``"""
    return in_order(messages.filter(message__pinned_at__isnull=True), order)


def front_messages(project, user):
    """The project page's messages: the pinned ones, then the latest in the
    board's order, ``FRONT_MESSAGES`` in all unless more are pinned"""
    messages = board(project, user)
    pinned = list(pinned_messages(messages))
    rest = max(0, FRONT_MESSAGES - len(pinned))
    latest = latest_messages(messages, messages_order(project))
    return pinned + list(latest[:rest])


def front_files(project, user):
    """The project page's docs and files: the latest ``FRONT_FILES`` changed
    ones, at any depth"""
    return list(
        with_checklist(Item.objects.visible_to(user))
        .filter(project=project, kind__in=[Kind.DOC, Kind.FILE])
        .select_related("creator")
        .order_by("-updated_at", "-pk")[:FRONT_FILES]
    )


def _counts(user, **filters):
    """{parent ID: {"folders": n, "docs": n, "files": n}} of the folders,
    docs and files the person can see"""
    found = {}
    rows = (
        Item.objects
        .visible_to(user)
        .filter(kind__in=[Kind.FOLDER, Kind.DOC, Kind.FILE], **filters)
        .values_list("parent", "kind")
        .annotate(n=Count("pk"))
        .order_by()
    )
    names = {Kind.FOLDER: "folders", Kind.DOC: "docs", Kind.FILE: "files"}
    for parent, kind, n in rows:
        found.setdefault(parent, {"folders": 0, "docs": 0, "files": 0})
        found[parent][names[kind]] = n
    return found


def root_counts(project, user):
    """What the root of the docs and files holds, for the project page:
    {"folders": n, "docs": n, "files": n}"""
    return _counts(user, project=project, parent=None).get(
        None, {"folders": 0, "docs": 0, "files": 0}
    )


def folder_counts(user, folders):
    """What each folder holds directly, for its tile (specs/files.md,
    "Folders"): {folder ID: {"folders": n, "docs": n, "files": n}}"""
    found = _counts(user, parent__in=[folder.pk for folder in folders])
    return {
        folder.pk: found.get(folder.pk, {"folders": 0, "docs": 0, "files": 0})
        for folder in folders
    }


def neighbours(versions, version):
    """The version before ``version`` (older, or None) and whether it is the
    newest; two small queries instead of loading every version"""
    before = Q(created_at__lt=version.created_at) | Q(
        created_at=version.created_at, pk__lt=version.pk
    )
    newer = Q(created_at__gt=version.created_at) | Q(
        created_at=version.created_at, pk__gt=version.pk
    )
    return versions.filter(before).first(), not versions.filter(newer).exists()
