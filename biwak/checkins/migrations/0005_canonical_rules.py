"""Rules are stored in canonical form (specs/todos.md, decided 2026-11-21):
the stored to-do recurrences and question rules once. The meaning stays
the same, so ``next_at`` stays and no event is recorded; rules which
aren't valid (any more) stay as they are."""

from django.db import migrations


def canonical_rules(apps, schema_editor):
    from biwak import schedules

    for model, field in [
        (apps.get_model("items", "Todo"), "recurrence"),
        (apps.get_model("checkins", "Question"), "rule"),
    ]:
        stored = model.objects.exclude(**{field: ""}).values_list("pk", field)
        for pk, rule in stored:
            try:
                canonical = schedules.validate(rule)
            except schedules.InvalidRule:
                continue
            if canonical != rule:
                model.objects.filter(pk=pk).update(**{field: canonical})


class Migration(migrations.Migration):
    dependencies = [
        ("checkins", "0004_no_skip"),
        ("items", "0006_archived_when_trashed"),
    ]

    operations = [
        migrations.RunPython(canonical_rules, migrations.RunPython.noop),
    ]
