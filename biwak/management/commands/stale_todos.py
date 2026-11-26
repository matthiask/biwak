from django.core.management import BaseCommand
from django.utils.formats import date_format

from biwak.items import stale


class Command(BaseCommand):
    help = (
        "Lists the stale to-dos per project, the oldest first, with why"
        " they're stale and what happens to them: warned (and the day they're"
        " marked obsolete), warned by the next run, or later (over the day's"
        " limit). Changes nothing (specs/stale-todos.md); run it before"
        " turning STALE_TODOS on."
    )

    def add_arguments(self, parser):
        parser.add_argument("--project", type=int, help="Only this project (its ID).")
        parser.add_argument(
            "--summary", action="store_true", help="Only the counts per project."
        )

    def handle(self, *, project=None, summary=False, **options):
        report = stale.report(project=project)
        if not report:
            self.stdout.write("No stale to-dos.")
            return
        totals = {"stale": 0, "warned": 0, "to_warn": 0}
        for proj, entry in sorted(report.items(), key=lambda p: p[0].name):
            self.stdout.write(f"{proj.name} (#{proj.pk}): {self.counts(entry)}")
            for key in totals:
                totals[key] += entry[key]
            if not summary:
                for todo in entry["todos"]:
                    self.stdout.write(f"  {self.line(todo['item'], todo['state'])}")
        self.stdout.write(
            f"In all: {self.counts(totals)}"
            + ("" if stale.is_on() else " (STALE_TODOS is off)")
        )

    def counts(self, entry):
        return (
            f"{entry['stale']} stale, {entry['warned']} warned,"
            f" {entry['to_warn']} to warn"
        )

    def line(self, item, state):
        """ "#12 Title (List / Group): Nothing since 3 May 2026; to warn" """
        group = item.todo.group
        where = f"{item.parent.title} / {group.title}" if group else item.parent.title
        if state == "warned":
            day = date_format(stale.obsolete_on(item.todo), "DATE_FORMAT")
            what = f"warned, marked obsolete on {day}"
        elif state == "to_warn":
            what = "to warn"
        else:
            what = f"later (over {stale.WARNINGS_PER_PROJECT} a day)"
        return f"#{item.pk} {item.title} ({where}): {stale.reason_text(item)}; {what}"
