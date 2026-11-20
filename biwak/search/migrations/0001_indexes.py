from django.db import migrations


# Table, column: every text of every kind (specs/search.md). Expression
# indexes, so there is nothing to keep up to date: the index follows every
# write, whoever makes it. ``biwak.search.queries.vector()`` has to use the
# same expression.
TEXTS = [
    ("items_item", "title"),
    ("items_todolist", "description"),
    ("items_todo", "notes"),
    ("items_message", "content"),
    ("items_doc", "content"),
    ("items_upload", "description"),
    ("checkins_answer", "content"),
    ("items_comment", "content"),
]


class Migration(migrations.Migration):
    dependencies = [
        ("items", "0005_merged_choices"),
        ("checkins", "0004_no_skip"),
    ]

    operations = [
        migrations.RunSQL(
            f"CREATE INDEX search_{table}_{column} ON {table}"
            f" USING gin (to_tsvector('simple', {column}))",
            reverse_sql=f"DROP INDEX search_{table}_{column}",
        )
        for table, column in TEXTS
    ]
