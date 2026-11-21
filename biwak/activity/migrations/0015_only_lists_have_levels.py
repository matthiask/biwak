"""Subscribing is the switch (specs/ui-round-6.md, part C): items other than
lists have no notification level anymore. Their overrides go; no users yet,
so nothing to tell anybody."""

from django.db import migrations


def forward(apps, schema_editor):
    LevelOverride = apps.get_model("activity", "LevelOverride")
    LevelOverride.objects.filter(item__isnull=False).exclude(item__kind="list").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("activity", "0014_unassigned_action"),
        ("items", "0010_assignment"),
    ]

    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
