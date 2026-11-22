"""The live docs' shared state becomes the rich editor's document (a
Y.XmlFragment, specs/rich-editor.md) instead of the Markdown in a Y.Text:
what was typed and not merged yet goes into the text, and the states are
deleted; the first editor makes a new one from the text, a new history,
so copies kept in browsers (specs/connection.md) aren't merged into it.
(No users yet, decided 2026-11-22: nothing more is needed.)"""

from django.db import migrations
from pycrdt import Doc, Text


def _text(state, updates):
    doc = Doc()
    for update in [state, *updates]:
        if update:
            doc.apply_update(bytes(update))
    return str(doc.get("content", type=Text))


def rebuild(apps, schema_editor):
    Doc_ = apps.get_model("items", "Doc")
    LiveState = apps.get_model("collab", "LiveState")
    LiveUpdate = apps.get_model("collab", "LiveUpdate")
    for state in LiveState.objects.all():
        updates = list(
            LiveUpdate.objects
            .filter(doc_id=state.doc_id)
            .order_by("pk")
            .values_list("data", flat=True)
        )
        if updates:
            text = _text(state.state, updates)
            Doc_.objects.filter(pk=state.doc_id).update(content=text)
    LiveUpdate.objects.all().delete()
    LiveState.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("collab", "0003_line_breaks")]

    operations = [migrations.RunPython(rebuild, migrations.RunPython.noop)]
