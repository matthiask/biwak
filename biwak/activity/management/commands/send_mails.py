import logging

from django.core.management import BaseCommand

from biwak.accounts.middleware import set_user_name
from biwak.activity.mails import send_mails
from biwak.checkins import operations as checkins
from biwak.outbox import sending as outbox


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Sends the notification mails which are due (specs/notifications.md):"
        " per person and item 2 minutes after the newest change, digests at"
        " 07:00; and what check-ins do (specs/checkins.md): asking the"
        " questions due, the summaries of the answers; and sending again what"
        " failed to go out (specs/mail-sending.md). Run every minute by cron."
    )

    def handle(self, **options):
        set_user_name("Send mails")
        # Each part on its own: one failing doesn't keep the other from
        # running
        try:
            count = send_mails()
        except Exception:
            logger.exception("Sending the notification mails failed")
        else:
            if options["verbosity"] > 1:
                self.stdout.write(f"{count} mails sent.")
        try:
            done = checkins.run()
        except Exception:
            logger.exception("Running the check-ins failed")
        else:
            if options["verbosity"] > 1:
                self.stdout.write(
                    "Check-ins: {asked} asked, {summarized} summarized.".format(**done)
                )
        try:
            retried = outbox.retry()
        except Exception:
            logger.exception("Sending the outbox again failed")
        else:
            if options["verbosity"] > 1 and retried:
                self.stdout.write(
                    "Outbox: "
                    + ", ".join(
                        f"{count} {result}" for result, count in retried.items()
                    )
                    + "."
                )
