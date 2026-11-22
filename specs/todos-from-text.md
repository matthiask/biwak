# Adding to-dos from text

Dropping a Markdown or text file (or pasting its text) onto a to-do
list adds its items as to-dos. Asked by the user 2026-11-22, after
Basecamp's version, which makes a new list per heading: here the text
goes into **one existing list**, and **headings become groups**.

**Status:** open.

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
- **Ticked items** (`[x]`) are added as completed (a list moved over
  from elsewhere keeps its state).
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
  entry), the adder subscribed to the to-dos as their creator. Live
  updates reload the list once.
- **Visibility** is the list's: the to-dos inherit it.
- **Who:** whoever may add to-dos to the list. Headings that need a new
  group follow the rule for creating groups (`access.md`: clients only
  in lists they created): otherwise the preview says which headings
  can't become groups and the button stays disabled until they're
  removed or match existing groups.
- **Limits:** questions below.

## API and CLI

- `POST /api/v1/lists/{id}/todos/from-text/` with `text` and `preview`
  (true answers the plan without adding: groups new or existing, to-dos,
  what's left out); the same parser and operation.
- `biwak todos add-from-text LIST [FILE]` (stdin without a file),
  `--preview`, `--json`. `[clients]`. Agents get a simple way to turn a
  plan into to-dos.

## Questions

1. **Limits:** how many to-dos per text and how big a file? Proposed:
   500 to-dos (the biggest template in the account being replaced has
   160) and 200 KB; more is refused with the count.
2. **Ticked items:** added as completed (proposed), or left out?

## Done when

- Parser tests with the examples above (headings to existing and new
  groups, nesting into notes, ticked items, plain lines, paragraphs
  left out, long titles); the operation (one event, silent to-dos,
  visibility, a client's group rule); the modal as staff and client,
  the API with `preview`, the CLI.
- Browser tests for dropping a file onto a list and onto a list on the
  project's lists, and the preview updating (`test_e2e.py`).
- The help's to-dos chapter says how.
