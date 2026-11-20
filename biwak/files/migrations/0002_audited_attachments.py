from django.db import migrations

from biwak.audit.operations import audit_tables


class Migration(migrations.Migration):
    """The audit trigger on attachments (AGENTS.md)"""

    dependencies = [
        ("audit", "0002_audited_tables"),
        ("files", "0001_attachments"),
    ]

    operations = [audit_tables("files_attachment")]
