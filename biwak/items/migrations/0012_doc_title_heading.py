from django.db import migrations


def prefix_headings(apps, schema_editor):
    """A doc's title is the first line of its text (specs/doc-titles.md,
    decided 2026-11-21): docs whose first line isn't their title already get
    ``# <title>`` and an empty line in front. Their versions stay as they
    are; the live state follows the content (``live.ensure_state()``)."""
    from biwak.files.titles import doc_title, with_heading

    Doc = apps.get_model("items", "Doc")
    for doc in Doc.objects.select_related("item").iterator():
        if doc_title(doc.content) != doc.item.title:
            doc.content = with_heading(doc.item.title, doc.content)
            doc.save(update_fields=["content"])


class Migration(migrations.Migration):
    dependencies = [("items", "0011_archived_lists_only")]

    operations = [migrations.RunPython(prefix_headings, migrations.RunPython.noop)]
