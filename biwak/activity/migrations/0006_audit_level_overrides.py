from django.db import migrations

from biwak.audit.operations import audit_tables


class Migration(migrations.Migration):
    """The audit trigger on the levels people set; not on mentions and
    notifications, which follow from texts and events"""

    dependencies = [
        ("audit", "0002_audited_tables"),
        ("activity", "0005_mentions_levels_notifications"),
    ]

    operations = [audit_tables("activity_leveloverride")]
