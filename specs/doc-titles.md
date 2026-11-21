# A doc's title is its first line

The idea (user, 2026-11-21): a doc's title sat in a form below the
editor, which is strange; writing a blog entry, the H1 is the title. So
the title is written in the text and pulled out of it.

**Status:** built (2026-11-21). `biwak/files/titles.py` has `doc_title()`
(the first non-empty line: a heading without its `#`s, else the line as
plain text via `excerpt()`, cut at a word boundary below `Item.title`'s
length with "…", "Untitled" when empty) and `with_heading()`. The title
is set in `files.operations._save()`, which every change of a doc's text
goes through (the form's "Save as a version", the live editor's saving,
the API, ticks, restoring a version, the importer's second run);
`create_doc()` prefixes `# <title>` and an empty line itself (form, API,
importer) and sets the title from that. Migration `items/0012` prefixes
existing docs. Decisions on the way: a save that doesn't change the text
keeps the title; the "New doc" form keeps its text field (the text
follows the heading) and opens the editor afterwards; in the API a
`title` next to `content` is ignored, alone it's a 400; the CLI's
`doc edit --title` is gone (0.35.0, `MINIMUM` unchanged: older CLIs
sending `--title` with text still work); the doc pages' header shows the
icon and client badge, no title (not an `h1`: the text has its own).

**Agent:** a cheaper model following this spec and the checklist in
`AGENTS.md`.

**Touches:** `biwak/files/` (the doc's operations, forms, views, API),
the live editor's saving (`biwak/collab/`), `templates/files/doc_live.html`
and the doc's other pages, the importer's docs, `docs/files.md`,
`specs/files.md`.

## Decided (2026-11-21)

- **The title is the text's first line:** a heading (`# Title`, any
  level) without its `#`s; otherwise the first line of text as it is
  (Markdown stripped to plain text, trimmed); a long one is cut at a
  word boundary before the title field's length, with "…". An empty doc is "Untitled". Docs only: messages keep their
  subject field.
- **Stored as today** (`Item.title`): every save of the text (the form,
  the live editor's saving, the API, mail replies if any) sets it in
  the same operation, so lists, the feed, search, mails, bookmarks and
  links go on using `Item.title`. A changed title is an edit like any
  other (no separate "renamed" event).
- **The page shows the title only in the text:** no separate title in
  the doc page's header (the breadcrumbs and the browser's tab title
  use it); the text starts with its heading, as in a blog editor.
- **The title form below the editor goes;** "Save as a version" moves to
  the top, beside the editor's status line.
- **New docs:** the "New doc" form asks for the title as today and the
  doc starts with `# <title>` and an empty line; then the editor opens.
- **Existing docs:** a migration puts `# <title>` and an empty line in
  front of the text of every doc whose first line isn't that title
  already (no users yet, but the import's docs need it), and their
  versions stay as they are.
- **The importer:** Basecamp's documents come in with `# <title>` in
  front of their text (a second import doesn't add it twice).
- **API and CLI:** creating a doc still takes `title` (it becomes the
  heading, as on the page) and `content`; changing a doc's `content`
  sets the title; a `title` alone in a change is refused (400, "the
  title is the text's first line") for docs.

## Done when

- The title follows the first line through every way the text changes
  (form, live editor, API, importer), with tests; the page without the
  title form and with "Save as a version" at the top; the migration
  tested on rows; `files.md` and the help say so.
