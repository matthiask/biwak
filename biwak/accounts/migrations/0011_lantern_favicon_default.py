from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0010_merge_main_collaboration")]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="lantern_in_favicon",
            field=models.BooleanField(
                default=True, verbose_name="unread notifications on the tab's icon"
            ),
        ),
    ]
