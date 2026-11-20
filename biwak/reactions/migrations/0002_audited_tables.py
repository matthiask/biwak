from django.db import migrations

from biwak.audit.operations import audit_tables


class Migration(migrations.Migration):
    dependencies = [
        ("audit", "0002_audited_tables"),
        ("reactions", "0001_initial"),
    ]

    operations = [audit_tables("reactions_reaction")]
