# A rich-text editor for every text

Replacing the Markdown source editing (CodeMirror in live docs, plain
textareas with the toolbar everywhere else) with one rich-text editor
that shows what the text will look like: we mostly write prose, not
code, and the source view looks like code. One editor for every text
field, live docs included. Asked by the user 2026-11-22.

**Status:** built 2026-11-22; open: pasting Markdown detected, the
table tools (both decided 2026-11-22). (Decided with the user 2026-11-22:
ProseMirror, Markdown stored, a source toggle, live docs' conversion in
Python; a spike confirmed it with the changes below; the choices made
while building confirmed 2026-11-22). What was built and the sizes:
"What's built" below.

Depends on: `editor.md` (the toolbar, checklists, pasting),
`collaboration.md` (live docs: Yjs, `pycrdt`, saving),
`notifications.md` (mentions), `files.md` (attachments, docs' titles),
`connection.md` (unsent typing), `keyboard.md`, `ui.md`.

## Which editor

- **ProseMirror now** (decided 2026-11-22). Mature, maintained ("ProseMirror isn't
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
  (`pymd/preserve.py` in the spike).
- **Our serializer style** (decided 2026-11-22 after the spike): `-`
  bullets, `*` emphasis (`_` can't emphasize inside a word), `**`
  strong, a newline for a break (`\` for an empty line), bare URLs
  stay bare, backtick fences, `---` rules; the source's style choices
  kept in the document. With the spike's nine fixes on top of
  prosemirror-markdown's defaults (adjacent lists alternate markers,
  compact items with blank lines or numbered sublists, only
  `[@…](person:N)` is a mention, escaping at line starts after a
  break, double breaks, entities and autolinks typed as text, pipes in
  cells, linkifying `www.` and bare domains like the server). Typed
  bare URLs become links while typing, as the page shows them.
- **One corpus, both sides, in CI:** the same texts (made up: our
  shapes, the help, paste and importer outputs) and random documents,
  run through the JavaScript and Python serializers: byte-identical
  output, checklist positions equal to `checklists.boxes()`.
  prosemirror-markdown pinned.
- **Ticking** keeps working: a box is a task item in reading order,
  the same index the server counts (`biwak/checklists.py`).

## Everywhere

- Every Markdown `Textarea` (`data-toolbar` today: to-do notes,
  comments, messages, docs, file descriptions, check-in answers,
  inline forms) becomes the editor; the textarea stays in the form,
  hidden, and gets the Markdown on every change, so forms post as now
  and work without JavaScript.
- **Enter starts a paragraph** (decided 2026-11-22, like every rich
  editor), Shift+Enter a line break (not in table cells: Markdown
  can't hold one there), Ctrl+Enter submits.
- **Input rules:** typing Markdown still works (`**bold**`, `# `, `- `,
  `1. `, `[ ] `, `> `, backticks), so nobody has to learn anything.
- **The toolbar** (`editor.md`) becomes the editor's: the same buttons,
  keys (Ctrl+B, Ctrl+I, Ctrl+K a link, Ctrl+Shift+7/8/9), roving tab
  stop, showing which marks are active. Tab and Shift+Tab indent list
  items, elsewhere Tab leaves the field.
- **Mentions:** typing `@` opens the existing list (`mentions.js`'s
  endpoints) and inserts a mention node; teams expand as now. The live
  editor gains mentions this way.
- **Attachments:** pasting and dropping files upload as now
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
  paste turns it back into the plain text. One detection function,
  tested with both kinds of examples.
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
  reachable by keyboard (a roving tab stop like the toolbar) and named
  for screen readers; on phones it wraps.
- **Forms:** Ctrl+Enter saves, Escape closes as now (the modal's
  "changed" check compares the Markdown); the inline forms' and the
  view-mode edit forms' behaviour stays.
- **A Markdown source toggle** per field ("Markdown" in the toolbar,
  decided 2026-11-22): for the special cases, such as pasting a code
  snippet or fixing something the schema can't show. Not remembered:
  every field opens rich. Switching back parses the source again.

## Live docs

The shared Yjs document becomes ProseMirror's (`y-prosemirror`, a
`Y.XmlFragment`) instead of the Markdown text (`Y.Text`). The server
reads and writes that document with `pycrdt`, so it needs our schema
in Python:

- **Saving** (`save_live()`): the fragment serialized to Markdown in
  Python, the same output as the JavaScript serializer (one test corpus
  for both), then the doc operations as now (events per author,
  versions, mentions credited).
- **Edits from elsewhere** (API, CLI, restoring a version, a tick):
  Markdown parsed with `markdown-it-py` (already ours) into the
  fragment's structure and applied as a **deep diff** (decided
  2026-11-22 after the spike, `pymd/blockdiff.py`): nodes of the same
  kind paired in the changed ranges, changed attributes set (a tick is
  one), lists and quotes recursed into, paragraphs' and headings'
  characters and marks diffed, also those with mentions, images and
  breaks. Replacing whole changed top-level blocks lost typing whenever
  both sides touched the same block (a tick in a list while someone
  types in it). Typing in a block the API deletes is lost (accepted).
- **Inline nodes keep what y-prosemirror drops** (decided 2026-11-22):
  it loses marks on inline nodes, so an image's link is an attribute of
  the image node; a mention's bold is dropped (cosmetic).
- **pycrdt counts UTF-8 bytes, Yjs UTF-16 units:** positions are
  converted (the spike's trap, with markdown-it-py's horizontal rule
  markup and `\w` meaning different things in JavaScript and Python).
- **Existing live states** are rebuilt from `Doc.content` once (a
  migration; there are no users yet).
- Cursors and names of others, offline typing (IndexedDB), undo per
  person (`y-prosemirror`'s), read-only and the status line stay.
- **In Python** (decided 2026-11-22), not ProseMirror's JSON stored
  (everything reading texts would need converting) and not a Node
  process (a second service, against `collaboration.md`'s decision).

## Loading

- The editor is its own chunk, loaded on pages with a text field
  (most pages: comments), parsing Markdown in the browser (decided
  2026-11-22: simpler, works offline, cached), fields upgraded on load.
  The spike measured about 123 KB gzipped (the main bundle is 34 KB),
  the live doc chunk 161 KB (136 today); budget 125 KB, measured again
  with the toolbar, mentions and attachments.

## What's built

- **The Markdown layer** (stage 1): `frontend/editor/schema.js` and
  `markdown.js` (schema, parser, our serializer with the spike's nine
  fixes, linked images as the image's `href`), the same in Python in
  `biwak/richtext/` (`tree.py`, `parse.py`, `serialize.py`,
  `preserve.py` keeping the old text and unchanged blocks' source,
  `ydoc.py` for y-prosemirror's fragment). The corpus is
  `biwak/richtext/corpus/` (made up; the hooks leave its whitespace
  alone). Tests: `frontend/editor/tests/*.test.js` with Node's own runner
  (no JavaScript test setup before; `biwak/richtext/test_js.py` runs it
  in the Django tests), `biwak/richtext/test_parity.py` compares both
  sides through `tests/dump.js` (corpus and 300 random documents:
  documents, Markdown, Y documents both ways, checklist positions equal
  to `checklists.boxes()`). Both skip without Node.
  `prosemirror-markdown` and `markdown-it` are pinned exactly.

- **The field editor** (stage 2): `frontend/editor/fields.js` (a chunk,
  `editor`, loaded by `main.js` where a `textarea[data-toolbar]` is,
  also in forms htmx brings), `editor.js` (keys: Enter a paragraph or a
  new item, a task item after a task item; Shift+Enter a break, not in
  cells; Ctrl+Enter and Escape left to the form), `rules.js` (input
  rules, Backspace takes one back), `commands.js` (the toolbar's
  actions, `aria-pressed` on what's active), `plugins.js` (bare URLs
  linked while typing like linkify, task boxes tick, the `@` list,
  pasting), `link.js` (the address field). The textarea stays, hidden;
  `textarea.richEditor` is the editor, `textarea.focus()` focuses it,
  its `invalid` event and the form's `reset` are followed. The
  toolbar (`toolbar.js`) hands its buttons to the editor, or to the
  source while "Markdown" shows it; `mentions.js` has one list for
  both (`mentionList()`), `attachments.js` inserts into either,
  `paste.js` keeps the converter. Forms keep the source of unchanged
  blocks on the server (`BootstrapMixin._clean_fields()`,
  `richtext.preserve.keep_source()`). Browser tests:
  `biwak/test_e2e_editor.py` (toolbar, keys, typing, unchanged texts,
  the source, pasting into lists and tables, input methods); the other
  browser tests type into the editor (`E2ETestCase.editor()`,
  `set_markdown()`).

- **Live docs** (stage 3): `frontend/editor/live.js` (`liveEditor()`:
  y-prosemirror's sync, cursors and undo on the doc's fragment),
  `frontend/collab.js` keeps the connection, the status, attachments
  and offline storage; CodeMirror and `y-codemirror.next` are gone. The
  server: `collab/ytext.py` reads and writes the fragment through
  `biwak/richtext/` (`ydoc.py` in UTF-8 positions, `diff.py` the deep
  diff, `preserve.py` keeping the stored text), `collab.0004` rebuilt
  the states. Tests: `richtext/test_diff.py` (the spike's table plus
  mentions, images, breaks and characters outside the Basic Plane, the
  merged states read by y-prosemirror), the consumer's and `live`'s
  tests with a Python client typing into the fragment, the browser's
  `CollabTest` (typing at once, cursors, undo per person, composing
  beside somebody typing, offline, ticks and API edits arriving).

- **Sizes** (measured 2026-11-22, production bundle, gzip -9): a page
  with a text field loads 129.6 KB of editor chunks beyond the main
  bundle (34 KB): ProseMirror, markdown-it and prosemirror-markdown
  117.5 KB, our editor modules 9.4 KB, the field code 2.7 KB; over the
  budget of 125 KB by about 5 KB (markdown-it's HTML entities and
  prosemirror-tables are the candidates if it matters). The live doc
  page loads 167 KB (Yjs and y-prosemirror 37.6 KB more; CodeMirror's
  was 136 KB).
- **Tried in a browser** (Chromium through Playwright): composition
  through the input method protocol (in a field, in a list with bold,
  in a live doc while somebody else types in the same paragraph), undo
  per person in live docs, the others' cursors with names, pasting into
  lists and table cells, our CSS (screenshots). **Not verified:** real
  input methods and phone keyboards (Android's composition, iOS's
  Enter), Safari and Firefox, screen readers with the editor.
- **Decided on the way** (2026-11-22): images with a link keep it as the
  image's `href` also in fields (one schema); the stored text keeps its
  line break at the end when the last block changes; forms keep the
  source of unchanged blocks on the server (`keep_source()`); a run of
  text split by a new mention keeps its Y text where most of it went
  (the deep diff's pairing).

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
- **"Markdown"** is the toolbar's last button (an icon, at the right),
  pressed while the source shows; the live doc editor has none (its
  shared document is the editor's).
- **Plain text pasted** (no formatting on the clipboard, Ctrl+Shift+V)
  stays text: lines become breaks, blank lines paragraphs; Markdown
  characters in it are not interpreted (they're escaped when saved).
  The "Markdown" switch is the way to paste Markdown source.
- **Buttons without a selection:** bold, italic and code apply to what's
  typed next (no "bold" placeholder as in the source); heading is level
  2 and toggles; code on several blocks makes one code block of their
  lines.
- **Tab in table cells** leaves the field like elsewhere (the spec's
  rule); arrow keys move between cells.
- **Saving through forms keeps unchanged blocks' source** on the server
  (`BootstrapMixin`, `richtext.preserve.keep_source()`): only the
  blocks somebody changed are written in the editor's style.
- **A line starting with `--`** (a mail signature's) is escaped as
  `\--` when its paragraph is saved (the serializer's rule for `-` at a
  line start), so pasted mails gain a backslash.
