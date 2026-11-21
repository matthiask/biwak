import datetime as dt
import os

from django.core.management import BaseCommand, CommandError

from biwak.accounts.middleware import set_user_name
from biwak.accounts.models import User
from biwak.importer import client as api
from biwak.importer.importer import Importer


def make_client(account, token):
    return api.BasecampClient(account, token)


class Command(BaseCommand):
    help = (
        "Imports Basecamp 4 projects (specs/import-basecamp.md). The OAuth"
        " token of an administrator of the account is read from the"
        " environment (BASECAMP_TOKEN); Basecamp only gives administrators"
        " the people's email addresses. A second run updates what was"
        " imported."
    )

    def add_arguments(self, parser):
        parser.add_argument("--account", required=True, help="The account's ID")
        parser.add_argument(
            "--project",
            required=True,
            action="append",
            type=int,
            help="A project's ID; repeat for several",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Count, list the people to create and the problems; write nothing",
        )
        parser.add_argument(
            "--since",
            type=dt.date.fromisoformat,
            help="Only what was changed on or after this date (YYYY-MM-DD)",
        )
        parser.add_argument(
            "--user",
            help=(
                "The email address of the Biwak person running the import"
                " (staff); default: the person the token belongs to"
            ),
        )

    def handle(self, *, account, project, dry_run, since, user, **options):
        token = os.environ.get("BASECAMP_TOKEN")
        if not token:
            raise CommandError("Set BASECAMP_TOKEN to an OAuth token.")
        client = make_client(account, token)
        email = user or client.get("/my/profile.json").get("email_address")
        actor = User.objects.filter(email__iexact=email or "", is_active=True).first()
        if actor is None or actor.is_client:
            raise CommandError(
                f"No active staff member {email!r} to run the import as: give"
                " --user with the email address of a Biwak staff member."
            )
        set_user_name("Basecamp import")
        since = since and dt.datetime.combine(since, dt.time(), tzinfo=dt.UTC)
        importer = Importer(client, actor=actor, dry_run=dry_run, since=since)
        for project_id in project:
            importer.run(project_id)
        self.stdout.write(importer.report.as_text())
