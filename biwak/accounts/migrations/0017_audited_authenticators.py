from django.db import migrations

from biwak.audit.operations import audit_tables


class Migration(migrations.Migration):
    """allauth's authenticators (passkeys, authenticator apps) in the audit
    log (specs/two-factor.md): who added, removed or reset one. Without
    ``data``, which holds the app's secret and the passkey's key, and
    without ``last_used_at``, which changes with every sign-in."""

    dependencies = [
        ("accounts", "0016_invited"),
        ("audit", "0002_audited_tables"),
        ("mfa", "0003_authenticator_type_uniq"),
    ]

    operations = [
        audit_tables("mfa_authenticator", exclude=["data", "last_used_at"]),
    ]
