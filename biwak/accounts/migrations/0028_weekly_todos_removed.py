from django.db import migrations

from biwak.audit.operations import audit_tables


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0027_weekly_todos"),
        ("audit", "0002_audited_tables"),
    ]

    operations = [
        migrations.RemoveField(model_name="user", name="weekly_todos"),
        migrations.RemoveField(model_name="user", name="weekly_todos_on"),
        # The trigger again without the column it excluded (specs/stale-todos.md)
        audit_tables("accounts_user", exclude=["last_login"]),
    ]
