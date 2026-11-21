import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

from biwak.audit.operations import audit_tables


TABLE = "items_todo_assignees"


def add_columns(apps, schema_editor):
    """The automatic many-to-many table gets the through model's columns and
    its unique constraint gets the model's name; the rows stay (without an
    assigner)"""
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, TABLE)
        for name, info in constraints.items():
            if (
                info["unique"]
                and not info["primary_key"]
                and info["columns"] == ["todo_id", "user_id"]
            ):
                cursor.execute(f'ALTER TABLE {TABLE} DROP CONSTRAINT "{name}"')
        cursor.execute(
            f"ALTER TABLE {TABLE}"
            " ADD COLUMN assigned_by_id bigint NULL"
            " REFERENCES accounts_user (id) DEFERRABLE INITIALLY DEFERRED,"
            " ADD COLUMN assigned_at timestamptz NOT NULL DEFAULT now(),"
            " ADD CONSTRAINT items_assignment_todo_user_uniq UNIQUE (todo_id, user_id)"
        )
        cursor.execute(f"ALTER TABLE {TABLE} ALTER COLUMN assigned_at DROP DEFAULT")
        cursor.execute(
            f"CREATE INDEX items_todo_assignees_assigned_by_id ON {TABLE} (assigned_by_id)"
        )


def drop_columns(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            f"ALTER TABLE {TABLE} DROP CONSTRAINT items_assignment_todo_user_uniq,"
            " DROP COLUMN assigned_by_id, DROP COLUMN assigned_at"
        )
        cursor.execute(f"ALTER TABLE {TABLE} ADD UNIQUE (todo_id, user_id)")


class Migration(migrations.Migration):
    """``Todo.assignees`` gets a through model on the same table
    (specs/ui-round-5.md, section 4); no backfill of who assigned."""

    dependencies = [
        ("items", "0009_merge_tick_editing"),
        ("audit", "0002_audited_tables"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(add_columns, drop_columns)],
            state_operations=[
                migrations.CreateModel(
                    name="Assignment",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                auto_created=True,
                                primary_key=True,
                                serialize=False,
                                verbose_name="ID",
                            ),
                        ),
                        (
                            "assigned_at",
                            models.DateTimeField(
                                default=django.utils.timezone.now,
                                verbose_name="assigned at",
                            ),
                        ),
                        (
                            "assigned_by",
                            models.ForeignKey(
                                blank=True,
                                null=True,
                                on_delete=django.db.models.deletion.SET_NULL,
                                related_name="+",
                                to=settings.AUTH_USER_MODEL,
                                verbose_name="assigned by",
                            ),
                        ),
                        (
                            "todo",
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.CASCADE,
                                to="items.todo",
                            ),
                        ),
                        (
                            "user",
                            models.ForeignKey(
                                on_delete=django.db.models.deletion.CASCADE,
                                to=settings.AUTH_USER_MODEL,
                            ),
                        ),
                    ],
                    options={
                        "db_table": "items_todo_assignees",
                        "constraints": [
                            models.UniqueConstraint(
                                fields=("todo", "user"),
                                name="items_assignment_todo_user_uniq",
                            )
                        ],
                    },
                ),
                migrations.AlterField(
                    model_name="todo",
                    name="assignees",
                    field=models.ManyToManyField(
                        blank=True,
                        related_name="assigned_todos",
                        through="items.Assignment",
                        through_fields=("todo", "user"),
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="assignees",
                    ),
                ),
            ],
        ),
        audit_tables(TABLE),
    ]
