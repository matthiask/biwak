import logging

from django.core.management import BaseCommand, call_command

from biwak.accounts.middleware import set_user_name
from biwak.accounts.models import prune_api_tokens
from biwak.files.attachments import delete_unlinked
from biwak.files.operations import save_pending
from biwak.forwarding.operations import delete_old as delete_forwarded
from biwak.inbound.tokens import prune as prune_replies
from biwak.items import stale
from biwak.items.editing import prune as prune_editing
from biwak.items.operations import delete_drafts, purge_trash
from biwak.outbox.sending import prune as prune_outbox
from biwak.projects.operations import recompute_activity
from biwak.public_links.operations import delete_expired as delete_public_links


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Daily tasks: deleting what has been in the trash for 30 days,"
        " pruning expired API tokens, deleting expired public links, deleting forwarded mails nobody filed after 30 days, deleting received mails and reply tokens after 90 days, deleting sent mails' records after 30 days, deleting attachments whose text was"
        " never saved after a day, warning about stale to-dos and marking"
        " those warned 14 days ago obsolete (STALE_TODOS),"
        " saving what was typed into docs live and"
        " not saved yet, deleting new docs left empty after a day, recomputing the projects' activity times, comparing the stored visibility with"
        " the tree and mailing admins about differences"
    )

    def handle(self, **options):
        set_user_name("Fairy tasks")
        tasks = {
            "purge_trash": purge_trash,
            "prune_api_tokens": prune_api_tokens,
            "save_pending": save_pending,
            # After saving: typing left over (offline, a lost connection)
            # links its files, and a draft with text saved is a doc
            "delete_unlinked": delete_unlinked,
            "delete_drafts": delete_drafts,
            "prune_replies": prune_replies,
            "prune_outbox": prune_outbox,
            "prune_editing": prune_editing,
            "delete_public_links": delete_public_links,
            "delete_forwarded": delete_forwarded,
            "recompute_activity": recompute_activity,
            # With STALE_TODOS (specs/stale-todos.md)
            "stale_todos": stale.run,
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
