from django.db import migrations


def own_organization(apps, schema_editor):
    """The own organization always exists ("Our
    organization" if none is marked), and staff without an organization go
    into it: staff without one are partners now (decided 2026-11-21), and
    nobody loses access by the migration"""
    Organization = apps.get_model("organizations", "Organization")
    User = apps.get_model("accounts", "User")
    own = Organization.objects.filter(is_own=True).first()
    if own is None:
        own = Organization.objects.filter(
            name__iexact="Our organization"
        ).first() or Organization(name="Our organization")
        own.is_own = True
        own.save()
    User.objects.filter(is_client=False, organization=None).update(organization=own)


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0002_audited_tables"),
        ("accounts", "0012_organizations"),
    ]

    operations = [migrations.RunPython(own_organization, migrations.RunPython.noop)]
