"""Changes earlier import runs brought over from Basecamp were recorded in
the item creator's name; Basecamp never says who changed something
(decided 2026-11-28: a to-do's creator who had left months before
"edited" it). They get no person, noted as the import's, as the importer
records them now (``Importer._from_basecamp()``).

The import's events carry Basecamp's times, in milliseconds; Biwak's own
are in microseconds. Assignments at the to-do's creation stay with its
creator, as the importer still records them, and so do docs, whose
versions need an author."""

from django.db import migrations


ACTIONS = [
    "edited",
    "archived",
    "unarchived",
    "reopened",
    "visibility_changed",
    "assigned",
    "unassigned",
]


def forget_actors(apps, schema_editor):
    Event = apps.get_model("activity", "Event")
    ImportedObject = apps.get_model("importer", "ImportedObject")
    ContentType = apps.get_model("contenttypes", "ContentType")
    item_type = ContentType.objects.filter(app_label="items", model="item").first()
    if item_type is None:
        return
    imported = set(
        ImportedObject.objects.filter(content_type=item_type).values_list(
            "object_id", flat=True
        )
    )
    events = (
        Event.objects
        .filter(action__in=ACTIONS, actor__isnull=False, item__isnull=False)
        .exclude(item__kind="doc")
        .select_related("item")
    )
    changed = []
    for event in events.iterator():
        item = event.item
        if (
            event.created_at.microsecond % 1000
            or event.actor_id != item.creator_id
            or item.pk not in imported
            or (event.data or {}).get("imported")
        ):
            continue
        if (
            event.action in {"assigned", "unassigned"}
            and event.created_at == item.created_at
        ):
            continue
        event.actor = None
        event.data = {**(event.data or {}), "imported": "basecamp"}
        changed.append(event)
    Event.objects.bulk_update(changed, ["actor", "data"], batch_size=500)


class Migration(migrations.Migration):
    dependencies = [
        ("activity", "0024_stale_warnings"),
        ("importer", "0002_basecamp_state"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.RunPython(forget_actors, migrations.RunPython.noop, elidable=True),
    ]
