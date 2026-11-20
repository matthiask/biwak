"""What the project page, the message board and the API list (specs/files.md):
everything through ``Item.objects.visible_to()``"""

from django.db.models import Count

from biwak.items.models import Item, Kind


# The project page shows this many messages, unless more are pinned
FRONT_MESSAGES = 3


def board(project, user):
    """The project's messages as the person sees them (the one check),
    with comment counts"""
    return (
        Item.objects
        .visible_to(user)
        .filter(project=project, kind=Kind.MESSAGE)
        .select_related("creator", "message__category")
        .annotate(comment_count=Count("comments"))
    )


def pinned_messages(messages):
    """The latest pinned first"""
    return messages.filter(message__pinned_at__isnull=False).order_by(
        "-message__pinned_at", "-pk"
    )


def latest_messages(messages):
    """The unpinned ones, newest first"""
    return messages.filter(message__pinned_at__isnull=True).order_by(
        "-created_at", "-pk"
    )


def front_messages(project, user):
    """The project page's messages: the pinned ones, then the latest, three
    in all unless more are pinned"""
    messages = board(project, user)
    pinned = list(pinned_messages(messages))
    rest = max(0, FRONT_MESSAGES - len(pinned))
    return pinned + list(latest_messages(messages)[:rest])


def root_counts(project, user):
    """What the root of the docs and files holds, for the project page:
    {"folders": n, "docs": n, "files": n}"""
    counts = dict(
        Item.objects
        .visible_to(user)
        .filter(
            project=project, parent=None, kind__in=[Kind.FOLDER, Kind.DOC, Kind.FILE]
        )
        .values_list("kind")
        .annotate(n=Count("pk"))
        .values_list("kind", "n")
    )
    return {
        "folders": counts.get(Kind.FOLDER, 0),
        "docs": counts.get(Kind.DOC, 0),
        "files": counts.get(Kind.FILE, 0),
    }
