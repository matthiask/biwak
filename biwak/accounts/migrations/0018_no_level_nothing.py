"""The level "nothing" is gone (specs/notifications.md, decided
2026-11-22): users on it are on "only what concerns me" now."""

from django.db import migrations, models


def forward(apps, schema_editor):
    apps.get_model("accounts", "User").objects.filter(
        notification_level="nothing"
    ).update(notification_level="concerns_me")


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0017_audited_authenticators"),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="user",
            name="notification_level",
            field=models.CharField(
                choices=[
                    ("everything", "Everything"),
                    ("concerns_me", "Only what concerns me"),
                ],
                default="everything",
                max_length=20,
                verbose_name="notifications",
            ),
        ),
    ]
