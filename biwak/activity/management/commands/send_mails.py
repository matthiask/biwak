from django.core.management import BaseCommand

from biwak.accounts.middleware import set_user_name
from biwak.activity.mails import send_mails
from biwak.checkins import operations as checkins


class Command(BaseCommand):
    help = (
        "Sends the notification mails which are due (specs/notifications.md):"
        " per person and item 2 minutes after the newest change, digests at"
        " 07:00; and what check-ins do (specs/checkins.md): asking the"
        " questions due, reminding, the summaries of the answers. Run every"
        " minute by cron."
    )

    def handle(self, **options):
        set_user_name("Send mails")
        count = send_mails()
        done = checkins.run()
        if options["verbosity"] > 1:
            self.stdout.write(f"{count} mails sent.")
            self.stdout.write(
                "Check-ins: {asked} asked, {reminded} reminded, "
                "{summarized} summarized.".format(**done)
            )
