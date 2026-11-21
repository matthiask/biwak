import logging

from django.core.management import BaseCommand, call_command

from biwak.accounts.middleware import set_user_name
from biwak.accounts.models import prune_api_tokens
from biwak.files.attachments import delete_unlinked
from biwak.inbound.tokens import prune as prune_replies
from biwak.items.operations import purge_trash
from biwak.projects.operations import recompute_activity


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Daily tasks: deleting what has been in the trash for 30 days,"
        " pruning expired API tokens, deleting received mails and reply tokens after 90 days, deleting attachments whose text was"
        " never saved after a day, recomputing the projects' activity times, comparing the stored visibility with"
        " the tree and mailing admins about differences"
    )

    def handle(self, **options):
        set_user_name("Fairy tasks")
        tasks = {
            "purge_trash": purge_trash,
            "prune_api_tokens": prune_api_tokens,
            "delete_unlinked": delete_unlinked,
            "prune_replies": prune_replies,
            "recompute_activity": recompute_activity,
            "check_visibility": lambda: call_command(
                "check_visibility", mail=True, stdout=self.stdout
            ),
        }
        # Each task on its own: one failing doesn't keep the others from
        # running
        for name, task in tasks.items():
            try:
                task()
            except Exception:
                logger.exception("The daily task %s failed", name)
