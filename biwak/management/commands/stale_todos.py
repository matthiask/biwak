from django.core.management import BaseCommand

from biwak.items import stale


class Command(BaseCommand):
    help = (
        "Lists the stale to-dos per project, how many are warned and how many"
        " the next run would warn, changing nothing (specs/stale-todos.md);"
        " run it before turning STALE_TODOS on"
    )

    def handle(self, **options):
        report = stale.report()
        if not report:
            self.stdout.write("No stale to-dos.")
            return
        totals = [0, 0, 0]
        for project, counts in sorted(report.items(), key=lambda p: p[0].name):
            self.stdout.write(
                f"{project.name} (#{project.pk}): {counts['stale']} stale,"
                f" {counts['warned']} warned, {counts['to_warn']} to warn"
            )
            for n, key in enumerate(["stale", "warned", "to_warn"]):
                totals[n] += counts[key]
        self.stdout.write(
            f"In all: {totals[0]} stale, {totals[1]} warned, {totals[2]} to warn"
            + ("" if stale.is_on() else " (STALE_TODOS is off)")
        )
