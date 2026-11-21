from django.db import migrations

from biwak.audit.operations import audit_tables


class Migration(migrations.Migration):
    """Creating, renaming and merging organizations is in the audit log
    (specs/organizations.md)"""

    dependencies = [
        ("audit", "0001_initial"),
        ("organizations", "0001_initial"),
    ]

    operations = [audit_tables("organizations_organization")]
