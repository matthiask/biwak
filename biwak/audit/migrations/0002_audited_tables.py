from django.db import migrations

from biwak.audit.operations import audit_tables


class Migration(migrations.Migration):
    """The audit trigger on the tables people change (SPEC.md); not on
    events and subscriptions, which are a log themselves or change too
    often to matter"""

    dependencies = [
        ("audit", "0001_initial"),
        ("accounts", "0002_apitoken"),
        ("projects", "0001_initial"),
        ("items", "0001_initial"),
    ]

    operations = [
        audit_tables(
            "projects_project",
            "projects_membership",
            "items_item",
            "items_todolist",
            "items_group",
            "items_todo",
            "items_todo_assignees",
            "items_message",
            "items_folder",
            "items_doc",
            "items_comment",
        ),
        audit_tables("accounts_user", exclude=["last_login"]),
        audit_tables("accounts_apitoken", exclude=["last_used_at", "expires_at"]),
    ]
