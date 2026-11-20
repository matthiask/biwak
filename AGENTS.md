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
- `.env` (not committed): `DATABASE_URL=postgres://localhost:5432/biwak`,
  `SECRET_KEY`, `DEBUG=True`.

Tests are Django tests. Browser end-to-end tests (Playwright) only where
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

- One part per branch and worktree (`specs/<part>.md`); the core
  (`core.md`, `access.md`, events and subscriptions) is done first and in
  order, see "Build order" in `SPEC.md`.
- Small commits, each with tests, docs and spec changes together.
- Questions the spec doesn't answer go to the user; write the answer into
  the spec.
- Anything touching visibility (`specs/access.md`) needs tests through
  every entry point: views, feed, search, mails, mail replies, API.

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

Code, specs, commits and issues in English. The interface in German and
English from the start; gender-neutral German or use the colon
(Teilnehmer:innen). Do not use the asterisk because broken Markdown parsers
do not like it.
