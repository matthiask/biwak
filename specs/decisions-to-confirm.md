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

### Sign-in and people

- **The own organization for clients and partners:** on the People page
  and a project's people page they see it by its name alone, without a
  badge ("Your own organization" stays for its people;
  `organizations.md`).

### Phones and accessibility

- **Doc pages show the title** in the header (an `<h1>`) and leave out
  the text's first line when rendering if it's a heading, so it isn't
  there twice (a first line that isn't a heading stays); the live
  editor's `<h1>` is for screen readers only (`files.md`).
- **x selects a tile** also with shortcuts turned off (it works only on
  the focused tile; `keyboard.md`).
- **The feed's filters on phones** are behind "Filters" (with the count
  of those set), open while one is set; wider screens unchanged
  (`ui.md`, "Filters and view choices").
- **Error pages:** 404 "Not found" ("This page doesn’t exist, or you
  can’t see it.") and 403 "Not allowed" are pages with the bar; 500 is a
  plain page of its own (no database, no request), "Server error".
- **Focus ring:** a 2px outline in the accent's ring color on every
  button, primary ones too, white on the bar.
- **Touch:** hit areas that grow sideways and fill their own line (about
  22px high, never over a neighbour), checkboxes 20px
  on touch screens, the tiles' "…" 36px; Home's "Search Ctrl+K" and
  "Keyboard shortcuts" hidden on phones.
- **Dark mode:** fields `#100e14` (a little darker than cards), dialog
  backdrop 70% black.
- **The palette** uses the pages' yellow "Clients" badge; its hint is
  cut before the title.
- **Full-page forms** (no JavaScript, or a modifier key) show the client
  tab instead of the banner, the same for `modal_form.html`'s page.
