"""Docs with CR LF line breaks (a form's, before forms sent LF only):
LF in the text, and a fresh live state from it, since the live editor
counts a line break as one character where Yjs counted two and every edit
landed off by one per line break before it. The text as it is now (with
what was typed and not merged yet) is kept; open editors resync."""

from django.db import migrations
from django.utils import timezone


def line_breaks(apps, schema_editor):
    from biwak.collab import ytext
    from biwak.text import line_breaks

    Doc = apps.get_model("items", "Doc")
    LiveState = apps.get_model("collab", "LiveState")
    LiveUpdate = apps.get_model("collab", "LiveUpdate")
    for doc in Doc.objects.all():
        state = LiveState.objects.filter(doc=doc).first()
        updates = list(
            LiveUpdate.objects
            .filter(doc=doc)
            .order_by("pk")
            .values_list("data", flat=True)
        )
        live = ytext.text(ytext.ydoc(state.state, updates)) if state else None
        if "\r" not in doc.content and (live is None or "\r" not in live):
            continue
        text = line_breaks(live if live is not None else doc.content)
        doc.content = text
        doc.save(update_fields=["content"])
        if state is not None:
            LiveUpdate.objects.filter(doc=doc).delete()
            state.delete()
            LiveState.objects.create(
                doc=doc, state=ytext.initial_state(text), created_at=timezone.now()
            )


class Migration(migrations.Migration):
    dependencies = [
        ("collab", "0002_live_state_created_at"),
        ("items", "0011_archived_lists_only"),
    ]

    operations = [migrations.RunPython(line_breaks, migrations.RunPython.noop)]
