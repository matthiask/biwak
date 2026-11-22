# People: inviting, activating, deactivating, resets

Who gets into Biwak and who leaves: inviting people (several at once),
the invitations still waiting, activating people the importer created
inactive, deactivating people who left, and resetting someone's sign-in. Organizations, the People page and externals are in
`organizations.md`; sign-in in `access.md`.

**Status:** built (2026-11-21). Inviting several: `biwak/projects/invitations.py`
(the form), `invite_people()`, `invite()`, `resend_invitation()`,
`withdraw_invitation()` in `biwak/projects/operations.py`,
`frontend/invite.js`. Activating and deactivating:
`biwak/organizations/activation.py`, the pages in
`biwak/organizations/people.py`, the API in `biwak/organizations/api.py`
(CLI 0.34.0).

## Who may (decided 2026-11-21)

One split for inviting, activating, deactivating and resets
(`activation.can_change()`): staff for clients; admins also for own
staff and externals (people of external organizations); clients and
externals never (`can_manage_members()`: the forms offer everybody,
whom externals mustn't learn about). Putting
people into the own or an external organization is for admins too
(`organizations.md`). Several people at once with someone the actor may
not change is refused as a whole. Pages answer 404 to clients and
externals and 403 to staff for somebody they may not change; the API 403
to both.

## Inviting

- **One flow, two entry points** (decided 2026-11-21): "Invite people"
  on `/people/` (staff choose the projects; also in the palette there)
  and "Invite by email" on a project's people page (that project chosen),
  the same form.
- **A row per person:** address, name, organization (suggested from the
  domain by `for_new_person()`, empty means the domain's; a name that
  doesn't exist asks "Create …?", created only when the round is saved,
  `organizations.md`) and, for admins, staff or client. Three rows
  without JavaScript, the first required, at most 50; an address twice is
  an error of the second row.
- **The projects:** one set for all rows, those the inviter can open and
  not archived, with one "Notified by default / Only when tagged" choice
  for the round, stored per project.
- **All or nothing:** errors per row (a deactivated person's address,
  staff invited by a non-admin, an organization the inviter may not
  touch).
- **The mail:** one per person after the commit, naming the one project
  ("Ada invited you to Website") or, with several, "Ada invited you to
  Biwak" with a line per project. People who already have an account are
  added and get the "added to" notification, no invitation; their
  organization doesn't change.
- The new-project modal invites from its rows the same way
  (`organizations.md`).

## Invitations

- **An invitation** is a person who was invited (`User.invited_by`,
  `invited_at`, set by `invite()`) and has never signed in
  (`User.objects.invited()`). Marked "Invited, not signed in yet" with
  who and when on the project's people page, `/people/` and the person's
  page; `/people/?invited=1` lists them oldest first. The mark is for own
  staff only (clients and externals don't learn who invited whom); Resend
  and Withdraw follow the split above (`can_manage_invitation()`: staff
  for clients, admins for everybody, decided 2026-11-21 after a review),
  on the pages, the API and the CLI.
- **Resend** sends the mail again from the person resending, naming the
  projects they're in now (not archived); "Sent again."; no limit
  (decided 2026-11-21); `invited_by` and `invited_at` stay.
- **Withdraw** (staff, only before they signed in, asking first):
  removes them from all their projects, also those the withdrawing
  person can't open (decided 2026-11-21: "withdrawing is withdrawing";
  it was only the projects the withdrawing person can open), recorded as
  "removed", the "added" events stay. The account goes when nothing
  refers to it (comments, items, events, files, links, assignments,
  check-ins asking them, mentions, reactions); when something does, it
  stays deactivated (decided 2026-11-21: through
  `activation.deactivate()`, so sessions, API tokens and calendar links
  go too). The question says which happens and names the projects the
  withdrawing person can open, counting the others ("2 projects you
  can't open"; confirmed 2026-11-21: admins see every project anyway); the API answers `removed_from` (those IDs),
  `removed_from_others` (the count), `deleted` and `deactivated`.

## Activating

The importer creates people without an account inactive on purpose, so
nobody gets mail or a sign-in before someone decides
(`import-basecamp.md`).

- Sets `is_active`; nothing else changes (memberships, subscriptions,
  assignments made by the import stay). Already active people are
  skipped quietly.
- **The mail is optional** (decided 2026-11-21, a checkbox, off by
  default): the invitation mail above, naming the projects they're in,
  through the outbox; `invited_by` and `invited_at` are set then, so they
  show as invited until they sign in. Not to addresses that bounced
  (`mail_undeliverable_at`): they can be activated, the page says the
  mail wasn't sent, and they aren't marked as invited.
- No event in the feed (it isn't about a project); the audit log records
  the change.

## Deactivating

- Clears `is_active`; refused for oneself (not offered) and for the last
  active admin (an error on the page, 400 in the API). The rows of the
  people and of every active admin are locked first, in the order of
  their IDs (`lock_with_admins()`), so two requests can't each deactivate
  an admin the other counted on (fixed 2026-11-21 after a review). Already inactive
  people are skipped quietly.
- **Ends access at once:** sessions (`UserSession.end()`), API tokens
  and calendar links are deleted; open websockets close through
  `sso.session_alive()` after `live.check_access(user=…)` told them to
  check. Again after the commit (`end_access_now_and_after_commit()`, as
  `sso.enforce_required_now_and_after_commit()`), so what other requests
  made meanwhile goes too.
- Keeps everything they did and what points at them: memberships,
  subscriptions (no mail goes to inactive people), comments and
  assignments, open to-dos' too (decided 2026-11-22, replacing the
  decision of 2026-11-21 to drop them, `handover.md`): they show as
  inactive and are handed over with "Assign…".
- **The question says what's left** (`handover.md`): their open to-dos
  and the projects they're the only active staff member of, in projects
  the deactivating person can open; it never blocks.
- No mail to the person. Reactivating is "Activate" again.
- **The Django admin** follows the same rules (fixed 2026-11-21 after a
  review): unticking "is active" deactivates through `deactivate()`
  (sessions, tokens, calendar links end), not oneself, and neither
  "is active" nor "is admin" can be taken from the last active admin
  (the form says so; `UserAdmin.save_model()` locks the admins first).

## Resetting someone's sign-in

"Reset sign-in…" on the person's page (it was "Reset two-factor…",
renamed 2026-11-21), with the split above: `two-factor.md` says what it
does.

## Pages, API, CLI

- **Pages:** `/people/` has the "Invited" and "Inactive" filters
  (`?invited=1`, `?inactive=1`, "Activate…" per row there); a person's
  page has "Activate…" or "Deactivate…" for whoever may, each a modal,
  also in the palette. Invitations: `/people/invite/`,
  `/projects/<id>/people/invite/`, `/people/<id>/invitation/resend/` and
  `…/withdraw/`.
- **API:** `GET|POST /api/v1/invitations/` (per-row errors as `{"detail",
  "errors": [{"index", "detail"}]}`, 400), `POST
  /api/v1/invitations/{id}/resend/`, `DELETE /api/v1/invitations/{id}/`
  (403 for clients and externals, 404 for people who aren't invitations);
  `GET /api/v1/people/` (active people, `?inactive=true` the inactive
  ones; own staff), `POST /api/v1/people/{id}/activate/` and
  `…/deactivate/`, and in bulk `POST /api/v1/people/activate/` (`ids`,
  `mail`) and `/people/deactivate/` (`ids`), all or nothing.
- **CLI:** `biwak invite EMAIL… --project ID… [--only-tagged]`, `biwak
  invitations [resend|withdraw]`, `biwak people [--inactive]`, `biwak
  people activate ID… [--mail]`, `biwak people deactivate ID…`.
