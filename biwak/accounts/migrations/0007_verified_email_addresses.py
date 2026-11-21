from django.db import migrations


def verify(apps, schema_editor):
    """Everybody's address as allauth's verified primary address (see
    ``verify_email()``); before, nobody had one, so adding a passkey after
    the first five minutes answered 403"""
    User = apps.get_model("accounts", "User")
    EmailAddress = apps.get_model("account", "EmailAddress")
    for user in User.objects.all():
        EmailAddress.objects.filter(user=user).exclude(email__iexact=user.email).update(
            primary=False
        )
        EmailAddress.objects.update_or_create(
            user=user,
            email__iexact=user.email,
            defaults={"email": user.email, "verified": True, "primary": True},
        )


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0006_user_passkey_offer_done"),
        ("account", "0009_emailaddress_unique_primary_email"),
    ]

    operations = [migrations.RunPython(verify, migrations.RunPython.noop)]
