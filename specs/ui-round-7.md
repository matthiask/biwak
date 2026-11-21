# UI round 7: files as tiles, ordering, moving, new docs

Round 7 of `ui-feedback.md` (2026-11-21), the questions answered the same
day.

**Status:** spec (2026-11-21). Not built. Details marked "proposed" are
the spec writer's.

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

- Files dragged from the computer onto a folder's grid upload into that
  folder, onto a folder tile (or "..", a breadcrumb) into that one;
  several at once. A drop zone shows while dragging, each file gets a
  progress row, and its tile appears when it's done; an error (too big,
  refused) says so on its row.
- The same upload operation as "Upload a file", with its defaults
  (proposed): no description, visible as the folder decides today,
  nobody notified; changing that afterwards on the file's page. Only for
  who may upload there.

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
