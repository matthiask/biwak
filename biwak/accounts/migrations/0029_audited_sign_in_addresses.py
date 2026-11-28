from django.db import migrations

from biwak.audit.operations import audit_tables


class Migration(migrations.Migration):
    """allauth's sign-in addresses and linked Google and Microsoft accounts
    in the audit log (specs/auditing.md, decided 2026-11-28): who linked or
    removed one, which address became the primary one. Without
    ``extra_data`` (the provider's profile, written again at every
    sign-in) and ``last_login``; the tokens' table stays out."""

    dependencies = [
        ("accounts", "0028_weekly_todos_removed"),
        ("audit", "0002_audited_tables"),
        ("account", "0009_emailaddress_unique_primary_email"),
        ("socialaccount", "0006_alter_socialaccount_extra_data"),
    ]

    operations = [
        audit_tables("account_emailaddress"),
        audit_tables(
            "socialaccount_socialaccount", exclude=["extra_data", "last_login"]
        ),
    ]
