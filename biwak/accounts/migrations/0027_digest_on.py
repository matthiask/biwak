from django.db import migrations, models

from biwak.audit.operations import audit_tables


class Migration(migrations.Migration):
    """The day of the last daily digest (specs/notifications.md, "Digest"),
    left out of the audit log like ``last_login``: it changes every day"""

    dependencies = [
        ("accounts", "0026_push_device_name"),
        ("audit", "0002_audited_tables"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="digest_on",
            field=models.DateField(
                blank=True, editable=False, null=True, verbose_name="last digest"
            ),
        ),
        migrations.RunSQL(
            audit_tables("accounts_user", exclude=["last_login", "digest_on"]).sql,
            reverse_sql=audit_tables("accounts_user", exclude=["last_login"]).sql,
        ),
    ]
