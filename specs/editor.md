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
  the detail row, refuses (409) when the text changed (a doc being
  locked by somebody else was refused too until the doc locks went with
  `collaboration.md`; since the merge, 2026-11-21, read-only docs can't be
  ticked: `can_tick()` is false, the boxes are disabled), and edits through the item's own operation
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
- **Known gap (closed 2026-11-21):** ticking didn't update an edit form
  that's open; see "Ticking while someone edits".

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

**Status:** built 2026-11-21 (branch `tick-editing`).

Built as decided, with these details:

- **The marker** is the table `items.Editing` (migration `items.0008`;
  one row per item and person, not audited: it's transient). Not the
  cache: Django's default cache is per process, so tests and production
  would differ. `biwak/items/editing.py` has `start()`, `stop()`,
  `holders()` (rows renewed within `TTL`, 2 minutes) and `prune()` (the
  daily `fairy_tasks` job deletes the expired rows). `POST
  /items/<id>/editing/` starts or renews it, with `release` ends it.
- **Who sets it:** the edit pages of messages, files and answers set it
  when they render the form (and again when a save is refused). The to-do
  page shows its form all the time, so the form announces itself with the
  first focus or input (`data-editing-lazy`) and ends when the page is
  left. All of it in `frontend/editing.js`: the open form renews every
  minute, Cancel (`data-editing-release`) gives up. Saving ends the
  person's marker in the operations (`update_todo`, `update_message`,
  `update_upload`, `update_answer`).
- **Docs** (merged with the live editor, decided 2026-11-21): whoever is
  connected to the doc's live editor with write access holds the marker.
  The websocket's consumer (`collab.consumers`) sets it when it connects,
  renews it with its access check every minute, and removes it when the
  connection closes or the person may not type anymore (read-only, access
  lost); when one of the person's tabs closes, their other tabs on the doc
  set it again. Chosen over the editor page announcing itself like the
  forms: the server knows when a websocket closes, also when a tab is
  closed without a goodbye, and a crashed process leaves at most `TTL`.
  Watchers (clients, read-only docs) don't block ticks. Saving a doc (the
  API, a tick) doesn't end the marker, the editor stays open. Docs aren't
  locked anymore (`collaboration.md`, "No locks"): the doc's page tells
  who has it open in the editor ("Ada is editing this.", names by
  `people_known_to()`, else "Someone is editing this."; several: "Several
  people are editing this."), and nobody is kept out.
- **Ticks** (`items.operations.tick()`) raise `editing.BeingEdited` while
  anybody's marker is current, the ticker's own included (one rule). Ticks
  of comments don't wait: comments have no edit form. The 409 answers
  `{"message": ..., "reload": bool}`; `frontend/checklist.js` shows the
  message in a `role="status"` span next to the box. "Ada is editing this;
  try again when they're done." (neutral wording instead of "she's", the
  names are of all genders); two or more: "Several people are editing
  this"; the ticker's own form: "You have the edit form of this open; save
  or cancel it first."
- **Names follow the visibility rules:** `editing.name_for()` uses
  `Project.people_known_to()`; clients get "Someone is editing this" and
  "Changed by someone a moment ago" for staff they may not know.
- **A text that changed** (`ChecklistConflict`) carries who changed it last
  (the latest `edited` event of the item, for comments their author) and
  when: "Changed by Bob a moment ago." (or "5 minutes ago"). The page loads
  the page again in the background and replaces the text in place (no
  navigation), the message beside the box.
- **Stale saves:** docs always refused them through the API
  (`base_version`, newest version); in the browser they're edited live. Now the to-do, message, file and answer forms carry `base` (the
  hash of title and text, `editing.version()`) and the operations take
  `base=`: somebody else's save meanwhile raises `editing.StaleEdit`, the
  form shows who and when above the user's text ("Bob changed this a moment
  ago, while you were editing, so your changes weren't saved. Copy your
  text, then reload the page."). A save without `base` (the API, the CLI,
  older forms) isn't checked; the API's `PATCH` has no `base` yet.
- Tests: `biwak/items/test_editing.py` (the marker and its expiry, saving
  and cancelling, refused ticks with names for staff and clients, changed
  texts, the stale save for every kind), `biwak/test_e2e_editor.py`
  (`EditingTest`: two browsers, one editing, one ticking; the reloaded text
  with the message).
