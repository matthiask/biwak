from django.db import migrations, models

from biwak.audit.operations import audit_tables


class Migration(migrations.Migration):
    """Docs edited live (specs/collaboration.md): the locks go, a doc can
    be read-only"""

    dependencies = [
        ("items", "0005_merged_choices"),
        # Audited the lock columns' table without them
        ("files", "0004_audited_file_versions"),
    ]

    operations = [
        migrations.RemoveField(model_name="doc", name="locked_at"),
        migrations.RemoveField(model_name="doc", name="locked_by"),
        migrations.AddField(
            model_name="doc",
            name="read_only",
            field=models.BooleanField(default=False, verbose_name="read-only"),
        ),
        audit_tables("items_doc"),
    ]
