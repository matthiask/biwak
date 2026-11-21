# Activating and deactivating people

The idea (backlog in `SPEC.md`, 2026-11-21): the importer creates people
without an account inactive on purpose, so nobody gets mail or a login
before someone decides; activating them works only in the Django admin
today. Deactivating someone who left is the same switch the other way.

**Status:** built (2026-11-21, CLI 0.34.0): `biwak/organizations/activation.py`
(`activate()`, `deactivate()`, `can_change()`), the pages in
`biwak/organizations/people.py` (`/people/?inactive=1`,
`/people/<id>/activate/` and `…/deactivate/`, a palette action on the
person's page), the API in `biwak/organizations/api.py`, `biwak people`
in the CLI; tests `biwak/organizations/test_activation.py` and
`biwak/test_cli_people.py`. Decisions on the way are marked "built".

**Agent:** a cheaper model following this spec and the checklist in
`AGENTS.md`; deactivating ends access, so have the tests of that
reviewed.

**Depends on:** `ui-round-6.md` (invitations, the invitation mail),
`sso.md` (sessions and tokens), `organizations.md` (the people pages).

## Who and where (decided 2026-11-21)

- **Who** (decided 2026-11-21, replacing "admins only"): staff activate
  and deactivate clients; admins also own staff and partners (people of
  partner organizations); clients and partners never. The same split as
  inviting (staff invite clients, admins invite staff). Several at once
  with someone the actor may not change is refused as a whole.
- **Pages:** `/people/` gets an "Inactive" filter (next to "Invited");
  a person's page has "Activate…" or "Deactivate…" for admins, each a
  modal (`form_response`).
- **API:** `POST /api/v1/people/{id}/activate/` and `…/deactivate/`, and
  a bulk form taking several IDs (`POST /api/v1/people/activate/` with
  `ids` and `mail`), all or nothing.
- **CLI:** `biwak people activate ID… [--mail]`, `biwak people deactivate
  ID…`, `biwak people --inactive` lists them (bump the CLI version).

## Activating

- Sets `is_active`; nothing else changes (memberships, subscriptions,
  assignments made by the import stay).
- **The mail is optional** (decided 2026-11-21): with `--mail` (a checkbox
  on the page, off by default) the person gets the invitation mail of
  `ui-round-6.md`, naming the projects they're in, through the outbox;
  `invited_by`/`invited_at` are set then, so they show as invited until
  they sign in. Without it, no mail.
- People whose address bounced (`mail_undeliverable_at`) can be activated;
  the mail isn't sent to them and the page says so.
- An event per person isn't needed in the feed (it isn't about a project);
  the audit log records the change (`accounts_user` is audited).

## Deactivating

- Clears `is_active`; refused for oneself and for the last active admin.
- **Ends access at once:** the person's sessions (`UserSession.end()` as
  `sso.md` does), API tokens and calendar links are deleted, open
  websockets close at their next access check.
- Keeps everything they did and what points at them: memberships,
  subscriptions (no mail goes to inactive people anyway), assignments
  (their to-dos count as "Nobody active", `ui-round-5.md`), comments.
- No mail to the person.
- Reactivating is "Activate" again (with or without the mail).

## Built (decisions on the way, 2026-11-21)

- **Page 404/403:** clients (and partners, who can't manage members) get
  404 on the pages, staff on somebody they may not change 403; the API
  answers 403 for both.
- **Already active** people in an activation, and already inactive ones in
  a deactivation, are skipped quietly (no mail, nothing recorded).
- **Bulk deactivation** exists too (`POST /api/v1/people/deactivate/` with
  `ids`; the CLI takes several IDs). `GET /api/v1/people/` lists the
  active people, `?inactive=true` the inactive ones (own staff): the CLI's
  `biwak people`.
- **A refused case** (oneself, the last active admin) is a 400 in the API,
  an error message on the pages; the pages don't offer "Deactivate…" for
  oneself. The last-admin refusal can't happen for an active admin acting
  (they stay), it guards the operation.
- **The mail** isn't sent to bounced addresses, and then `invited_by`/
  `invited_at` stay unset too. The "Inactive" filter has "Activate…" per
  row (the bulk is API and CLI only).
- **Open websockets** close through `sso.session_alive()` (inactive people
  fail it) after `live.check_access(user=…)` told them to check.

## Done when

- Both ways through the pages, the API (single and bulk) and the CLI, as
  admin; staff and clients get 403 (pages: 404 for clients, as the
  people pages).
- Tests: activating with and without the mail (outbox, after the commit,
  nothing on a failed bulk), bounced addresses, deactivating ending
  sessions, tokens, calendar links and websockets, oneself and the last
  admin refused, the filters.
- `docs/` (people) and `SPEC.md`'s backlog item say so.
