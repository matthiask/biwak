"""The message board's "Latest update" order (specs/files.md, "The
message board", decided 2026-11-22): the later of posting and the latest
comment, stored on the message"""

import django.utils.timezone
from django.db import migrations, models

from biwak.audit.operations import audit_tables


# ``operations.MESSAGE_ACTIVITY_SQL`` as it was, for all messages
FILL = """
UPDATE items_message m SET last_activity_at = GREATEST(
  i.created_at,
  (SELECT max(c.created_at) FROM items_comment c WHERE c.item_id = m.item_id)
)
FROM items_item i
WHERE i.id = m.item_id
"""


class Migration(migrations.Migration):
    dependencies = [
        ("items", "0017_untitled_empty"),
        ("audit", "0002_audited_tables"),
    ]

    operations = [
        migrations.AddField(
            model_name="message",
            name="last_activity_at",
            field=models.DateTimeField(
                default=django.utils.timezone.now,
                editable=False,
                verbose_name="last activity at",
            ),
        ),
        migrations.RunSQL(FILL, migrations.RunSQL.noop),
        # The column changes with every comment, which the log has anyway
        audit_tables("items_message", exclude=["last_activity_at"]),
    ]
