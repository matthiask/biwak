# Writing: checklists, the toolbar, pasting

Texts are Markdown (to-do notes, comments, messages, docs, file
descriptions, check-in answers). Three things make writing them easier:
checklists that can be ticked and counted, a small toolbar, and pasting
that keeps bold, emphasis, links and lists.

**Status:** open.

**Agent:** suits a cheaper model following this spec and the checklist
in `AGENTS.md`. Ticking a checkbox changes a text: through the item's
operation, with the same permission and visibility checks.

**Depends on:** nothing new. The live editor (`collaboration.md`) gets
the toolbar and pasting when it's merged; until then, the textareas.

**Touches:**
- `render_markdown` in `biwak/templatetags/biwak.py`, which enables the
  task list plugin;
- a small module for checklists (counting, ticking);
- the to-do, message, doc, file and answer operations (ticking as an
  edit);
- the templates showing texts and rows;
- `frontend/toolbar.js` and `frontend/paste.js`;
- the converter shared with the importer (HTML to Markdown).

## Checklists

- **GitHub's task lists:** `- [ ] open` and `- [x] done`, rendered as
  checkboxes (the `tasklists` plugin of `mdit-py-plugins`), in pages,
  mails (as ☐ and ☑ in the plain text part) and the API's `*_html`.
- **Ticking in place:** people who may change the text (`can_change()`;
  for to-dos everybody who sees them, since to-dos are shared work) tick
  the boxes on the rendered page without opening the editor.
  - A click posts the checkbox's position and the text's current version
    (a hash of the text).
  - The server flips exactly that box through the item's operation, so
    it's an edit like any other: the audit log and the history record
    it, and an `edited` event merges like other edits.
  - If the text changed meanwhile, the server refuses (409) and the page
    reloads the text.
  - Others see a disabled checkbox.
- **Counting:** an item whose text has a checklist shows the count where
  it's listed, as a small signal like the comment count (`glance.md`):
  "2/5" with a checklist icon. That covers to-do rows (lists, board, my
  to-dos), message board rows, the docs and files list, and the search
  results. Counted when the text is saved (`checklist_done`,
  `checklist_total` on the detail models), not on every page view; the
  API returns both.
- **Comments** have checklists too (rendered, tickable by their author
  and staff), not counted on rows.

## The toolbar

A small row of buttons, always visible above every Markdown field
(decided 2026-11-21): bold, italic, link,
heading, bulleted list, numbered list, checklist, quote, code, mention
(@), attach (the existing button moves into it).

- Each button wraps the selection or the current line, the way
  GitHub's toolbar does. It works on the textarea's text, keeps the undo
  history (`execCommand("insertText")` or the `beforeinput` path), and
  never replaces the whole field.
- Keyboard: Ctrl+B, Ctrl+I, Ctrl+Shift+7 (numbered), Ctrl+Shift+8
  (bulleted), Ctrl+Shift+9 (checklist), Tab and Shift+Tab indenting list
  items, and **Ctrl+K** for a link inside a field (decided 2026-11-21:
  in text fields Ctrl+K is "link", elsewhere it opens the palette).
- On phones the toolbar scrolls sideways instead of wrapping.
- One script for all fields (`data-toolbar` on the textarea). The live
  editor gets the same buttons through CodeMirror's commands once it's
  merged.

## Pasting

- **Rich text** (from a web page, a mail, Word, Google Docs): the HTML
  on the clipboard becomes Markdown with the same converter the importer
  uses (`markdownify`, through a small endpoint, so there's one
  converter in Python and no second one in JavaScript). It keeps bold,
  emphasis, links, headings, bulleted, numbered and task lists, quotes,
  code and tables. Everything else becomes plain text: no colors, no
  fonts, no images from other sites.
- **A URL pasted over selected text** makes a link of the selection.
- **Images** on the clipboard become attachments, as today.
- **Ctrl+Shift+V** pastes plain text, unchanged.
- **Plain text** pastes as it is.

## Done when

- **Checklists:**
  - rendering in pages, mails and the API;
  - ticking as staff, as a client on a to-do, and refused for a client
    on someone else's message;
  - the 409 on a changed text;
  - an edit event and history entry per tick;
  - the counts on rows, in a fixed number of queries.
- **The toolbar:** each button, the keyboard, undo after a button, in
  Playwright.
- **Pasting:** in Playwright, HTML from a fixture (a mail, a Google Docs
  fragment) becoming the expected Markdown; URL over selection; plain
  paste.
