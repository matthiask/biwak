from django.db import migrations, models


def give_marks(apps, schema_editor):
    """Everybody there already gets a mark, as if created in the order of
    their IDs: the one fewest people of the organization who haven't left
    have"""
    from biwak.accounts.marks import fewest_used

    User = apps.get_model("accounts", "User")
    counts = {}
    for user in User.objects.filter(mark="").order_by("pk"):
        used = counts.setdefault(user.organization_id, {})
        user.mark = fewest_used(used)
        user.save(update_fields=["mark"])
        if user.is_active or user.left_at is None:
            used[user.mark] = used.get(user.mark, 0) + 1


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0022_left_in_basecamp"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="mark",
            field=models.CharField(blank=True, max_length=30, verbose_name="mark"),
        ),
        migrations.RunPython(give_marks, migrations.RunPython.noop),
    ]
