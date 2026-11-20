# API, CLI and agent skills

**Status:** the foundations are built (2026-11-20, see "Order" below);
each part adds its endpoints and commands.

API first: everything the web interface does is possible through the API
(decided 2026-11-20). Conventions copied from Governance and Workbench.

## API

- django-ninja under `/api/v1/`, OpenAPI schema published.
- Authentication: personal API keys (created and revoked by the person,
  read-only or read-write), and a browser-based login for the CLI that
  creates such a key.
- The same visibility rules as the web interface (`access.md`): a client's
  key sees what the client sees. Every item in a response carries its
  visibility.
- Rich text accepted as Markdown, returned as HTML and Markdown.
- Cursor pagination; filters matching the web interface's.
- Writes create the same events and notifications as the web interface.
- Webhooks for events (later): signed, retried, per project or
  installation.

## CLI

A Python package in `cli/`, the command is `biwak` (no abbreviation for
a name this short):

- Login, projects, lists, to-dos (create, complete, assign, move),
  comments, messages, docs, files (upload and download), check-in answers,
  the chronological list ("my to-dos"), the feed, search, bookmarks.
- Human-readable output by default, `--json` for scripts and agents.
- Versioned with the server; warns when they don't match.

## Agent skills

Skills in the CLI package for common work: triaging what changed,
turning a mail into a to-do or message, writing a weekly summary of a
project. They tell agents to check visibility before writing anything a
client could see. Not built yet: their own part after the importer
(decided 2026-11-20), specified before building.

## Closing the gaps to the web (decided 2026-11-20)

**Built (2026-11-20, CLI 0.17.0).** The verification round found what the
web does but the API and CLI can't; one small part closes it. Built on
`create_project()` and `joinable_projects()` in `biwak/projects/operations.py`,
which the web views use too. Choices made on the way: admins list the
projects they can join with `GET /api/v1/projects/joinable/` (id and name
only, empty for everybody else) and `biwak projects --joinable`; joining
twice changes nothing; the DELETE answers with the removed person and 404
when they aren't a member; creating records no event (as on the web).

- `POST /api/v1/projects/` (staff; the creator becomes a member),
  `biwak project add NAME [--limited]`.
- Joining: admins see limited projects they're not in (as the projects
  page does) and `POST /api/v1/projects/{id}/join/` records `joined`;
  `biwak project join ID`.
- Removing a member and leaving: `DELETE
  /api/v1/projects/{id}/members/{person_id}/` with the web's rules,
  `biwak member remove PROJECT PERSON`.
- `biwak todo move TODO --list ID [--group ID]` and moving several
  (`--todos 1,2,3`) through the existing move endpoints.

## Order

The foundations (keys, conventions, visibility in responses) come with
the core; each part adds its endpoints and CLI commands in the same
branch.

Built with the core (2026-11-20): tokens (`biwak/accounts/models.py`,
page at `/accounts/api-tokens/`, `/accounts/cli-login/`), the conventions
in `biwak/api_conventions.py` (every item carries `visible_to_clients`;
Markdown plus `*_html`; cursor pagination for lists that grow, complete
responses for short ones; absolute URLs), the CLI version check
(`biwak/cli_version.py`, header `X-Biwak-CLI`), endpoints for me, tokens,
projects, members, lists, groups, to-dos, comments, subscriptions and the
visibility switch, and `biwak login/logout/me/projects/lists/todos/todo`.
Webhooks, the feed, search and the chronological list come with their
parts.
