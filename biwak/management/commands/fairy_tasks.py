from django.core.management import BaseCommand, call_command

from biwak.accounts.middleware import set_user_name
from biwak.accounts.models import prune_api_tokens
from biwak.files.attachments import delete_unlinked
from biwak.items.operations import purge_trash
from biwak.projects.operations import recompute_activity


class Command(BaseCommand):
    help = (
        "Daily tasks: deleting what has been in the trash for 30 days,"
        " pruning expired API tokens, deleting attachments whose text was"
        " never saved after a day, recomputing the projects' activity times, comparing the stored visibility with"
        " the tree and mailing admins about differences"
    )

    def handle(self, **options):
        set_user_name("Fairy tasks")
        purge_trash()
        prune_api_tokens()
        delete_unlinked()
        recompute_activity()
        call_command("check_visibility", mail=True, stdout=self.stdout)
