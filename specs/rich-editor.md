# A rich-text editor for every text

Replacing the Markdown source editing (CodeMirror in live docs, plain
textareas with the toolbar everywhere else) with one rich-text editor
that shows what the text will look like: we mostly write prose, not
code, and the source view looks like code. One editor for every text
field, live docs included. Asked by the user 2026-11-22.

**Status:** open (decided with the user 2026-11-22: ProseMirror,
Markdown stored, a source toggle, live docs' conversion in Python).

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
  normalizes (`*` vs `_`, list markers, escaping, numbering), so
  opening and saving an unchanged text would record an edit, a doc
  version, events. Rule: the editor submits the original text when its
  document is unchanged; a test suite round-trips a corpus of our own
  texts (and imported ones) and lists what changes, and the serializer
  is configured to our style (`-` bullets, `**`, `_`?) so the first
  real edit changes little.
- **Ticking** keeps working: a box is a task item in reading order,
  the same index the server counts (`biwak/checklists.py`).

## Everywhere

- Every Markdown `Textarea` (`data-toolbar` today: to-do notes,
  comments, messages, docs, file descriptions, check-in answers,
  inline forms) becomes the editor; the textarea stays in the form,
  hidden, and gets the Markdown on every change, so forms post as now
  and work without JavaScript.
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
  fragment's structure. Today a three-way text merge keeps unsaved
  typing; with a tree, proposed: replace only the top-level blocks
  that differ (a block diff), so typing in other blocks stays.
- **Existing live states** are rebuilt from `Doc.content` once (a
  migration; there are no users yet).
- Cursors and names of others, offline typing (IndexedDB), undo per
  person (`y-prosemirror`'s), read-only and the status line stay.
- **In Python** (decided 2026-11-22), not ProseMirror's JSON stored
  (everything reading texts would need converting) and not a Node
  process (a second service, against `collaboration.md`'s decision).

## Loading

- The editor is its own chunk, loaded on pages with a text field
  (most pages: comments). Proposed: fields upgrade on load (no jump on
  the first click); the bundle grows by roughly ProseMirror's size, to
  be measured, Yjs only on live docs as now.

## Questions while building

- Anything that should look or behave differently from the Markdown it
  stands for (how mentions, task lists or tables look while editing):
  ask, don't decide.

## Done when

- Every Markdown field and the live doc editor are the rich editor,
  behind `frontend/editor/` (nothing else imports ProseMirror); the
  forms still post Markdown and work without JavaScript.
- A corpus of texts (our tests' and imported Basecamp shapes)
  round-trips: unchanged texts are submitted unchanged, and the
  JavaScript and Python serializers give the same Markdown for the same
  document (tests on both sides with the same files).
- The toolbar, its keys, input rules, mentions (with teams),
  attachments, pasting through `/paste/markdown/`, ticking, Ctrl+Enter
  and Escape behave as `editor.md` says (browser tests).
- The source toggle switches both ways without losing anything the
  schema holds.
- Live docs: several editors type at once, saving writes the same
  Markdown as before, edits from the API, the CLI, restoring and ticks
  arrive in open editors without losing typing in other blocks;
  offline typing is kept; existing live states are rebuilt.
- `editor.md`, `collaboration.md` and the help say what's built;
  the bundle's size is measured and written down.
