from django.db import migrations

from biwak.audit.operations import audit_tables


class Migration(migrations.Migration):
    """The audit trigger on the files' tables (AGENTS.md); doc versions are
    a log themselves, categories change rarely"""

    dependencies = [
        ("audit", "0002_audited_tables"),
        ("files", "0003_file_versions"),
        ("items", "0003_files_stage_2"),
    ]

    operations = [
        audit_tables("files_fileversion", "items_upload"),
        # Locks are renewed every minute: not worth a row each
        audit_tables("items_doc", exclude=["locked_by_id", "locked_at"]),
    ]
