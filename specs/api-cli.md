# API, CLI and agent skills

**Status:** API and CLI built (2026-11-20), each part adds its endpoints
and commands; agent skills postponed (2026-11-21).

API first: everything the web interface does is possible through the API
(decided 2026-11-20). Conventions copied from Governance and Workbench.

## API

- django-ninja under `/api/v1/`, OpenAPI schema published.
- Authentication: personal API tokens (created and revoked by the
  person, read-only or read-write; `biwak/accounts/models.py`, page at
  `/accounts/api-tokens/`), and a browser-based login for the CLI that
  creates one (`/accounts/cli-login/`).
- The same visibility rules as the web interface (`access.md`): a
  client's token sees what the client sees. Every item in a response
  carries `visible_to_clients`.
- The conventions are in `biwak/api_conventions.py`: Markdown in, Markdown
  plus `*_html` out; cursor pagination for lists that grow, complete
  responses for short ones; absolute URLs.
- Writes go through the same operations as the pages, so they create the
  same events and notifications.
- Errors (decided 2026-11-21): `{"detail": ...}`; what the schema
  refuses is ninja's 422 list (titles: `Title` in
  `biwak/api_conventions.py`, stripped, 1 to 500 characters), what the
  models refuse (`ValidationError`) a 400 from one handler in
  `biwak/api.py`, 404 where an object's existence mustn't leak.
- Projects and members as on the web (`create_project()`,
  `joinable_projects()` in `biwak/projects/operations.py`): staff create
  projects (the creator becomes a member, no event); admins list
  (`GET /api/v1/projects/joinable/`) and join limited projects they're
  not in; `DELETE /api/v1/projects/{id}/members/{person_id}/` removes a
  member, own staff only, themselves included (clients and externals get
  403, for themselves too: nobody leaves, decided 2026-11-22,
  `organizations.md`).
- Webhooks for events: later (signed, retried, per project or
  installation), specified before building.

## CLI

A Python package in `cli/` (`biwak_cli`), the command is `biwak`:

- Every part adds its commands (`cli/biwak_cli/commands.py`); human-
  readable output by default, `--json` for scripts and agents, `[clients]`
  marking what clients can see.
- Lists with cursor pagination are read page by page (`paginate()` in
  `cli/biwak_cli/core.py`): complete, or up to `--limit` where a command
  has one.
- The server checks the CLI's version (`biwak/cli_version.py`, header
  `X-Biwak-CLI`) and refuses CLIs older than `MINIMUM`; bump
  `cli/pyproject.toml` with new commands.

## Agent skills

Skills in the CLI package for common work (triaging what changed,
turning a mail into a to-do or message, a weekly summary of a project),
telling agents to check visibility before writing anything a client
could see. **Postponed** (decided 2026-11-21): no skill is needed yet;
one-off work like activating imported people is a script on top of the
API and the CLI (`activation.md`). Specified before building.
