import logging

from django.core.management import BaseCommand

from biwak.accounts.middleware import set_user_name
from biwak.activity import push
from biwak.activity.mails import send_mails
from biwak.checkins import operations as checkins
from biwak.files import operations as files
from biwak.outbox import sending as outbox


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Sends the notification mails which are due (specs/notifications.md):"
        " per person and item 10 minutes after the newest change, digests at"
        " 07:00; and what check-ins do (specs/checkins.md): asking the"
        " questions due, the summaries of the answers; the push notifications"
        " of mentions and assignments (specs/web-push.md); and sending again what"
        " failed to go out (specs/mail-sending.md); and telling about docs"
        ' whose creator never answered "Tell people about it?" (specs/files.md).'
        " Run every minute by cron."
    )

    def handle(self, **options):
        set_user_name("Send mails")
        verbose = options["verbosity"] > 1
        # Each part on its own: one failing doesn't keep the others from
        # running
        self.run(
            files.tell_unanswered,
            "Telling about unanswered docs failed",
            lambda told: verbose and told and f"{told} docs told about.",
        )
        self.run(
            send_mails,
            "Sending the notification mails failed",
            lambda count: verbose and f"{count} mails sent.",
        )
        self.run(
            push.send_due,
            "Sending the push notifications failed",
            lambda pushed: verbose and pushed and f"{pushed} pushes sent.",
        )
        self.run(
            checkins.run,
            "Running the check-ins failed",
            lambda done: (
                verbose
                and "Check-ins: {asked} asked, {summarized} summarized.".format(**done)
            ),
        )
        self.run(
            outbox.retry,
            "Sending the outbox again failed",
            lambda retried: (
                verbose
                and retried
                and "Outbox: "
                + ", ".join(f"{count} {result}" for result, count in retried.items())
                + "."
            ),
        )

    def run(self, part, failed, report):
        """Runs one part, logging what fails; writes what ``report`` says"""
        try:
            result = part()
        except Exception:
            logger.exception(failed)
        else:
            if line := report(result):
                self.stdout.write(line)
