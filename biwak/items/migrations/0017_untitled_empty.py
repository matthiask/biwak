"""Docs without a title store it empty; "Untitled" is shown in the reader's
language (specs/files.md, decided 2026-11-22)."""

from django.db import migrations, models


def forward(apps, schema_editor):
    apps.get_model("items", "Item").objects.filter(kind="doc", title="Untitled").update(
        title=""
    )
    apps.get_model("items", "DocVersion").objects.filter(title="Untitled").update(
        title=""
    )


class Migration(migrations.Migration):
    dependencies = [
        ("items", "0016_folder_color"),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="docversion",
            name="title",
            field=models.CharField(blank=True, max_length=500, verbose_name="title"),
        ),
        migrations.AlterField(
            model_name="item",
            name="title",
            field=models.CharField(blank=True, max_length=500, verbose_name="title"),
        ),
    ]
