from django.db import migrations


def delete_old_addresses(apps, schema_editor):
    """Old addresses of people whose address changed: ``verify_email()``
    only made them not primary, so they still logged in by code and
    couldn't be given to somebody else"""
    User = apps.get_model("accounts", "User")
    EmailAddress = apps.get_model("account", "EmailAddress")
    for user in User.objects.all():
        EmailAddress.objects.filter(user=user).exclude(
            email__iexact=user.email
        ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0007_verified_email_addresses"),
    ]

    operations = [migrations.RunPython(delete_old_addresses, migrations.RunPython.noop)]
