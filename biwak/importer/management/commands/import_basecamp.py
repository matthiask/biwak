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
            action="append",
            default=[],
            type=int,
            help="A project's ID; repeat for several",
        )
        parser.add_argument(
            "--templates",
            action="store_true",
            help=(
                "Import the account's project templates and its to-do list"
                " library as templates (once per import is enough)"
            ),
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
            "--full",
            action="store_true",
            help=(
                "Read everything again, also what didn't change since the last"
                " run (changed subscriptions only come along this way)"
            ),
        )
        parser.add_argument(
            "--include-disabled",
            action="store_true",
            help="Import the tools switched off in Basecamp too",
        )
        parser.add_argument(
            "--archive",
            action="store_true",
            help=(
                "Archive each project in Basecamp once it was imported (not"
                " in a dry run); the token's person must be allowed to"
            ),
        )
        parser.add_argument(
            "--user",
            help=(
                "The email address of the Biwak person running the import"
                " (staff); default: the person the token belongs to"
            ),
        )

    def handle(
        self,
        *,
        account,
        project,
        dry_run,
        since,
        user,
        archive,
        full,
        include_disabled,
        templates,
        **options,
    ):
        if not project and not templates:
            raise CommandError("Give --project, --templates or both.")
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
        # Progress on stderr while it runs (-v 0: none), the report at the end

        def progress(line):
            if options["verbosity"] > 0:
                self.stderr.write(line)
                self.stderr.flush()

        def waiting(seconds, why):
            progress(f"    waiting {seconds:.0f} s ({why})")

        client.on_wait = waiting
        importer = Importer(
            client,
            actor=actor,
            dry_run=dry_run,
            since=since,
            full=full,
            include_disabled=include_disabled,
            archive=archive,
            progress=progress,
        )
        for number, project_id in enumerate(project, 1):
            progress(f"[{number}/{len(project)}] Basecamp project {project_id}")
            importer.run(project_id)
        if templates:
            progress("Templates")
            importer.run_templates()
        self.stdout.write(importer.report.as_text())
