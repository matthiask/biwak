"""The level "nothing" is gone (specs/notifications.md, decided
2026-11-22): overrides on it are on "only what concerns me" now."""

from django.db import migrations, models


def forward(apps, schema_editor):
    apps.get_model("activity", "LevelOverride").objects.filter(level="nothing").update(
        level="concerns_me"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("activity", "0015_only_lists_have_levels"),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="leveloverride",
            name="level",
            field=models.CharField(
                choices=[
                    ("everything", "Everything"),
                    ("concerns_me", "Only what concerns me"),
                ],
                max_length=20,
                verbose_name="notifications",
            ),
        ),
    ]
