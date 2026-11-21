# Search

Finding things across projects: a to-do, a message, a doc, a file, a
comment, a check-in answer, by words in their title or text.

**Status:** built (2026-11-20; archived left out by default since
2026-11-21): `biwak/search/`.

## Decided

- **PostgreSQL full-text search**, no outside service (2026-11-20). The
  `simple` configuration with prefix matching, the same for every
  language (English and German texts), no stemming.
- **Newest first** by `updated_at`, not by relevance; 50 results per
  page, excerpts of 200 characters, like the feed (confirmed
  2026-11-21).
- **All words anywhere in an item:** the title, its text and its
  comments together.
- **"Only mine":** items you created and to-dos assigned to you
  (2026-11-21).
- **Archived** (changed 2026-11-21): archived projects, archived lists
  and their to-dos are left out unless "Include archived" (no negation
  in the label; `archived=true` in the API, `--archived` in the CLI);
  results are then marked "Archived" (`archived` and `project_archived`
  in the API, `(archived)` in the CLI).

## How it works

- **Indexes, not stored vectors:** expression GIN indexes on
  `to_tsvector('simple', …)` of every searched text
  (`biwak/search/migrations/0001_indexes.py`: item titles, list
  descriptions, to-do notes, messages, docs, file descriptions, answers,
  comments). They follow every write, whoever makes it (importer, admin,
  SQL), and the audit trigger doesn't see a vector column. **Rule:**
  `vector()` in `biwak/search/queries.py` must use the same expression
  as the migration, and a new searchable text gets its index in a
  migration and its entry in `TEXTS`. Old doc versions aren't searched.
- **The query:** each word is read by the database
  (`to_tsvector('simple', …)`, so "1.5" and addresses match as indexed),
  quoted and made a prefix (`'word':*`); at most 10 words and 200
  characters, never query syntax. Per word the IDs of every source are
  united (each using its index), then `Item.objects.visible_to(user)`
  filters: comments are found through their item, trashed items never
  show. Cursor paginated (`?before=` on the page, `cursor` in the API).
  Fast enough on a few hundred thousand items (measured 2026-11-20: 15
  to 130 ms for realistic words).
- **Excerpts:** `ts_headline` for the page's results in one query,
  with private-use characters as markers, then escaped, `<mark>` the
  only markup; texts made plain first (Markdown rendered, mentions as
  written). The item's text if it has the words, else the first
  matching comment ("Comment:"), none if only the title has them.
- **Results:** kind icon, title, project with its color, the excerpt,
  the client badge, the date, the checklist count.
- **Page:** `/search/?q=` with project, kind, "only mine" and "Include
  archived"; a project the person can't open is a form error (404 in
  the API). Reached through the palette (`keyboard.md`).
- **API and CLI:** `GET /api/v1/search/?q=` with the same filters
  (`excerpt`, `excerpt_html`, `title_html`, `in_comment`,
  `project_name` on top of `ItemOut`); `biwak search TERMS… [--project]
  [--kind] [--mine] [--archived] [--limit]`, marking `[clients]`.
- The palette's jumps (`keyboard.md`) are separate: archived projects
  last and marked, archived lists listed like active ones.
