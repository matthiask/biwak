from django.db import migrations
from django.db.models import Q


def convert(apps, schema_editor):
    """Only lists are archived (specs/archiving.md, decided 2026-11-21):
    archived to-dos become completed ones, at their last change, other
    archived items active ones. What was trashed archived (``archived_when_trashed``)
    is the same, so restoring brings it back as it is now."""
    Item = apps.get_model("items", "Item")
    Todo = apps.get_model("items", "Todo")
    not_lists = ~Q(kind="list")
    archived = not_lists & (Q(status="archived") | Q(archived_when_trashed=True))
    # Items of all kinds can hold the old values, so to-dos go first
    todos = Item.objects.filter(archived, kind="todo")
    for item in todos.select_related("todo"):
        Todo.objects.filter(item=item, completed_at__isnull=True).update(
            completed_at=item.updated_at
        )
    Item.objects.filter(not_lists, status="archived").update(status="active")
    Item.objects.filter(not_lists, archived_when_trashed=True).update(
        archived_when_trashed=False
    )


class Migration(migrations.Migration):
    dependencies = [
        ("items", "0010_assignment"),
    ]

    operations = [
        migrations.RunPython(convert, migrations.RunPython.noop),
    ]
