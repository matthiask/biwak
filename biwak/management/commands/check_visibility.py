from django.core.mail import mail_admins
from django.core.management.base import BaseCommand

from biwak.items import visibility


class Command(BaseCommand):
    help = (
        "Compares the stored visibility of all items with the tree"
        " (specs/access.md); mails admins about differences with --mail"
    )

    def add_arguments(self, parser):
        parser.add_argument("--mail", action="store_true")

    def handle(self, *args, **options):
        differences = visibility.check()
        if not differences:
            self.stdout.write("No differences.")
            return
        lines = [
            f"Item {item.pk} ({item.kind}, project {item.project_id}):"
            f" stored {stored}, expected {expected}"
            for item, stored, expected in differences
        ]
        self.stdout.write("\n".join(lines))
        if options["mail"]:
            mail_admins(
                f"{len(differences)} items with wrong visibility", "\n".join(lines)
            )
