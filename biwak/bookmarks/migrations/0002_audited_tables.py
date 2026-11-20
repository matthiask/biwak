from django.db import migrations

from biwak.audit.operations import audit_tables


class Migration(migrations.Migration):
    dependencies = [
        ("audit", "0002_audited_tables"),
        ("bookmarks", "0001_bookmarks_and_links"),
    ]

    operations = [audit_tables("bookmarks_bookmark", "bookmarks_link")]
