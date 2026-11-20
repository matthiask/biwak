from django.db import migrations

from biwak.audit.operations import audit_tables


class Migration(migrations.Migration):
    """The audit trigger on what people change; not on occurrences (a log
    of what happened), not on when a question is asked next (the schedule
    moves it)"""

    dependencies = [
        ("audit", "0002_audited_tables"),
        ("checkins", "0001_initial"),
    ]

    operations = [
        audit_tables("checkins_question", exclude=["next_at"]),
        audit_tables(
            "checkins_question_people",
            "checkins_answer",
            "checkins_skip",
            "checkins_questionmail",
        ),
    ]
