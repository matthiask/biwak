"""The rule of a recurring to-do moves to the next one (specs/todos.md,
decided 2026-11-23): completed to-dos which have a next one keep none"""

from django.db import migrations
from django.db.models import Exists, OuterRef


def forwards(apps, schema_editor):
    Todo = apps.get_model("items", "Todo")
    # A next one in the trash doesn't count, as when completing
    following = Todo.objects.filter(previous=OuterRef("item")).exclude(
        item__status="trashed"
    )
    Todo.objects.filter(completed_at__isnull=False).exclude(recurrence="").filter(
        Exists(following)
    ).update(recurrence="", recurrence_ends_on=None, recurrence_count=None)


class Migration(migrations.Migration):
    dependencies = [("items", "0020_group_color")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
