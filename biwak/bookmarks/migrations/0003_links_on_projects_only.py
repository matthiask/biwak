from django.db import migrations, models


def delete_links_on_items(apps, schema_editor):
    """Links on items go (specs/feed.md, decided 2026-11-21)"""
    apps.get_model("bookmarks", "Link").objects.filter(item__isnull=False).delete()


class Migration(migrations.Migration):
    dependencies = [("bookmarks", "0002_audited_tables")]

    operations = [
        migrations.RunPython(delete_links_on_items, migrations.RunPython.noop),
        migrations.RemoveIndex(
            model_name="link", name="bookmarks_l_project_cd0805_idx"
        ),
        migrations.RemoveField(model_name="link", name="item"),
        migrations.AddIndex(
            model_name="link",
            index=models.Index(
                fields=["project", "position"], name="bookmarks_l_project_e3dfa3_idx"
            ),
        ),
        migrations.AlterField(
            model_name="link",
            name="visible_to_clients",
            field=models.BooleanField(
                default=False,
                help_text="Internal unless you switch it.",
                verbose_name="visible to clients",
            ),
        ),
    ]
