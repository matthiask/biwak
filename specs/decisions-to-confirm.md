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

### Phones and accessibility

- **Doc pages show the title** in the header (an `<h1>`, as the findings
  asked) and hide the text's first line when it's a heading, so that it
  isn't there twice; the live editor's `<h1>` is for screen readers only,
  because the editor's first line changes as people type (`files.md`).
- **The feed's filters on phones** are behind "Filters" (with the count
  of those set), open while one is set; wider screens unchanged
  (`ui.md`, "Filters and view choices").
- **Error pages:** 404 "Not found" ("This page doesn’t exist, or you
  can’t see it.") and 403 "Not allowed" are pages with the bar; 500 is a
  plain page of its own (no database, no request), "Server error".
- **Focus ring:** a 2px outline in the accent's ring color on every
  button, primary ones too, white on the bar.
- **Touch:** invisible hit areas around small controls, checkboxes 20px
  on touch screens, the tiles' "…" 36px; Home's "Search Ctrl+K" and
  "Keyboard shortcuts" hidden on phones.
- **Dark mode:** fields `#100e14` (a little darker than cards), dialog
  backdrop 70% black.
- **The palette** uses the pages' yellow "Clients" badge; its hint is
  cut before the title.
- **Full-page forms** (no JavaScript, or a modifier key) show the client
  tab instead of the banner, the same for `modal_form.html`'s page.
