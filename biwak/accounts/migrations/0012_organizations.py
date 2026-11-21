import django.db.models.deletion
from django.db import migrations, models


def names(texts):
    """``{text: name}``: texts differing only in case and spaces get one
    name, the first one's spelling with single spaces; empty ones none"""
    first = {}
    result = {}
    for text in texts:
        name = " ".join(text.split())
        if name:
            result[text] = first.setdefault(name.lower(), name)
    return result


def to_organizations(apps, schema_editor):
    """The texts become organizations (``names()``), the oldest person's
    spelling wins"""
    User = apps.get_model("accounts", "User")
    Organization = apps.get_model("organizations", "Organization")
    people = list(User.objects.exclude(organization_text="").order_by("pk"))
    organizations = {}
    for text, name in names(user.organization_text for user in people).items():
        if name not in organizations:
            organizations[name] = Organization.objects.create(name=name)
        for user in people:
            if user.organization_text == text:
                user.organization = organizations[name]
                user.save(update_fields=["organization"])


def to_texts(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    for user in User.objects.exclude(organization=None).select_related("organization"):
        user.organization_text = user.organization.name
        user.save(update_fields=["organization_text"])


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0011_lantern_favicon_default"),
        ("organizations", "0001_initial"),
    ]

    operations = [
        migrations.RenameField("user", "organization", "organization_text"),
        migrations.AddField(
            model_name="user",
            name="organization",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="people",
                to="organizations.organization",
                verbose_name="organization",
            ),
        ),
        migrations.RunPython(to_organizations, to_texts),
        migrations.RemoveField("user", "organization_text"),
    ]
