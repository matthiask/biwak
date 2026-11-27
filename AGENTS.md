# Biwak

A self-hosted project management tool for teams working with clients.
`SPEC.md` describes what the app does and why, the model and the
decisions; `specs/` has one spec per part (`specs/README.md` lists them). Read `SPEC.md` and
the spec of the part you're working on before anything else, and update
them when a decision changes (dated: "decided 2026-11-20").

# Running it

- `./runtests.sh` runs all tests (needs the local PostgreSQL container:
  `podman start local_postgres_1`), `./runtests.sh biwak.items` some.
  In parallel, a process per CPU with a copy of the test database
  (`--parallel 1` for one). Coverage only when asked:
  `COVERAGE=1 ./runtests.sh`; CI doesn't measure it, nothing read it
  (decided 2026-11-21).
- Node and yarn come from `mise.toml` (`mise install`), as in CI. Yarn,
  never npm: `yarn add`, `yarn <bin>`, only `yarn.lock` committed
  (decided 2026-11-22: npm was very slow).
- `fl dev` runs Django and the rspack dev server; `uv run ./manage.py
  check_visibility` compares the stored visibility with the tree.
  `runserver` is Daphne's (`DEBUG`), serving the websockets of docs
  edited live and of live updates too (`asgi.py`, `biwak/collab/`,
  `biwak/live/`); the rspack dev server passes `/ws/docs/` and
  `/ws/live/` on. Deployed, the websockets need an ASGI process
  and Redis (`CACHE_URL`'s, or `REDIS_URL`), see `specs/collaboration.md`.
- `./manage.py fairy_tasks` runs the daily jobs (trash older than 30
  days, expired API tokens, `check_visibility` mailing admins).
  `./manage.py send_mails` sends the notification mails and digests that
  are due, retries the outbox (`biwak/outbox/`) and tells about docs
  whose creator never clicked "Done" (`specs/files.md`); cron runs it
  every minute. Deployed, the cron jobs live in the argocd repository.
- Push notifications (`specs/web-push.md`) need a VAPID key pair, made
  once: `uvx --from py-vapid vapid --gen` writes `private_key.pem`,
  `uvx --from py-vapid vapid --applicationServerKey` (in the same
  directory) prints "Application Server Key = …", the public key; `WEBPUSH_VAPID_PUBLIC_KEY` is that, `WEBPUSH_VAPID_PRIVATE_KEY`
  the PEM (or its lines between the markers joined), `WEBPUSH_SUBJECT`
  `mailto:` the default from address unless set. Without the keys
  nothing is offered or sent; `send_mails` pushes. The keys stay the
  same for good: new keys end every browser's subscription, so everybody
  would have to turn pushes on again.
- Replies by mail come in through Resend's webhook (`/inbound/resend/`);
  `./manage.py receive_mail FILE.eml --dmarc pass` handles a mail by
  hand. Off unless `REPLY_DOMAIN`, `RESEND_API_KEY` and
  `RESEND_WEBHOOK_SECRET` are set (`specs/notifications.md`).
- Mail goes out through the outbox (`biwak/outbox/`, admin "Outgoing
  mails") with Django's default mailer: `EMAIL_URL` (`console:` in
  development), Resend's API with `EMAIL_URL=resend:`; the same webhook
  records bounces and complaints (`specs/mail-sending.md`).
- `BASECAMP_TOKEN=... ./manage.py import_basecamp --account ID --project ID
  [--dry-run] [--archive]` imports a Basecamp 4 project
  (`specs/import-basecamp.md`); a second run updates, `--archive`
  archives it in Basecamp afterwards. Always dry-run first. The Basecamp
  CLI's tokens last an hour: for long runs `--token-command "basecamp
  auth token"` instead of `BASECAMP_TOKEN` renews it on a 401; an
  interrupted run is simply started again. Downloaded
  files are cached in `~/.cache/biwak/basecamp/` (`XDG_CACHE_HOME`),
  `--cache-dir DIR` elsewhere, `--no-cache` off; never cleaned up. The
  API's answers are reused from there for an hour (`--answers-max-age`),
  so the dry run and the run after it ask Basecamp once.
  `fl manage-remote biwak-feinheit-app ~/projects/sites/biwak
  "import_basecamp …"` (in the argocd repository) runs it locally
  against production, so the cache survives pod restarts; the checkout
  must match the deployed version.
- The audit log (`biwak/audit/`) is a trigger on the main tables.
  Requests, API tokens and `fairy_tasks` set who changes things
  (`set_user_name()`). Tests reading the audit log delete its rows first.
  What is recorded where (audit log, events, mail logs, Sentry, log
  lines): `specs/auditing.md`.
- Behind a proxy, `ALLAUTH_TRUSTED_PROXY_COUNT=1` (deployed: behind the
  ingress) takes the client's IP from `X-Forwarded-For`; without it the
  allauth's rate limits and the sessions' admin see the proxy's address.
- `.env` (not committed): `DATABASE_URL=postgres://localhost:5432/biwak`,
  `SECRET_KEY`, `DEBUG=True`.

Tests are Django tests. The CLI (`cli/`, package `biwak_cli`, installed
editable as a dev dependency) is tested by running it against the API
through the test client (`biwak/test_cli.py`). Each part adds its API
endpoints (`<app>/api.py`, conventions in `biwak/api_conventions.py`) and
CLI commands with its pages; bump `cli/pyproject.toml`'s version with new
commands and `MINIMUM` in `biwak/cli_version.py` when older CLIs break.
The agent skills are `cli/biwak_cli/skills/<name>/SKILL.md`
(`specs/agent-skills.md`), linked into Claude Code by `biwak skills
install`: bump the CLI's version when a skill changes; `biwak/test_skills.py`
checks the commands and options they show.

End-to-end tests (`biwak/test_e2e_<area>.py` on the shared base in
`biwak/test_e2e.py`, tagged `e2e`) run the real server and
Chromium through Playwright: `uv run playwright install chromium` once,
without the browser they're skipped, `./runtests.sh --exclude-tag e2e`
leaves them out.
What a run costs is how many tests it runs: one module about 3
seconds, a whole app half a minute, everything five minutes. While
building, run the one or two modules you changed with `--exclude-tag
e2e --parallel 1` (decided 2026-11-22: waiting on tests isn't work). Only for what nothing but a browser can test:
the JavaScript in `frontend/` and htmx (decided 2026-11-20); the test client
covers everything else. A change to a script or an htmx interaction gets a
test there: logged in through a session cookie, Playwright's waiting
instead of sleeps, `ControlOrMeta` for shortcuts (so they run on a Mac too), at least the client's view where it differs. No tests
of plain CSS layout (sizes, positions, alignment, wrapping, fitting the
screen): they're slow, break on font differences between machines and
test the browser, not our code; look at screenshots instead (decided
2026-11-21). Positions that JavaScript computes (menus, the reaction
picker) and computed colors stay testable.

# Modals

Forms open in a `<dialog>` (`frontend/modal.js`, `biwak/modals.py`, copied
from Governance). Every modal form is also a page:

- A view answers with `form_response(request, form, title=, cancel_url=,
  item=/project=, intro=, submit_label=, destructive=)`, which renders
  `modal_form.html`: the whole page normally, only the form for a request
  with the `HX-Modal` header. `form=None` is a question (the trash).
- Success is a plain `redirect()`: the middleware turns it into
  `HX-Redirect` for modal requests. Errors render the form again in the
  dialog, with status 200.
- A link opens it with `data-modal` (without JavaScript, or with a modifier
  key, it's the form's page). In JavaScript: `openModal(url, from)`. In the
  palette: `modal(label, url)` in `biwak/palette/actions.py`.
- Escape closes an unchanged form, a changed one needs it twice; Cancel
  has `data-modal-close`; the focus returns to the link (or its menu).
- Items' "More" menu is `items/_more.html` (Notifications…, Move to…,
  Trash); the navigation's search field is a link to the search page that
  opens the palette (`data-palette-open`).

# Code and conventions

The code and conventions come from
[Governance](https://github.com/feinheit/governance) (checked out in
`~/projects/sites/governance`, see its `AGENTS.md`), which got them from
Workbench. Copy what fits instead of depending on it, and keep its
conventions unless this file says otherwise: Django, PostgreSQL,
django-ninja, htmx, the page layout, the frontend bundle, `fl` for the
usual tasks, tests with `./runtests.sh`. Governance is BSD-3 licensed by
Feinheit AG; copied files keep its copyright line (`NOTICE`). Workbench
(`~/projects/sites/workbench`) is GPLv3 only because of its QR bill
library; its own code is the user's, and adapting it is fine (decided
2026-11-21). Leave its QR bill parts alone.

# Working on a part

- One part per branch and worktree (`specs/<part>.md`).
- Small commits, each with tests, docs and spec changes together.
- No attribution in commits, merges or pull requests: no
  `Co-Authored-By:` lines, no "Generated with …" (decided 2026-11-24).
- Keep it consistent: check what the existing code already does (the
  same action elsewhere, the other entry points) and do the same. No
  branches for special cases unless the special case makes sense
  (decided 2026-11-21). Often that answers a question before it's asked.
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
   Texts people search for get an expression index in a migration and an
   entry in `TEXTS` in `biwak/search/queries.py` (`specs/search.md`).
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
   create to-dos, comments and messages where they can see and change
   only what they created (`ops.can_change()`), except the fields of
   visible to-dos, which are shared work (`specs/access.md`). Visibility
   switches are staff only.
5. **Pages.** Server-rendered templates extending `base.html`,
   following the UI rules in `specs/ui.md` (read it before building a
   page): forms in modals, quiet pages, one primary button, cards, empty
   states, filters, the combobox, `capfirst` labels, the client badge,
   tab and banner, phones, motion, keyboard rows. How to build them:
   icons with `{% icon %}`, a new one in `frontend/styles/icons.css`
   (`biwak/test_icons.py` checks). JavaScript only for interaction, in
   `frontend/`, loaded from `main.js`. Every `Textarea` is a Markdown
   field with the toolbar (`data-toolbar`); texts shown with
   `{% checklist_markdown text item %}` can be ticked in place, and a
   detail model with a text that may have a task list inherits
   `Checklist` (stored counts, shown on rows with
   `items/_checklist_signal.html`). What several pages show comes from
   an include, not a copy. A class in a template needs CSS in the bundle
   (`biwak/test_css.py`: Bootstrap is compiled in parts,
   `frontend/styles/bootstrap.scss`, or a `wb-` class in `main.css`).
   What a page offers in the command palette and as shortcuts is decided
   in `biwak/palette/actions.py` (the buttons' permission checks); a new
   kind of page or action goes there, with a test on the rendered JSON.
   Colors are palette tokens, never hard-coded.
   Template comments: `{# … #}` only on one line (Django prints a
   multi-line one); longer ones in `{% comment %}…{% endcomment %}`.
6. **API.** Endpoints in the app's `api.py`, registered in
   `biwak/api.py`, following `biwak/api_conventions.py`
   (`visible_to_clients` on every item, Markdown plus `*_html`, cursor
   pagination for lists that grow). Same operations as the pages.
7. **CLI.** Commands in the area's module in `cli/biwak_cli/` (`todos.py`,
   `projects.py`, ...; what they share in `core.py`) with `--json`, named
   by the rules in `specs/api-cli.md` (a plural group per thing that
   lists alone, verbs as subcommands); mark what clients can see with
   `[clients]`. Bump `cli/pyproject.toml`'s version.
8. **Admin.** Model admins use `biwak.admin` (`from biwak import
   admin`): read only, unless it opts in (`ReadWriteModelAdmin`) because
   the spec says the admin changes it; `raw_id_fields` (or autocomplete)
   for foreign keys of editable admins. `biwak/test_admin.py` lists who
   may change what.
9. **Audit log.** New tables people change get `audit_tables()` in a
   migration (`biwak/audit/migrations/0002_audited_tables.py` shows how).
10. **Daily or hourly work** goes into `fairy_tasks` (daily) or an
   `hourly_tasks` command; nothing runs in threads or on requests.
11. **Mails** go through the outbox: `biwak.outbox.sending.send(message,
    kind)` in the transaction of the change, never `message.send()`; it
    sends after the commit and retries (`specs/mail-sending.md`).
    `mail_admins` alone goes around it.
12. **Help.** The user documentation is in `docs/` (`/help/`,
    `biwak/help.py`, `specs/help.md`). A part that adds or changes what
    people see or do updates the chapter it belongs to (or adds one, in
    `help.py`'s table), in the same branch: what it does now, short,
    no plans, in both languages (`name.md` and `name.de.md`). Shortcuts stay in `palette/_shortcuts.html`, the one list.
13. **Tests.** Django tests next to the code (`test_*.py`): the
    operations, every page and endpoint as staff and as a client
    (including a client getting 404 for internal items), the CLI
    commands (`biwak/test_cli.py`). Made-up data from
    `biwak/test_utils.py`. Browser tests only for JavaScript and htmx
    (above).
14. **Done** means: the spec's "Done when" list is true, the help says
    what was built, the tests your change affects pass, `uvx prek run
    --all-files` is clean, and the spec says what was built (a "Status"
    line) and any decisions made on the way.

    **Run only the affected tests** (decided 2026-11-22: several agents
    at once had the machine at a load above 13, slowing everybody down):
    the test modules or classes covering the code you changed
    (`./runtests.sh biwak.items.test_start_dates …`), not whole apps;
    browser tests only when you changed JavaScript or htmx, and only
    those classes. **No full runs locally**, not after merging either
    (decided 2026-11-23: a full run per merge had the machine at a load
    of 21): CI runs everything. Push `main` in batches, after a few
    merges, and fix what CI finds.

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

Code, specs, commits and issues in English. The interface is English and
German, chosen per person (`specs/languages.md`). Every text is marked for
translation (`gettext`, `gettext_lazy` outside functions, whole sentences
with placeholders, `ngettext` for counts) and translated in the same
branch: `fl mm --language=de`, translate the new entries in
`conf/locale/de/LC_MESSAGES/django.po`, `fl cm`, commit both files
(`fl mm` also writes `conf/strings.js`, ignored by git);
`biwak/test_catalog.py` fails on a text without its translation. The
German: "du", Swiss spelling (ss, never ß), gender-neutral with the colon
(Teilnehmer:innen) or neutral words, the glossary in
`specs/languages.md`. Do not use the asterisk because broken Markdown
parsers do not like it. Mails go out in `language_for(recipient)`
(`biwak/accounts/languages.py`); scripts get their texts from the page.
