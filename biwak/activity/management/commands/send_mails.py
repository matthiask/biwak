from django.core.management import BaseCommand

from biwak.accounts.middleware import set_user_name
from biwak.activity.mails import send_mails


class Command(BaseCommand):
    help = (
        "Sends the notification mails which are due (specs/notifications.md):"
        " per person and item 2 minutes after the newest change, digests at"
        " 07:00. Run every minute by cron."
    )

    def handle(self, **options):
        set_user_name("Send mails")
        count = send_mails()
        if options["verbosity"] > 1:
            self.stdout.write(f"{count} mails sent.")
