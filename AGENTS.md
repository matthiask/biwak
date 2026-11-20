# Biwak

A self-hosted project management tool for teams working with clients.
`SPEC.md` describes what the app does and why, the model, the decisions
and the build order; `specs/` has one spec per part. Read `SPEC.md` and
the spec of the part you're working on before anything else, and update
them when a decision changes (dated: "decided 2026-11-20").

# Running it

- `./runtests.sh` runs all tests (needs the local PostgreSQL container:
  `podman start local_postgres_1`), `./runtests.sh biwak.items` some.
- `fl dev` runs Django and the rspack dev server; `uv run ./manage.py
  check_visibility` compares the stored visibility with the tree.
- `./manage.py fairy_tasks` runs the daily jobs (trash older than 30
  days, expired API tokens, `check_visibility` mailing admins); new daily
  jobs go there, hourly ones into an `hourly_tasks` like Governance's.
  Once deployed, the cron job lives in the argocd repository.
- The audit log (`biwak/audit/`) is a trigger on the main tables; new
  tables people change get `audit_tables()` in a migration. Requests,
  API tokens and `fairy_tasks` set who changes things (`set_user_name()`).
  Tests reading the audit log delete its rows first.
- `.env` (not committed): `DATABASE_URL=postgres://localhost:5432/biwak`,
  `SECRET_KEY`, `DEBUG=True`.

Tests are Django tests. The CLI (`cli/`, package `biwak_cli`, installed
editable as a dev dependency) is tested by running it against the API
through the test client (`biwak/test_cli.py`). Each part adds its API
endpoints (`<app>/api.py`, conventions in `biwak/api_conventions.py`) and
CLI commands with its pages; bump `cli/pyproject.toml`'s version with new
commands and `MINIMUM` in `biwak/cli_version.py` when older CLIs break. Browser end-to-end tests (Playwright) only where
nothing else can test something, and not while we're still exploring
(decided 2026-11-20): they slow us down.

# Code and conventions

The code and conventions come from
[Governance](https://github.com/feinheit/governance) (checked out in
`~/projects/sites/governance`, see its `AGENTS.md`), which got them from
Workbench. Copy what fits instead of depending on it, and keep its
conventions unless this file says otherwise: Django, PostgreSQL,
django-ninja, htmx, the page layout, the frontend bundle, `fl` for the
usual tasks, tests with `./runtests.sh`. Governance is BSD-3 licensed by
Feinheit AG; copied files keep its copyright line (`NOTICE`). Don't copy
from Workbench directly (GPLv3).

# Working on a part

- One part per branch and worktree (`specs/<part>.md`), in the order of
  "Build order" in `SPEC.md`; a part's spec says what it depends on.
- Small commits, each with tests, docs and spec changes together.
- Questions the spec doesn't answer go to the user; write the answer into
  the spec. Don't invent product decisions: values the spec doesn't fix
  (durations, limits, wording of states) are questions too.
- Anything touching visibility (`specs/access.md`) needs tests through
  every entry point: views, feed, search, mails, mail replies, API.

## Building a part: the checklist

What every part does the same way. Look at how the core does it
(`biwak/items/`, `biwak/projects/`) and copy the pattern.

1. **Models.** New kinds of items are an `Item` kind plus a detail model
   sharing its primary key (`Detail` in `biwak/items/models.py`); add the
   kind to `Kind`, `ALLOWED_PARENTS`, `SWITCHABLE` and `COMMENTABLE` as
   the spec says. Things that aren't items (bookmarks, links, mail
   tokens) get a foreign key to `Item` or `Project`. Texts are Markdown
   in a `TextField`, never HTML.
2. **Operations.** Every change goes through a function in the app's
   `operations.py`, `@transaction.atomic`, which also records the event
   (`biwak.activity.operations.record`) and subscriptions. Views, the
   API, mail replies and the importer call these functions; they never
   save items themselves.
3. **Visibility.** Every query for items goes through
   `Item.objects.visible_to(user)` (views: `item_for()` in
   `biwak/items/views.py`, API: `item_for()` in `biwak/items/api.py`);
   projects through `Project.objects.accessible_to(user)`. Something
   pointing at an item is visible exactly when its item is. New items
   get their stored visibility with `visibility.recompute(item)` in the
   creating operation.
4. **Who may change what.** Staff change everything they see; clients
   create where they can see and change only what they created
   (`ops.can_change()`). Visibility switches are staff only.
5. **Pages.** Server-rendered templates extending `base.html`, the
   client badge (`{% client_badge item %}`) on everything visible to
   clients and the banner (`items/_client_banner.html`) above forms on
   visible items. Icons with `{% icon %}`; a new icon goes into
   `frontend/styles/icons.css` (`biwak/test_icons.py` checks). JavaScript
   only for interaction, in `frontend/`, loaded from `main.js`.
6. **API.** Endpoints in the app's `api.py`, registered in
   `biwak/api.py`, following `biwak/api_conventions.py`
   (`visible_to_clients` on every item, Markdown plus `*_html`, cursor
   pagination for lists that grow). Same operations as the pages.
7. **CLI.** Commands in `cli/biwak_cli/commands.py` with `--json`; mark
   what clients can see with `[clients]`. Bump `cli/pyproject.toml`'s
   version.
8. **Audit log.** New tables people change get `audit_tables()` in a
   migration (`biwak/audit/migrations/0002_audited_tables.py` shows how).
9. **Daily or hourly work** goes into `fairy_tasks` (daily) or an
   `hourly_tasks` command; nothing runs in threads or on requests.
10. **Mails** go out after the transaction commits
    (`transaction.on_commit`), never inside it.
11. **Tests.** Django tests next to the code (`test_*.py`): the
    operations, every page and endpoint as staff and as a client
    (including a client getting 404 for internal items), the CLI
    commands (`biwak/test_cli.py`). Made-up data from
    `biwak/test_utils.py`. No browser tests.
12. **Done** means: the spec's "Done when" list is true, `./runtests.sh`
    passes, `uvx prek run --all-files` is clean, and the spec says what
    was built (a "Status" line) and any decisions made on the way.

# Fixing bugs

1. Write a test which reproduces the bug.
2. Run it and make sure it fails, and fails for the right reason.
3. Simplify the test down to the essential behaviour.
4. Run it again and make sure it still fails.
5. Only then implement the fix and confirm the test passes.

# Data

No real data in this repository: tests, fixtures and examples use made-up
projects, people and clients. The same in issues and commit messages.

# Language

Code, specs, commits and issues in English. The interface is English for
now, with texts marked for translation (`gettext`) but no catalog; the
German translation comes at the end (decided 2026-11-20: churn while
exploring). Then gender-neutral German or use the colon
(Teilnehmer:innen). Do not use the asterisk because broken Markdown parsers
do not like it.
