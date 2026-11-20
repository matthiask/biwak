from django.core.management import BaseCommand, call_command

from biwak.accounts.middleware import set_user_name
from biwak.accounts.models import prune_api_tokens
from biwak.items.operations import purge_trash


class Command(BaseCommand):
    help = (
        "Daily tasks: deleting what has been in the trash for 30 days,"
        " pruning expired API tokens, comparing the stored visibility with"
        " the tree and mailing admins about differences"
    )

    def handle(self, **options):
        set_user_name("Fairy tasks")
        purge_trash()
        prune_api_tokens()
        call_command("check_visibility", mail=True, stdout=self.stdout)
