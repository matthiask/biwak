"""Takes people removed from a project or deactivated off its open to-dos,
as ``unassign_dropped()`` does from now on (decided 2026-11-21,
specs/todos.md). Completed to-dos keep them. Deactivated means the audit
log has ``is_active`` cleared: people the importer created inactive and
nobody activated yet keep the import's assignments (specs/activation.md).
No events: there are no real users yet (2026-11-21), and an event needs
an actor."""

from django.db import migrations
from django.db.models import Exists, OuterRef


DEACTIVATED = """
SELECT DISTINCT (row_data -> 'id')::bigint
FROM audit_logged_actions
WHERE table_name = 'accounts_user'
AND action = 'U'
AND changed_fields -> 'is_active' = 'f'
"""


def drop_lost_assignees(apps, schema_editor):
    Assignment = apps.get_model("items", "Assignment")
    Membership = apps.get_model("projects", "Membership")
    User = apps.get_model("accounts", "User")
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(DEACTIVATED)
        deactivated = [row[0] for row in cursor.fetchall()]
    open_ = Assignment.objects.filter(todo__completed_at__isnull=True)
    # Removed from the project (assigning makes people members)
    open_.exclude(
        Exists(
            Membership.objects.filter(
                project_id=OuterRef("todo__item__project_id"),
                user_id=OuterRef("user_id"),
            )
        )
    ).delete()
    # Deactivated, and still inactive
    open_.filter(
        user__in=User.objects.filter(pk__in=deactivated, is_active=False)
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0017_audited_authenticators"),
        ("audit", "0002_audited_tables"),
        ("items", "0014_drafts"),
        ("projects", "0004_files_ordering"),
    ]

    operations = [
        migrations.RunPython(drop_lost_assignees, migrations.RunPython.noop),
    ]
