from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("files", "0004_audited_file_versions"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="attachment",
            index=models.Index(fields=["file"], name="files_attachment_file"),
        ),
    ]
