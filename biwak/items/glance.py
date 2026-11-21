"""Seeing more without opening everything (specs/glance.md): the counts
behind the indicators on to-do rows and the numbers on the project page"""

from django.db.models import Count, F, Q
from django.db.models.functions import Coalesce

from biwak.items.models import Item, Kind, Status


# The detail models with a text that may have a task list (``Checklist``)
CHECKLIST_DETAILS = ["todo", "message", "doc", "upload"]


def with_signals(todos):
    """To-dos annotated with ``comment_count`` and ``attachment_count``:
    one query for all rows, never one per row"""
    return todos.annotate(
        comment_count=Count("comments", distinct=True),
        attachment_count=Count("attachments", distinct=True),
    )


def with_checklist(items):
    """Items annotated with ``checklist_done`` and ``checklist_total`` of
    their text (specs/editor.md), 0 for kinds without a task list: stored
    with the texts, read in the same query"""
    return items.annotate(
        checklist_done=Coalesce(
            *(F(f"{name}__checklist_done") for name in CHECKLIST_DETAILS), 0
        ),
        checklist_total=Coalesce(
            *(F(f"{name}__checklist_total") for name in CHECKLIST_DETAILS), 0
        ),
    )


def list_counts(user, lists, today):
    """``{list pk: (open, overdue)}`` of the open, not trashed to-dos of the
    given lists that ``user`` sees: one query"""
    pks = [item.pk for item in lists]
    rows = (
        Item.objects
        .visible_to(user)
        .filter(
            parent__in=pks,
            kind=Kind.TODO,
            todo__completed_at__isnull=True,
        )
        .exclude(status=Status.TRASHED)
        .values("parent")
        .annotate(
            open=Count("pk"),
            overdue=Count("pk", filter=Q(todo__due_on__lt=today)),
        )
    )
    return {row["parent"]: (row["open"], row["overdue"]) for row in rows}


def peek_comments(item, limit=3):
    """The latest ``limit`` comments, newest first"""
    return list(
        item.comments.select_related("author").order_by("-created_at", "-pk")[:limit]
    )
