# Adding to-dos from text

Dropping a Markdown or text file (or pasting its text) onto a to-do
list adds its items as to-dos. Asked by the user 2026-11-22, after
Basecamp's version, which makes a new list per heading: here the text
goes into **one existing list**, and **headings become groups**.

**Status:** built 2026-11-22 (branch `todos-from-text`). The parser
`biwak/items/from_text.py`, the operation `add_from_text()` in
`biwak/items/operations.py`, the modal and preview
`biwak/items/from_text_views.py` (`items/from_text_form.html`,
`items/_from_text_preview.html`), dropping `frontend/from-text.js`
(`items/_drop_text.html`), the event `added_todos`, the API and
`biwak lists add-from-text`.

## Where

- **Dropping a file** (`.md`, `.markdown`, `.txt`, or any `text/*`)
  onto a list's page, in the list or the board view, or onto a list on
  the project's lists: the browser reads it (no upload) and opens the
  modal with its text and that list. Several files at once are joined in
  order, a blank line between. Other files dropped there are refused
  with a message ("Only text files can be added as to-dos."), as drops
  of files are elsewhere.
- **"Add from text…"** in a list's "More" menu and the palette: the
  same modal, empty, with a file input next to the text field. Works
  without JavaScript and on phones (pasting).
- **The modal** (`form_response`): the list (the combobox of lists in
  the project the person may add to-dos to, the one dropped on
  preselected, so another one can be picked), the text (a plain
  textarea, not the editor: it's source), and below it the preview of
  what will be added, updated as the text or the list changes. "Add 12
  to-dos" is the button; nothing is added before.

## Reading the text

One parser (`biwak/items/from_text.py`, markdown-it like the rest), the
same for the modal, the API and the CLI:

- **Headings** (any level, `#` or underlined) become **groups** of the
  list, in their order. A heading matching an existing group of the list
  (ignoring case and surrounding spaces) adds to that group; others
  create a group at the end. Items before the first heading are added
  ungrouped. Levels aren't kept: groups are one level.
- **List items** (`-`, `*`, `+`, `1.`, with or without `[ ]`) become
  **to-dos**, appended at the end of their group in the text's order.
  The first line is the title, as plain text (inline Markdown removed;
  the title of a to-do isn't Markdown); a title over 500 characters is
  cut and the whole line kept in the notes.
- **Ticked items** (`[x]`) are added as completed (decided 2026-11-22:
  a list moved over from elsewhere keeps its state).
- **What's indented under an item** becomes its notes: nested items as
  a checklist (`- [ ]`, ticked ones stay ticked, deeper levels as they
  are), paragraphs and code as written. The same as Basecamp's card
  steps become a checklist (`import-basecamp.md`).
- **Text without any list items** (a plain `.txt`): every non-empty line
  that isn't a heading is a to-do. With list items, other top-level
  paragraphs are left out, and the preview says so ("2 paragraphs
  aren't list items and are left out.").
- No guessing beyond that: no due dates, assignees or repeats from the
  text; "@Ada" stays text. People are assigned afterwards ("Assign…",
  `handover.md`).

## The preview

The list as it will look: groups in order, each marked "new" or
"existing", the to-dos under them with their checklist counts, and a
line on what's left out. Empty text or nothing to add: the button is
disabled and the preview says why.

## Adding

- An operation `add_from_text(todolist, text, *, actor)`,
  `@transaction.atomic`: groups through `create_group()`, to-dos created
  silently like `copy_list()`'s, **one event** "added 12 to-dos to
  Launch" (list subscribers hear about it once, the lantern shows one
  entry), the adder subscribed to the to-dos as their creator, and the
  list's watchers too (decided 2026-11-28, `notifications.md`,
  "Watching a list"). Live updates reload the list once.
- **Visibility** is the list's: the to-dos inherit it.
- **Who:** whoever may add to-dos to the list. Headings that need a new
  group follow the rule for creating groups (`access.md`: clients only
  in lists they created): otherwise the preview says which headings
  can't become groups and the button stays disabled until they're
  removed or match existing groups.
- **Limits** (decided 2026-11-22): 500 to-dos per text, files up to
  200 KB; more is refused with the count ("This text has 640 to-dos; up
  to 500 can be added at once.").

## API and CLI

- `POST /api/v1/lists/{id}/todos/from-text/` with `text` and `preview`
  (true answers the plan without adding: groups new or existing, to-dos,
  what's left out); the same parser and operation.
- `biwak lists add-from-text LIST [FILE]` (stdin without a file; next to
  `biwak lists copy`: it acts on a list, decided 2026-11-22),
  `--preview`, `--json`. `[clients]`. Agents get a simple way to turn a
  plan into to-dos.

## Decided while building (confirmed by the user 2026-11-22)

- **The event** is a new action `added_todos` on the list ("Bob added 12
  to-dos to Launch", mails "Bob added 12 to-dos."), not `added`, which
  is the project's "added a person" and would merge with it in the feed.
- **Only active lists** in projects that aren't archived: archived ones
  aren't offered (menu, palette, drops, the combobox) and the operation
  refuses them ("No to-dos can be added to this list.").
- **Groups:** a heading's title is cut at 200 characters (the field);
  an empty heading is ignored (the items stay where they were); a heading
  without items still makes its group; the same heading twice is one
  group. Two existing groups of the same name: the first.
- **Plain text mode:** lines of code blocks count as lines too; a
  horizontal rule is neither a to-do nor "left out". With list items,
  code blocks, quotes and tables at the top level count as "paragraphs
  left out".
- **Titles:** a title over 500 characters is cut with "…". An item whose
  first line isn't a paragraph (`- ```…`) takes the line as written.
  The rest of the first paragraph (lines after the first) goes into the
  notes.
- **Wording:** "Paste a text or choose a file." (empty), "This text has
  no to-dos.", "This text is larger than 200 KB; up to 200 KB can be
  added at once." (and "This file …"), "This file can’t be read as text
  (UTF-8).", for clients "Only the list’s creator can add groups. Remove
  these headings or use the names of existing groups: …", the badges
  "new" and "existing", the button "Add to-dos" while there's nothing.
  German: "Aus Text hinzufügen…", "Listenpunkte", "bestehend".
- **Without JavaScript** the button is always enabled; posting shows the
  problem and the preview. The file input posts the file, its text added
  after the typed text; with JavaScript the chosen file is read into the
  text field (after what's there) and not uploaded. Files can also be
  dropped onto the modal's form.
- **The API** answers `200` for a preview (with `problem`), `201` when
  added, `400` with the problem otherwise; groups carry `id` (existing,
  or created), `new`, and the to-dos their IDs once added.

## Done when

- Parser tests with the examples above (headings to existing and new
  groups, nesting into notes, ticked items, plain lines, paragraphs
  left out, long titles); the operation (one event, silent to-dos,
  visibility, a client's group rule); the modal as staff and client,
  the API with `preview`, the CLI.
- Browser tests for dropping a file onto a list and onto a list on the
  project's lists, and the preview updating (`test_e2e_from_text.py`).
- The help's to-dos chapter says how.
