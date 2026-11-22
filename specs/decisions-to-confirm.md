# Decisions to confirm

Decisions made while fixing the findings of the verification round and
the phone and accessibility pass (2026-11-22), without asking first. Each
is built and written into its spec; this list is for the user to go
through. Once confirmed (or changed), delete the entry; git keeps it.

## Made while fixing

### To-dos and filters

- **Completing from a page from before** someone else's change does what
  the button said: "Complete" on a to-do somebody completed meanwhile
  leaves it completed (by them), instead of reopening it (`done=1/0`,
  `todos.md`).
- **"To-dos I assigned" leaves out those you gave yourself** (the spec's
  "to anybody else", as Home), also in the API and the CLI; with
  "Assigned by: Me" the empty "Assigned to" choice is "Anybody" across
  projects too (not "Me", which would show only those you gave
  yourself), so `/todos/?assigned_by=me` is the whole list.
- **Links leave out defaults and empty values**: Home's, the palette's
  and the project page's links, "Assigned to me" and the completed
  to-dos' pages (`/todos/?assigned_by=me`, `?grouping=due`).

### Notifications and files

- **Clients picked for something internal** (with A): the form says
  "Clients can't see it." and the API answers 400, rather than leaving
  them out quietly.
- **Uploads chain the same in mails and the lantern**
  (`lantern.chain()`): a round more than 10 minutes after the one before
  is an entry and a mail of its own, unless it's the same batch (one
  file taking long); a batch's files are always one entry, in the
  lantern too.
- **Restoring a folder** sets the time of the last change of everything
  it brings back, not only its own: an unannounced doc in it is told an
  hour later, and it counts as changed in "latest changed" lists.
- **"Tell people about it?" tells people on "Nothing"** too (the doc's
  `shared` event says `posted`): like posting, unlike "Tell them now" in
  the subscribers box, which stays "except on Nothing".

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
