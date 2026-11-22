# Decisions to confirm

Decisions made while fixing the findings of the verification round and
the phone and accessibility pass (2026-11-22), without asking first. Each
is built and written into its spec; this list is for the user to go
through. Once confirmed (or changed), delete the entry; git keeps it.

## Made before the fixes

- **A. Clients in "will be told" at the top level.** Ticking "Visible to
  clients" on a new message or upload at the top level lists the clients
  who'll be told and lets "Also tell…" offer clients of the project; the
  line follows the checkbox.
- **B. A to-do moved and moved back** within the 10 minutes shows no
  line in the timeline, the same as completing and reopening.
- **C. Confirming who you are with a passkey** (before sensitive
  changes) needs the PIN or fingerprint, as signing in does
  (`MFA_WEBAUTHN_USER_VERIFICATION = "required"`).
- **D. Links inside sentences** are underlined (text in the feed, Home,
  comments, help); links that are a row, a title or navigation are not.
- **E. A project's people page:** "Invite" and "Organizations" in the
  header; a person's role is changed through a "…" menu on their row,
  opening a modal, instead of a select and Save on every row.

## Made while fixing

### To-dos and filters

### Notifications and files

### Sign-in and people

- **The own organization for clients and partners:** on the People page
  and a project's people page they see it by its name alone, without a
  badge ("Your own organization" stays for its people;
  `organizations.md`).
- **E, as built:** "Add someone" moved into the header too, beside
  "Invite by email" and "Organizations", all quiet (two actions add
  people, so none is primary). The row's "…" menu has "Notifications…"
  (the "role" was the notification choice) and "Remove from the project"
  or "Leave the project", still without asking, as before; the choice
  shows as a quiet line under the name (`organizations.md`).

### Phones and accessibility
