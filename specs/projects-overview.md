# The projects page: favorites, activity, cards

`/projects/` (Home is `/`, `dashboard.md`): which projects matter to the
person and where something is going on.

**Status:** built (2026-11-20; archiving and the color picker changed
2026-11-21).

## Favorites are bookmarked projects

Decided 2026-11-20: no separate favorite. Bookmarked projects
(`Bookmark(user, project)`, `feed.md`) come first, with the filled
bookmark icon, in the chosen order among themselves. The bookmark button
is on each card (htmx).

## Ordering: by activity or by name

Decided 2026-11-20: by activity by default, or alphabetical.

- **Stored activity times**, because computing them from the events per
  request is too slow: `Project.last_activity_at` and
  `last_client_activity_at`, indexed, ignored by the audit trigger (they
  change with every event).
- `record()` (`biwak/activity/operations.py`) updates them in the same
  transaction with `GREATEST(column, event time)`: `last_activity_at`
  for every event of the project, `last_client_activity_at` only for
  events of items visible to clients at that moment, not for project
  events (joining, members) or internal items. Reactions don't count.
- **Clients** are sorted and shown by the client column, so internal
  work doesn't reorder or date their projects.
- **Drift:** an item switched to internal later has counted for clients
  already. `fairy_tasks` recomputes both columns from the events every
  night (`RECOMPUTE_ACTIVITY_SQL` in `biwak/projects/operations.py`;
  reactions, events of trashed items and, for clients, of items not
  visible now don't count). Projects without events sort last, by name.
- **The switch:** "Activity" and "A–Z", `?order=activity|name`, a small
  filter form remembered in the browser (`ui.md`; decided 2026-11-21,
  not a field on `User`).

## Cards

A grid of cards (one column on phones, two on tablets, three on wide
screens), favorites first. **The whole card is the link** to the
project (decided 2026-11-22, the user: not just the title): the name's
link covers the card (`.wb-card-link`, its `::after`), the bookmark
button sits above it (`.wb-above-card-link`) and stays a button; Tab
reaches the link, then the bookmark, and the focus outlines the whole
card. The lock's and the "Clients" badge's titles don't show on hover
any more (under the link). Home's cards are the same include. Each
card, and nothing more:

- the name, the project's color as a stripe (`project-colors.md`), the
  lock icon for limited projects, the bookmark button;
- the description's first line (`|excerpt`, cut at 160 characters and by
  CSS);
- a "Clients" badge if the project has client members (staff only);
- the last activity ("3 hours ago") from the column matching the person;
- open to-dos assigned to the person and the overdue ones among them
  (danger color), each only when not zero, counted with
  `biwak.items.due.todos(user, assignee="me")` in one query for all
  cards (the page in a fixed number of queries with 200 projects).

## Archived projects

- "Archive" and "Active projects" switch with htmx (the page's content,
  `projects/_page.html`); the archived list (`?archived=1`) is a plain
  alphabetical list without cards.
- **No archiving from this page** (decided 2026-11-21): archiving and
  bringing back are in the project's own "More" menu. After archiving
  the projects page says "Archived Website." with an Undo.
- Admins get a link "All projects" below the cards (decided
  2026-11-22, `handover.md`), in place of the plain list of limited
  projects they're not a member of: `/projects/all/` lists them with
  "Join".

## API and CLI

`GET /api/v1/projects/` takes `order` (`activity` or `name`) and
`archived=true` (alphabetical), favorites first; every project carries
`is_bookmarked` and `last_activity_at` (the person's column). `biwak
projects [--order activity|name]` marks favorites with `*`.
