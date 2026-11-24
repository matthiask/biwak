"""Message categories in the audit log (specs/auditing.md, decided
2026-11-24): renaming or deleting one left no trace"""

from django.db import migrations

from biwak.audit.operations import audit_tables


class Migration(migrations.Migration):
    dependencies = [
        ("items", "0021_recurrence_moves"),
        ("audit", "0002_audited_tables"),
    ]

    operations = [audit_tables("items_messagecategory")]
