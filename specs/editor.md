# Writing: checklists, the toolbar, pasting

Texts are Markdown (to-do notes, comments, messages, docs, file
descriptions, check-in answers). Three things make writing them easier:
checklists that can be ticked and counted, a small toolbar, and pasting
that keeps bold, emphasis, links and lists.

**Status:** built 2026-11-21 (branch `editor`), see "Built" below.

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

## Built (2026-11-21)

- **Checklists** (`biwak/checklists.py`, `render_markdown` with
  `mdit-py-plugins`' `tasklists`): counting, ticking and rendering use the
  same parser, so a checkbox is what the page shows as one (not one in a
  code block). A box is named by its position in reading order. Pages,
  `*_html` (disabled boxes) and mails (HTML and plain text with ☐ and ☑).
- **Counts** are stored by `Checklist.save()` (`checklist_done`,
  `checklist_total` on `Todo`, `Message`, `Doc`, `Upload`; migration
  `items.0007` counts the texts that exist). Rows read them
  (`items/_checklist_signal.html`, `glance.with_checklist()` for items of
  every kind in one query): to-do rows (lists, board, my to-dos), the
  message board and project page, the docs and files list, search results;
  the API returns both numbers (`checklist_done`, `checklist_total`), the
  CLI shows them in `todo show`. Answers have no stored counts (the spec
  doesn't list them on rows).
- **Ticking** (`items.operations.tick()`, `POST /items/<id>/tick/`,
  `frontend/checklist.js`): the page sends the box's index, the hash of
  the text it rendered (`checklists.text_hash()`) and the state to set
  (`checked`, so a repeated click can't flip it back). The operation locks
  the detail row, refuses (409) when the text changed or a doc is locked
  by somebody else, and edits through the item's own operation
  (`update_todo`, `update_message`, `update_doc`, `update_upload`,
  `update_answer`), so it's an edit event (merging like other edits), an
  audit entry and, for docs, a version. Whoever may change the text ticks
  (`can_tick()`: to-dos everybody who sees them, else `can_change()`), 403
  otherwise; others see disabled boxes. Comments: their author and staff,
  an audit entry but no event (comments have no edit events). The peek
  below a row and old doc versions stay read-only. The API has no tick
  endpoint; `PATCH` the text.
- **The toolbar** (`frontend/toolbar.js`, buttons in
  `forms/_toolbar.html`, `data-toolbar` set on every `Textarea` by
  `BootstrapMixin`): one script, edits through
  `execCommand("insertText")` (undo works) and only touches the range it
  changes. Buttons toggle (bold on bold takes it off), line buttons
  replace each other (bullets, numbers, checklist). Roving tab stop, arrows
  move; the attach button moves into the bar (`attachments.js`); the
  mention button only where the field has mentions. Keys as above; Tab
  and Shift+Tab indent only on list lines, elsewhere Tab leaves the
  field. **Ctrl+K** in a field is a link (`palette.js` ignores
  `textarea[data-toolbar]`); Escape leaves the field, so Ctrl+K opens the
  palette again.
- **Pasting** (`frontend/paste.js`, `POST /paste/markdown/`,
  `biwak/htmlmarkdown.py`): the converter moved to `biwak/htmlmarkdown.py`
  (the importer's `Converter` subclasses it). Pasted HTML is cleaned first:
  Google Docs' styled spans become bold, emphasis, strikethrough and code,
  its redirect links are unwrapped, links other than http(s) and mailto,
  images, scripts and styles are dropped, a table's first row becomes the
  header. HTML without anything worth keeping (an editor's div per line)
  pastes as text, so code stays as it is. Files on the clipboard stay
  `attachments.js`'s; Ctrl+Shift+V pastes plain text; a failing endpoint
  pastes the text.
- Tests: `biwak/test_checklists.py`, `biwak/items/test_checklists.py`,
  `test_checklist_rows.py`, `test_checklist_api.py`, `biwak/test_paste.py`
  (fixtures in `biwak/test_fixtures/`), `biwak/test_e2e_editor.py`
  (Playwright: ticking, every toolbar button and key, undo, Ctrl+K, a phone
  width, pasting).
- **Known gap:** ticking doesn't update an edit form that's open on the same
  page; saving it later writes its (older) text. The 409 covers ticks, not
  forms.

## Ticking while someone edits (decided 2026-11-21)

An open edit form is more important than a tick:

- While someone has the item's edit form open, ticks are refused. The
  form announces itself (a small "editing" marker per item and person,
  renewed by the open form every minute, gone 2 minutes after the last
  renewal or when the form is saved or cancelled).
- The person ticking sees why: "Ada is editing this; try again when
  she's done." With live updates (`lantern.md`), the box re-enables when
  the form closes.
- When a tick fails because the text changed since the page was shown,
  the message says who changed it last ("Changed by Bob a moment ago"),
  and the page reloads the text.
- The edit form itself still refuses a stale save (someone else saved
  meanwhile) and says who; ticks made before the form was opened are
  in the form's text.
