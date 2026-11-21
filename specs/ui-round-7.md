# UI round 7: files as tiles, ordering, moving, new docs

Round 7 of `ui-feedback.md` (2026-11-21), the questions answered the same
day.

**Status:** being built (2026-11-21, branch `ui7`). Details marked
"proposed" are the spec writer's, accepted unless noted. Built so far:
part 1 (`files/_tiles.html`, `.wb-tiles` in `main.css`); part 2
(`library.folder_new` and `folder_rename`, `files.operations.update_folder()`,
renaming records `edited` like any edit, in the palette too); part 3
(`Folder.ordering`, `Project.files_ordering`, `files.operations.set_ordering()`,
the "Order…" modals; API: `ordering` in `GET projects/{id}/files/`,
`PATCH projects/{id}/files/` and `PATCH folders/{id}/` with `title` and
`ordering`; CLI 0.36.0: `biwak folder rename`, `biwak folder order`,
"Order:" in `biwak files`). The ordering is just a setting: no event;
the audit trigger still records the column like any other (not left
out, nothing to gain). Part 4 (`frontend/files.js`; `library.files_move`
and `files_trash` taking `items`, `files.operations.move_items()` and
`trash_items()`): only tiles the person may move (`can_change()`, as
"Move to…") are draggable and selectable; a refused or failed drop
reloads the page; selecting a folder and something in it trashes them
together (one `trashed`, restored together). Keyboard: Ctrl+Space and
Shift+arrows (`palette/_shortcuts.html`). The drag's image is the
browser's (one tile) also when several move.

**Agent:** a strong model (drag and drop, a draft doc's life); the
visibility tests reviewed.

**Depends on:** `files.md`, `doc-titles.md`, `subscribers.md`,
`collaboration.md`.

## 1. Files as tiles (decided 2026-11-21: a grid, not the list in a card)

- A folder (and the project's "Docs and files") shows its contents as a
  grid of cards: an icon (folder, doc, file type), an image's preview for
  images (`file_preview`, proposed), the title, below it the size (files)
  or the checklist signal (docs), the client badge. Two to five columns
  by width; one on a phone is a list of compact cards.
- **".."** (decided 2026-11-21): inside a folder, the first tile leads to
  the parent (the project's top level from a first-level folder), also a
  drop target. The breadcrumbs stay.
- Empty: "Nothing here yet." as today.

## 2. Folders through modals

- "New folder" is a button in the header opening a modal (title, visible
  to clients for staff), replacing the form under the list; a folder's
  "Rename…" in its "More" menu, a modal too (`form_response`, as items).

## 3. Ordering per folder (decided 2026-11-21: stored on the folder)

- Choices: alphabetical (the default), reverse alphabetical, newest
  first, oldest first (by creation; proposed: by the last change instead
  would reorder while people work). Folders always come first, in the
  same order.
- Set by staff in the folder's "More" menu ("Order…", a modal); the
  project's top level has it in the header's menu (stored on the
  project). Everybody sees that order. No event, no audit log entry
  needed (decided 2026-11-21: just a setting); the API and CLI read and
  set it with the folder.

## 4. Moving: drag and drop, several at once (decided 2026-11-21)

- Tiles are draggable (who may move them: as "Move to…" today) onto a
  folder tile, the ".." tile or a breadcrumb; dropping moves (the same
  operation as "Move to…", visibility recomputed). No manual order: the
  folder's ordering decides where it shows.
- **Selecting several** (decided 2026-11-21: no checkboxes, it looks
  nicer, at the price of being less discoverable): Ctrl-click (Cmd on a
  Mac) adds or removes a tile, Shift-click selects the range from the
  last one; a plain click opens as before. With a selection a bar shows:
  "Move to…" (the folder choice of today), "Move to trash" and
  "Deselect" (Escape too); dragging one of the selected drags them all.
  Keyboard: Ctrl+Space and Shift+arrows on the focused tile do the same.
  The help says so (`docs/files.md`).
- Without JavaScript: "Move to…" per item as today.

## 4b. Uploading by dropping files (decided 2026-11-21)

- **Dropping files** from the computer anywhere into the window of a
  folder (or the project's "Docs and files") opens an "Upload files"
  modal for that folder; dropping onto a folder tile, ".." or a
  breadcrumb picks that folder instead. "Upload a file" becomes "Upload
  files" (a file input taking several) opening the same modal.
- **The modal** lists the files: each with its name (editable: the
  title, the file name's extension kept) and its size, removable; more
  can be dropped onto it. Below, once for all of them: visible to
  clients (staff, as the folder decides today) and **whom to notify**,
  the choice of "Upload a file" today (nobody, everybody, these people).
- **Uploading:** "Upload" sends them one after another with a progress
  row per file; an error (too big, refused) stays on its row, the others
  go on. The tiles appear when done.
- **One notification for the batch** (decided 2026-11-21): the people
  chosen get one entry in the lantern and one mail, "Ada uploaded 5 files
  to Minutes", listing them (each linking to its file), not one per file.
  The upload's files share a batch (an ID on their events); the lantern
  and the mails merge a batch's events into one entry; the feed merges
  them anyway (same person, action and folder).
- Only for who may upload there; without JavaScript "Upload files" is a
  page with a multiple file input and the same fields.

## 5. New docs (decided 2026-11-21)

Every doc is edited together (the live editor); the new-doc form with a
text field and "whom to notify" goes.

- **"New doc" opens the editor at once** with a doc whose text is `# `
  and the cursor after it: the title is typed first (`doc-titles.md`).
- **The doc exists from the first save on** (decided 2026-11-21: the
  first save puts its address into the browser's history, then it goes
  on as usual). Proposed, to make that work with the live editor: opening
  "New doc" creates a draft at once (the editor needs a doc to sync);
  a draft is nobody's business until it has text beyond `# `: no event,
  not in the folder, the feed, search or the lantern, no notification;
  the page's address is replaced (`history.replaceState`) when it stops
  being a draft. Drafts left empty are deleted by `fairy_tasks` after a
  day. Its visibility: internal (staff can switch it on the doc's page).
- **Telling people:** creating notifies nobody; the creator is the only
  subscriber (decided 2026-11-21). When the creator leaves the editor the
  first time ("Done", the draft having become a doc), a modal "Tell
  people about it?" opens with the subscribers' picker ("add others,
  telling them now", `subscribers.md`): "Tell them" or "Not now", and
  it's never offered again either way (decided 2026-11-21: once, no
  reminder); afterwards the subscribers card works as on every item.
- API and CLI: creating a doc stays as it is (title and text, not a
  draft).

## Done when

- The grid with "..", the modals, the ordering (pages, API, CLI), drag
  and drop and the selection (browser tests for the JavaScript: dragging
  onto a folder, "..", a breadcrumb; Ctrl- and Shift-click selecting
  several and moving them),
  new docs as drafts until written, telling people after "Done"; tests
  as staff and client (clients move only what they may, never see
  others' drafts); the help (`docs/files.md`).
