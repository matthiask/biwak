import datetime as dt
import os
import shlex
import subprocess
from pathlib import Path

from django.core.management import BaseCommand, CommandError

from biwak.accounts.middleware import set_user_name
from biwak.accounts.models import User
from biwak.importer import client as api
from biwak.importer.importer import Importer, ImportRefused


def make_client(account, token, *, cache_dir=None, answers_max_age=0, renew_token=None):
    """``cache_dir``: where downloads are cached, None for no cache; the
    API's answers are cached in its ``answers/`` for ``answers_max_age``
    seconds (0: not). ``renew_token``: called for a new token after a 401"""
    if cache_dir is None:
        return api.BasecampClient(account, token, renew_token=renew_token)
    answers = None
    if answers_max_age > 0:
        answers = api.AnswerCache(Path(cache_dir) / "answers", answers_max_age)
    return api.BasecampClient(
        account,
        token,
        cache=api.FileCache(cache_dir),
        answers=answers,
        renew_token=renew_token,
    )


def token_from(command):
    """The token a command prints (``basecamp auth token``), run
    without ``BASECAMP_TOKEN``, which the Basecamp CLI would just echo"""
    env = {k: v for k, v in os.environ.items() if k != "BASECAMP_TOKEN"}
    try:
        result = subprocess.run(
            shlex.split(command),
            capture_output=True,
            text=True,
            check=True,
            env=env,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CommandError(f"--token-command {command!r} failed: {exc}") from exc
    return result.stdout.strip()


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
            "--cache-dir",
            help=(
                "Where downloaded files are cached, by their storage location"
                " (default: $XDG_CACHE_HOME/biwak/basecamp or"
                " ~/.cache/biwak/basecamp); never cleaned up"
            ),
        )
        parser.add_argument(
            "--no-cache",
            action="store_true",
            help=(
                "Download every file and ask Basecamp everything, without"
                " reading or writing the cache"
            ),
        )
        parser.add_argument(
            "--answers-max-age",
            type=float,
            default=1,
            metavar="HOURS",
            help=(
                "How long the API's answers are reused from the cache, so a"
                " dry run and the run after it read Basecamp once (default:"
                " 1; 0: always ask)"
            ),
        )
        parser.add_argument(
            "--user",
            help=(
                "The email address of the Biwak person running the import"
                " (staff); default: the person the token belongs to"
            ),
        )
        parser.add_argument(
            "--token-command",
            help=(
                "A command printing an OAuth token, run for the token without"
                " BASECAMP_TOKEN and again whenever Basecamp refuses it (401;"
                ' the Basecamp CLI\'s last an hour), e.g. "basecamp auth token"'
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
        cache_dir,
        no_cache,
        answers_max_age,
        token_command,
        **options,
    ):
        if not project and not templates:
            raise CommandError("Give --project, --templates or both.")
        renew_token = token_command and (lambda: token_from(token_command))
        token = os.environ.get("BASECAMP_TOKEN") or (renew_token and renew_token())
        if not token:
            raise CommandError(
                "Set BASECAMP_TOKEN to an OAuth token, or give --token-command."
            )
        if no_cache and cache_dir:
            raise CommandError("Give --cache-dir or --no-cache, not both.")
        if not no_cache:
            cache_dir = cache_dir or api.default_cache_dir()
        client = make_client(
            account,
            token,
            cache_dir=None if no_cache else cache_dir,
            answers_max_age=answers_max_age * 3600,
            renew_token=renew_token,
        )
        try:
            profile = client.identify()
        except api.Unauthorized as exc:
            raise CommandError(_refused(token_command)) from exc
        email = user or profile.get("email_address")
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
        client.on_renew = lambda: progress("    token renewed")
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
        try:
            for number, project_id in enumerate(project, 1):
                progress(f"[{number}/{len(project)}] Basecamp project {project_id}")
                importer.run(project_id)
            if templates:
                progress("Templates")
                importer.run_templates()
        except ImportRefused as exc:
            raise CommandError(str(exc)) from exc
        except api.Unauthorized as exc:
            raise CommandError(_refused(token_command)) from exc
        self.stdout.write(importer.report.as_text())


def _refused(token_command):
    if token_command:
        return (
            f"Basecamp refused the token, also the one {token_command!r} gave"
            " (401). Log in again; a rerun continues where this one stopped."
        )
    return (
        "Basecamp refused the token (401), it probably expired: give"
        ' --token-command "basecamp auth token" to renew it while'
        " running. A rerun continues where this one stopped."
    )
