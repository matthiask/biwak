# A rich-text editor for every text

One rich-text editor that shows what the text will look like, for
every text field, live docs included: we mostly write prose, not code,
and the Markdown source view looks like code (decided 2026-11-22:
ProseMirror, Markdown stored, a source toggle, live docs' conversion in
Python). The toolbar, checklists and pasting: `editor.md`; live docs:
`collaboration.md`.

**Status:** built (2026-11-22).

## Which editor

- **ProseMirror** (decided 2026-11-22). Mature, maintained ("ProseMirror isn't
  going anywhere"), with what we need ready: `y-prosemirror` for the
  live docs, `prosemirror-markdown` for Markdown, input rules, tables
  (`prosemirror-tables`), good IME and mobile support.
- **Wordgard later, maybe.** ProseMirror's author's new editor
  (0.1, 2026-07-02, MIT) is meant to replace it eventually ("Once
  Wordgard is stable, I wouldn't recommend building a new system on
  ProseMirror anymore"), but he says it stays 0.x "likely at least a
  year", the interface will change, and "if you need a stable library,
  you won't want to use an unproven thing like Wordgard". It has no
  Yjs binding and no Markdown parser or serializer yet; touch input and
  mobile composition are still being tested. Its concepts are close to
  ProseMirror's, so porting later is contained if the editor sits
  behind one module of ours (`frontend/editor/`): schema, Markdown,
  toolbar, mentions and attachments go through it, nothing else imports
  ProseMirror. Revisit at Wordgard 1.0.

## Stored as Markdown

Texts stay Markdown in the database (decided 2026-11-22). Everything else reads
Markdown already and stays as it is: rendering (`render_markdown`),
mails, search, the API and CLI (`*` fields and `*_html`), agents, mail
replies, the importer, checklists (counting, ticking by position),
mentions (`[@Ada](person:12)`). The editor parses Markdown into its
document and serializes it back (`prosemirror-markdown`, with our
additions).

- **The schema covers what we render**, no more: paragraphs, headings,
  bold, italic, strikethrough, inline code, code blocks, quotes, links
  (and linkified URLs), bulleted, numbered and task lists (nested),
  tables, hard breaks (our Markdown has `breaks: True`: a single line
  break is a break), images (attachments), mentions as an inline node
  (`[@Ada](person:12)`), horizontal rules. What the schema can't hold
  (raw HTML is off already) stays as text.
- **Round trips must not change texts nobody edited.** Serializing
  normalizes, so opening and saving an unchanged text would record an
  edit, a doc version, events. Rule: the editor (and the source toggle
  switching back) submits the original text when its document is
  unchanged; the server keeps the saved text when new Markdown parses
  to the same document, and the source of unchanged blocks
  (`biwak/richtext/preserve.py`; forms through
  `BootstrapMixin._clean_fields()`, `keep_source()`: only the blocks
  somebody changed are written in the editor's style). The stored text
  keeps its line break at the end when the last block changes (decided
  2026-11-22).
- **Our serializer style** (decided 2026-11-22): `-`
  bullets, `*` emphasis (`_` can't emphasize inside a word), `**`
  strong, a newline for a break (`\` for an empty line), bare URLs
  stay bare, backtick fences, `---` rules; the source's style choices
  kept in the document. On top of prosemirror-markdown's defaults:
  adjacent lists alternate markers,
  compact items with blank lines or numbered sublists, only
  `[@…](person:N)` is a mention, escaping at line starts after a
  break, double breaks, entities and autolinks typed as text, pipes in
  cells, linkifying `www.` and bare domains like the server; images with a
  link keep it as the image's `href` (one schema for fields and live
  docs). Typed bare URLs become links while typing, as the page shows
  them. A line starting with `--` (a mail signature's) is escaped as
  `\--` when its paragraph is saved (the rule for `-` at a line start),
  so pasted mails gain a backslash (confirmed 2026-11-22).
- **One corpus, both sides, in CI:** the same texts (made up: our
  shapes, the help, paste and importer outputs; `biwak/richtext/corpus/`,
  the hooks leave its whitespace alone) and random documents, run
  through the JavaScript and Python serializers
  (`biwak/richtext/test_parity.py` through `frontend/editor/tests/dump.js`):
  byte-identical output, checklist positions equal to
  `checklists.boxes()`. The JavaScript tests run with Node's own runner
  (`frontend/editor/tests/*.test.js`, run by `biwak/richtext/test_js.py`);
  both skip without Node. `prosemirror-markdown` and `markdown-it` are
  pinned exactly.
- **Ticking** keeps working: a box is a task item in reading order,
  the same index the server counts (`biwak/richtext/checklists.py`).

## Everywhere

- Every Markdown `Textarea` (`data-toolbar`: to-do notes, comments,
  messages, docs, file descriptions, check-in answers, inline forms) is
  the editor; the textarea stays in the form, hidden, and gets the
  Markdown on every change, so forms post as before and work without
  JavaScript.
- **Enter starts a paragraph** (decided 2026-11-22, like every rich
  editor), Shift+Enter a line break (not in table cells: Markdown
  can't hold one there), Ctrl+Enter submits.
- **Input rules:** typing Markdown still works (`**bold**`, `# `, `- `,
  `1. `, `[ ] `, `> `, backticks), so nobody has to learn anything.
- **The toolbar** (`editor.md`) is the editor's: the same buttons,
  keys (Ctrl+B, Ctrl+I, Ctrl+K a link, Ctrl+Shift+7/8/9), roving tab
  stop, showing which marks are active. Tab and Shift+Tab indent list
  items, elsewhere Tab leaves the field, also in table cells (arrow
  keys move between cells).
- **Mentions:** typing `@` opens the existing list (`mentions.js`'s
  endpoints) and inserts a mention node; teams expand into their
  members.
- **Attachments:** pasting and dropping files upload
  (`attachments.js`), inserting an image or a link node.
- **Pasting rich text** keeps going through the one converter on the
  server (`/paste/markdown/`, `htmlmarkdown.py`), the result parsed
  into the editor, so pasting behaves the same in every field and the
  importer's converter stays the only one.
- **Pasting plain text that is clearly Markdown** (decided 2026-11-22):
  plain text (nothing richer on the clipboard) is parsed as Markdown
  only when it has unmistakable structure: a heading line (`# ` …), a
  list of several items, a fenced code block, a table, or
  `[text](url)` links. Anything else stays text, so code with `#`
  comments, a mail's `*` or `-` lines and paths with `_` aren't
  formatted. Ctrl+Shift+V always pastes text; undo right after such a
  paste turns it back into the plain text, its Markdown characters
  escaped when saved (`\## Packing`; confirmed 2026-11-22). One
  detection function (`frontend/editor/detect.js`, `isMarkdown()`),
  tested with both kinds of examples (`tests/detect.test.js`).
- **Plain text pasted** that isn't clearly Markdown (confirmed
  2026-11-22) stays text: lines become breaks, blank lines paragraphs;
  Markdown characters in it are not interpreted (they're escaped when
  saved). The "Markdown" switch is the way to paste Markdown source.
- **Tables** (decided 2026-11-22): "Insert table" in the toolbar
  inserts a 2×2 table with a header row. While the cursor is in a
  table, a small bar next to it offers: a row above, a row below, a
  column left, a column right, delete the row, delete the column,
  delete the table, and the column's alignment (left, center, right;
  the active one pressed). Alignment is per column as in Markdown
  (`:---`, `:---:`, `---:`): the editor keeps every cell of a column
  in step, so what's saved is one alignment per column. "Delete row"
  is disabled in the header row (Markdown tables need one); deleting
  the last column deletes the table. The bar's buttons are
  named for screen readers; on phones it wraps. The bar floats above the table at its left edge
  (the surface color, a shadow, like the link's address field), shown
  while the cursor is in a table and the editor or the bar has the
  focus; "Row above" is unavailable in the header row like "Delete
  row" (both dimmed, `aria-disabled`); the icons `arrow-bar-up`,
  `-down`, `-left`, `-right`, `dash-square` (delete row), `x-square`
  (delete column), `trash`, `text-left`/`-center`/`-right`; "Insert
  table" after "Code" (`table`), in the Markdown source an empty
  table's Markdown; alignment pressed again takes it off (confirmed
  2026-11-22). The bar and the table's shape (the first row the header,
  every cell at its column's alignment after any change) are
  `frontend/editor/tables.js`. **Keyboard**
  (decided 2026-11-22): Tab in a cell leaves the field as everywhere;
  **Alt+F10** goes to the bar (the common rich-editor key for a
  toolbar), the arrows, Home and End move in it, Escape goes back to
  the cell, the focus stays in the bar after an action.
- **Forms:** Ctrl+Enter saves, Escape closes (the modal's "changed"
  check compares the Markdown); the inline forms and the view-mode
  edit forms behave as without the editor.
- **A Markdown source toggle** per field ("Markdown" in the toolbar,
  decided 2026-11-22): for the special cases, such as pasting a code
  snippet or fixing something the schema can't show. Not remembered:
  every field opens rich. Switching back parses the source again.
  "Markdown" is the toolbar's last button (an icon, at the right),
  pressed while the source shows; the live doc editor has none (its
  shared document is the editor's; confirmed 2026-11-22).

## Live docs

The shared Yjs document is ProseMirror's (`y-prosemirror`, a
`Y.XmlFragment`), not the Markdown text. The browser:
`frontend/editor/live.js` (`liveEditor()`), `frontend/collab.js` keeps
the connection, the status, attachments and offline storage. The
server reads and writes that document with `pycrdt`
(`biwak/collab/ytext.py` through `biwak/richtext/`), so it needs our
schema in Python:

- **Saving** (`save_live()`): the fragment serialized to Markdown in
  Python (`biwak/richtext/serialize.py`), the same output as the JavaScript serializer (one test corpus
  for both), then the doc operations as now (events per author,
  versions, mentions credited).
- **Edits from elsewhere** (API, CLI, restoring a version, a tick):
  Markdown parsed with `markdown-it-py` (already ours) into the
  fragment's structure and applied as a **deep diff** (decided
  2026-11-22, `biwak/richtext/diff.py`): nodes of the same
  kind paired in the changed ranges, changed attributes set (a tick is
  one), lists and quotes recursed into, paragraphs' and headings'
  characters and marks diffed, also those with mentions, images and
  breaks; a run of text split by a new mention keeps its Y text where
  most of it went. Replacing whole changed top-level blocks would lose
  typing whenever both sides touch the same block (a tick in a list
  while someone types in it). Typing in a block the API deletes is lost
  (accepted).
- **Inline nodes keep what y-prosemirror drops** (decided 2026-11-22):
  it loses marks on inline nodes, so an image's link is an attribute of
  the image node; a mention's bold is dropped (cosmetic).
- **pycrdt counts UTF-8 bytes, Yjs UTF-16 units:** positions are
  converted (`biwak/richtext/ydoc.py`). Also different between the
  sides: markdown-it-py's horizontal rule markup and `\w` in JavaScript
  and Python.
- Cursors and names of others, offline typing (IndexedDB), undo per
  person (`y-prosemirror`'s), read-only and the status line stay.
- **In Python** (decided 2026-11-22), not ProseMirror's JSON stored
  (everything reading texts would need converting) and not a Node
  process (a second service, against `collaboration.md`'s decision).

## Loading

- The editor is its own chunk (`frontend/editor/fields.js`, loaded by
  `main.js` where a `textarea[data-toolbar]` is, also in forms htmx
  brings), parsing Markdown in the browser (decided 2026-11-22: simpler,
  works offline, cached), fields upgraded on load.
  `textarea.richEditor` is the editor, `textarea.focus()` focuses it,
  its `invalid` event and the form's `reset` are followed.
- **Budget** 140 KB gzipped beyond the main bundle (decided 2026-11-22:
  raised from 125 KB rather than trimming; markdown-it's HTML entities
  are the candidate if it ever matters). Measured 2026-11-22 before the
  table tools: 129.6 KB, the live doc page 167 KB.

## The code

`frontend/editor/`: `schema.js` and `markdown.js` (schema, parser,
serializer), `editor.js` (keys), `rules.js` (input rules, Backspace
takes one back), `commands.js` (the toolbar's actions, `aria-pressed`
on what's active), `plugins.js` (linking while typing, task boxes, the
`@` list, pasting), `link.js` (the address field), `tables.js`,
`detect.js`, `live.js`. The toolbar (`toolbar.js`) hands its buttons to
the editor, or to the source while "Markdown" shows it; `mentions.js`
has one list for both (`mentionList()`), `attachments.js` inserts into
either, `paste.js` keeps the converter. Python: `biwak/richtext/`
(`tree.py`, `parse.py`, `serialize.py`, `preserve.py`, `ydoc.py`,
`diff.py`). Browser tests: `biwak/test_e2e_editor.py`; the other
browser tests type into the editor (`E2ETestCase.editor()`,
`set_markdown()`).

**Input methods, phones, other browsers, screen readers:** left to
ProseMirror, which is battle-tested there (decided 2026-11-22: not
checked separately). Composition through Chromium's input method
protocol is tested.

## Choices confirmed by the user (2026-11-22)

- **Looking like the page:** task items show their box as the page
  does (clickable, it ticks in the document), mentions as `@Name` in
  the page's mention style (the label as written, not the current short
  name), tables as plain bordered cells, images through the
  attachment's download URL. Tight lists without paragraph spacing,
  as on the page.
- **The link button and Ctrl+K** open a small address field under the
  selection (Enter sets it, an empty address removes the link, Escape
  or leaving it cancels); nothing selected inserts the address as a
  link.
- **Buttons without a selection:** bold, italic and code apply to what's
  typed next (no "bold" placeholder as in the source); heading is level
  2 and toggles; code on several blocks makes one code block of their
  lines.
