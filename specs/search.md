# Search

Finding things across projects: a to-do, a message, a doc, a file, a
comment, a check-in answer, by words in their title or text.

**Status:** open (decided 2026-11-20 to be its own part, before the
importer).

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

- **PostgreSQL full-text search**, no outside service: a `tsvector` per
  item (title and text) and per comment, kept up to date by the
  operations or generated columns, with GIN indexes. Several languages
  are expected (English and German texts): the `simple` configuration
  plus prefix matching.
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

- The `simple` text search configuration with prefix matching, the same
  for every language; no stemming.
- Archived projects are searched, their results marked as archived; a
  filter leaves them out.
- Page size and excerpt length like the feed: 50 results, 200
  characters.

## Done when

Searching titles, texts and comments of every kind; a client finding
only visible items, never internal comments' items; staff without
access to a limited project finding nothing in it; trashed items not
found; the page, the API and the CLI; a query plan using the indexes on
a few hundred thousand items.
