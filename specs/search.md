# Search

Finding things across projects: a to-do, a message, a doc, a file, a
comment, a check-in answer, by words in their title or text.

**Status:** built 2026-11-20 (branch `search`): the page, the API and
`biwak search`. See "Built" below for how, the decisions made on the way
and the query plan.

**Agent:** suits a cheaper model following this spec and the checklist
in `AGENTS.md`. Search shows content: visibility tests through the page
and the API, with a client and with staff without access to a limited
project.

**Depends on:** every kind of item that exists now (to-dos, messages,
docs, files, check-ins, comments).

**Touches:** a new app `biwak/search/` (queries, views, api, templates),
a search field in `base.html`, the CLI, migrations for the search
indexes.

## What

- **PostgreSQL full-text search**, no outside service: GIN indexes on
  the title of items, the text of every kind and the comments, which
  stay current by themselves (see "Built"). Several languages are
  expected (English and German texts): the `simple` configuration plus
  prefix matching.
- **Results** go through `Item.objects.visible_to(user)` (comments through
  their item), so a client never finds what they can't see and trashed
  items don't show. Each result: kind icon, title, project, a short
  excerpt with the matched words (`ts_headline`, escaped), the client
  badge, the date.
- **Page:** `/search/?q=…`, with filters for the project, the kind and
  "only mine"; the field in the navigation. Paginated like the feed.
- **API and CLI:** `GET /api/v1/search/?q=` with the same filters and
  cursor pagination; `biwak search TERMS [--project ID] [--kind K]`,
  marking `[clients]`.

## Decided (2026-11-20)

- Excerpts are plain text like the excerpts elsewhere (`glance.md`): no
  Markdown, mentions as "@Label" as written.

- The `simple` text search configuration with prefix matching, the same
  for every language; no stemming.
- Archived projects are searched, their results marked as archived; a
  filter leaves them out.
- Page size and excerpt length like the feed: 50 results, 200
  characters.

## Built (2026-11-20)

- **Indexes, not stored vectors**: expression GIN indexes on
  `to_tsvector('simple', …)` of `items_item.title`, `items_todolist.description`,
  `items_todo.notes`, `items_message.content`, `items_doc.content`,
  `items_upload.description`, `checkins_answer.content` and
  `items_comment.content` (`biwak/search/migrations/0001_indexes.py`).
  Nothing in the operations: the indexes follow every write, whoever
  makes it (importer, admin, SQL), and the audit trigger doesn't see a
  vector column. `biwak/search/queries.py` (`vector()`) has to use the
  same expression as the migration, and a new text gets its index in a
  migration and its entry in `TEXTS`. Old doc versions aren't searched.
- **The query**: every word of the query is read by the database itself
  (`to_tsvector('simple', …)`, so "1.5" and addresses match as indexed),
  quoted and made a prefix (`'word':*`); at most 10 words, 200
  characters, never query syntax. An item is found when every word is
  somewhere in it: the title, its text or its comments (the words can be
  spread over them). Per word the IDs of the 8 sources are united (each
  using its index), then `Item.objects.visible_to(user)` filters, so
  comments are found through their item and trashed items (and those of a
  trashed list) never show. Newest first by `updated_at`, cursor
  paginated like the feed, 50 per page (`?before=` on the page,
  `cursor` in the API).
- **Excerpts**: `ts_headline` per text of the 50 results, in one query,
  with private-use characters as markers (taken out of the texts
  first), cut to 200 characters in Python, then escaped; `<mark>` is the
  only markup. The text of the item if it has the words, else the first
  matching comment (marked "Comment:"), none if only the title has them.
  Texts and comments are turned into plain text first (Markdown rendered,
  tags stripped, mentions as written). API: `excerpt` (plain), `excerpt_html`, `title_html`,
  `in_comment`, `project_name`, `project_archived` on top of `ItemOut`.
- **Page and field**: `/search/?q=` with the project, kind, "only mine"
  and "without archived projects" filters; the field in the navigation of
  `base.html`. Filters of projects the person can't open are form errors
  (page) or 404 (API). CLI: `biwak search TERMS… [--project] [--kind]
  [--mine] [--no-archived] [--limit]`, 0.18.0.
- **Query plan** (`EXPLAIN ANALYZE`, 300 000 items, 300 000 comments,
  100 000 each of to-do notes, message and doc texts, 40 projects, made-up
  words with a Zipf-like distribution, local PostgreSQL): every part of
  the union uses its GIN index (Parallel Bitmap Heap Scan on a
  Bitmap Index Scan for the large results, Bitmap Heap Scan for the
  small ones; the tables of lists, files and answers are empty and
  scanned). Then a semi join with the visible items, a top-N sort of the
  first page. A word in 44 texts: 15 ms; in 344: 21 ms; in 16 700 (5 % of
  the items): 130 ms; in 267 000 items (a word in nearly every text,
  which people don't search for): 780 ms, as the sort needs all matches.
  As a client the same (the filter on the stored visibility is cheap).

## Decisions made on the way (confirmed 2026-11-21: newest first, all
words anywhere in an item; "only mine" changed to created or assigned)

- Order: newest first by `updated_at`, not by relevance (the spec says
  "paginated like the feed" and shows a date).
- "Only mine": items you created and to-dos assigned to you (decided
  2026-11-21); still within `visible_to()`.
- Words match anywhere in the item (title, text, comments together).
- The filter for archived projects is "without archived projects" (the
  default includes them, marked "Archived").

## Done when

Searching titles, texts and comments of every kind; a client finding
only visible items, never internal comments' items; staff without
access to a limited project finding nothing in it; trashed items not
found; the page, the API and the CLI; a query plan using the indexes on
a few hundred thousand items.
