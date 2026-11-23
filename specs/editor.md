# Writing: checklists, the toolbar, pasting

Texts are Markdown (to-do notes, comments, messages, docs, file
descriptions, check-in answers). Decided 2026-11-21: GitHub's task
lists in all texts, tickable in place and counted on rows; a small
toolbar on every Markdown field; pasting rich text keeps the structure.

**Status:** built (2026-11-21).

## Checklists

- **GitHub's task lists** (`- [ ] open`, `- [x] done`, `mdit-py-plugins`'
  `tasklists` in `render_markdown`), in pages, mails (☐ and ☑ in the
  plain text) and the API's `*_html` (disabled). Counting, ticking and
  rendering use the same parser (`biwak/richtext/checklists.py`), so a box is
  what the page shows as one (not one in a code block); a box is named
  by its position in reading order.
- **Counts** are stored when the text is saved (`Checklist.save()`:
  `checklist_done`, `checklist_total` on `Todo`, `Message`, `Doc`,
  `Upload`; a detail model with such a text inherits `Checklist`) and
  shown as "2/5" on rows (`items/_checklist_signal.html`,
  `glance.with_checklist()`): to-do rows, the message board and project
  page, docs and files, search results; the API returns both. Answers
  and comments aren't counted.
- **Ticking in place** (`items.operations.tick()`, `POST
  /items/<id>/tick/`, `frontend/checklist.js`): the page sends the box's
  index, the hash of the text it rendered (`checklists.text_hash()`) and
  the state to set (so a repeated click can't flip it back). The
  operation locks the detail row, refuses (409) when the text changed,
  and edits through the item's own operation, so a tick is an edit like
  any other: an event (merging like edits), an audit entry, a doc
  version. Who may change the text ticks (`can_tick()`: to-dos everybody
  who sees them, since to-dos are shared work; else `can_change()`),
  others see disabled boxes. Comments: their author and staff, no event.
  The peek, old doc versions and read-only docs can't be ticked. The API
  has no tick endpoint: `PATCH` the text.

## Ticking while someone edits

Decided 2026-11-21: an open edit form is more important than a tick.

- **The editing marker** (`items.Editing`, `biwak/items/editing.py`, a
  table, not the cache, which is per process): one row per item and
  person, renewed every minute by the open form (`frontend/editing.js`,
  `POST /items/<id>/editing/`), gone 2 minutes after the last renewal,
  when the form is saved or cancelled; `fairy_tasks` prunes. The click-
  to-edit form sets it when rendered; the view sets none.
- **Ticks are refused** while anybody holds a marker on a to-do,
  message, file or answer (the ticker's own included): "Ada is editing
  this; try again when they're done." / "Several people are editing
  this" / "You have the edit form of this open; save or cancel it
  first." With live updates the box re-enables when the form closes.
- **A text that changed** says who changed it last and when ("Changed by
  Bob a moment ago."), and the page reloads the text in place.
- **Names follow the visibility rules** (`editing.name_for()`,
  `people_known_to()`): otherwise "Someone".
- **Stale saves:** the forms of to-dos, messages, files and answers
  carry `base` (`editing.version()`, a hash of title and text); somebody
  else's save meanwhile raises `StaleEdit` and the form says who
  ("…so your changes weren't saved. Copy your text, then reload the
  page."). Saves without `base` (the API, the CLI) aren't checked; docs
  have `base_version` in the API.
- **Docs: ticks never wait** (decided 2026-11-21): the live editor's
  consumer holds the marker for everybody connected with write access,
  but only for the heads-up ("Ada is editing this.") on the doc's page.
  A tick goes into the open editors as a Yjs update
  (`files.operations.tick_doc()`, `live.apply_text`), so nothing is
  overwritten; a page showing the editors' live text ticks against it
  (`live.apply_live_text`).

## The toolbar

Since 2026-11-22 the fields are the rich editor (`rich-editor.md`): the
buttons and keys below act on its document (`frontend/editor/commands.js`),
and on the Markdown source as described here while its "Markdown"
switch shows the source.

Always visible above every Markdown field (`data-toolbar`, set on every
`Textarea` by `BootstrapMixin`; `frontend/toolbar.js`,
`forms/_toolbar.html`): bold, italic, link, heading, bulleted, numbered
and checklist, quote, code, mention (where the field has mentions),
attach.

- Buttons wrap the selection or the current line like GitHub's and
  toggle; they edit through `execCommand("insertText")`, so undo works,
  and only touch the range they change.
- Keys: Ctrl+B, Ctrl+I, Ctrl+Shift+7/8/9 (numbered, bulleted,
  checklist), Alt+F10 in a table its bar (`rich-editor.md`), Tab and
  Shift+Tab indent list lines (elsewhere Tab leaves the field),
  **Ctrl+K** a link (decided 2026-11-21: in fields Ctrl+K is
  "link", elsewhere the palette; Escape leaves the field).
- Roving tab stop. On narrow screens the toolbar wraps into a second
  row (decided 2026-11-21), the paperclip always reachable.
- The live editor has the same toolbar (`attachToEditor()`,
  `collaboration.md`).

## Pasting

`frontend/paste.js`, `POST /paste/markdown/`, `biwak/richtext/htmlmarkdown.py`
(the one converter, the importer's subclasses it; none in JavaScript):

- **Rich text** (web pages, mails, Word, Google Docs) keeps bold,
  emphasis, strikethrough, links, headings, lists and task lists,
  quotes, code and tables; everything else becomes plain text (no
  colors, fonts or images from other sites). Google Docs' styled spans
  and redirect links are cleaned; only http(s) and mailto links stay.
  HTML without anything worth keeping pastes as text, so code stays as
  it is. A failing endpoint pastes the text.
- **A URL over selected text** makes a link; **images** become
  attachments; **Ctrl+Shift+V** pastes plain text.
- **In the rich editor** (`rich-editor.md`) the converter's Markdown is
  parsed and inserted as blocks or inline; plain text stays text (lines
  are breaks, blank lines paragraphs) unless it is clearly Markdown
  (`rich-editor.md`, decided 2026-11-22); copies from the editor itself
  paste as they are, mentions included (decided 2026-11-22, to confirm).
