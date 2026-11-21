# Activating and deactivating people

The idea (backlog in `SPEC.md`, 2026-11-21): the importer creates people
without an account inactive on purpose, so nobody gets mail or a login
before someone decides; activating them works only in the Django admin
today. Deactivating someone who left is the same switch the other way.

**Status:** spec (2026-11-21), the questions answered the same day. Not
built.

**Agent:** a cheaper model following this spec and the checklist in
`AGENTS.md`; deactivating ends access, so have the tests of that
reviewed.

**Depends on:** `ui-round-6.md` (invitations, the invitation mail),
`sso.md` (sessions and tokens), `organizations.md` (the people pages).

## Who and where (decided 2026-11-21)

- **Admins only**, both ways: activating gives someone a way in.
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

## Done when

- Both ways through the pages, the API (single and bulk) and the CLI, as
  admin; staff and clients get 403 (pages: 404 for clients, as the
  people pages).
- Tests: activating with and without the mail (outbox, after the commit,
  nothing on a failed bulk), bounced addresses, deactivating ending
  sessions, tokens, calendar links and websockets, oneself and the last
  admin refused, the filters.
- `docs/` (people) and `SPEC.md`'s backlog item say so.
