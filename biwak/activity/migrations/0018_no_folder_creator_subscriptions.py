from django.db import migrations
from django.db.models import F


def forwards(apps, schema_editor):
    """Creating a folder no longer subscribes its creator (decided
    2026-11-22, specs/notifications.md): the automatic subscriptions of
    folders' creators go. A creator who subscribed themselves later can't
    be told apart; there are no users yet."""
    Subscription = apps.get_model("activity", "Subscription")
    Subscription.objects.filter(
        item__kind="folder", user=F("item__creator"), added_by=None
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("activity", "0017_alter_event_action"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
