# UI round 6: finding people, inviting several, subscribing is the switch

Round 6 of `ui-feedback.md` (2026-11-21). Built 2026-11-21. Where it
lives now:

- **A, a combobox for long selects** (`ComboboxSelect`,
  `frontend/combobox.js`): `core.md` ("Pages").
- **B, inviting several people at once, invitations visible:** to move
  into `organizations.md` (the People page) or `activation.md`, below.
- **C, subscribing is the switch** (subscribed means notified of
  everything on the item; levels only on projects and lists, deciding
  who gets subscribed automatically): in `notifications.md` and
  `subscribers.md`; the check-ins' part in `checkins.md`. One detail to
  move, below.

## To move after the builds

Into `organizations.md` or `activation.md` (part B):

- **One flow, two entry points** (decided 2026-11-21): "Invite people"
  on `/people/` (staff, choosing the projects) and "Invite by email" on a
  project's people page (that project chosen); the same form
  (`biwak/projects/invitations.py`, `invite_people()`, `invite()` on top
  of it, `frontend/invite.js`).
- **A row per person:** email, name, organization (suggested from the
  domain by `for_new_person()`, left empty means the domain's; a name
  that doesn't exist asks "Create …?", created only when the round is
  saved) and, for admins, staff or client. Three rows without
  JavaScript, the first required, at most 50; an address twice is an
  error of the second row.
- **The projects:** one set for all rows, those the inviter can open and
  not archived, with one "Notified by default / Only when tagged" choice
  for the round stored per project.
- **Sending:** one mail per person after the commit, naming the one
  project ("Ada invited you to Website") or, with several, "Ada invited
  you to Biwak" with a line per project. People with an account are
  added and get the "added to" notification, no invitation.
- **All or nothing:** errors per row (a deactivated person's address,
  staff invited by a non-admin, an organization they may not touch);
  only admins invite staff and put people into the own organization;
  clients don't invite.
- **An invitation** is a person who was invited (`User.invited_by`,
  `invited_at`, set by `invite()`) and has never signed in
  (`User.objects.invited()`). Marked "Invited, not signed in yet" with
  who and when on the project's people page, `/people/` and the
  person's page; `/people/?invited=1` lists them oldest first. The mark,
  Resend and Withdraw are for own staff only (clients and partners don't
  learn who invited whom).
- **Resend** sends the mail again from the person resending, naming the
  projects they're in now (not archived); "Sent again."; no limit
  (decided 2026-11-21); `invited_by`/`invited_at` unchanged.
- **Withdraw** (staff, only before they signed in, asking first):
  removes them from the projects the withdrawing person can open
  (recorded as "removed", the "added" events stay); the account goes
  when they're in no other project and nothing refers to it (comments,
  items, events, files, links, assignments, check-ins asking them,
  mentions, reactions). The question says which of the two happens.
- **API and CLI:** `GET|POST /api/v1/invitations/` (per-row errors as
  `{"detail", "errors": [{"index", "detail"}]}`, 400), `POST
  /api/v1/invitations/{id}/resend/`, `DELETE /api/v1/invitations/{id}/`;
  403 for clients and partners, 404 for people who aren't invitations.
  `biwak invite EMAIL… --project ID… [--only-tagged]`, `biwak
  invitations [resend|withdraw]`. The palette offers "Invite people" on
  `/people/`.

Into `notifications.md` (part C): folders have no level of their own,
they follow the project's (confirmed 2026-11-21).
