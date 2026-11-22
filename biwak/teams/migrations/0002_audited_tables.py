from django.db import migrations

from biwak.audit.operations import audit_tables


class Migration(migrations.Migration):
    """Creating, renaming and changing teams is in the audit log
    (specs/teams.md)"""

    dependencies = [
        ("audit", "0001_initial"),
        ("teams", "0001_initial"),
    ]

    operations = [audit_tables("teams_team", "teams_teammember")]
