"""Who wrote a message's latest comment, shown on the board in the "Latest
update" order (specs/files.md, "The message board", decided 2026-11-22)"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

from biwak.audit.operations import audit_tables


# ``operations.MESSAGE_ACTIVITY_SQL`` as it was, for all messages
FILL = """
UPDATE items_message m SET last_commenter_id = (
  SELECT c.author_id FROM items_comment c WHERE c.item_id = m.item_id
  ORDER BY c.created_at DESC, c.id DESC LIMIT 1
)
"""


class Migration(migrations.Migration):
    dependencies = [
        ("items", "0018_message_last_activity"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="message",
            name="last_commenter",
            field=models.ForeignKey(
                blank=True,
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
                verbose_name="last commenter",
            ),
        ),
        migrations.RunSQL(FILL, migrations.RunSQL.noop),
        # Changes with every comment, like ``last_activity_at``
        audit_tables(
            "items_message", exclude=["last_activity_at", "last_commenter_id"]
        ),
    ]
