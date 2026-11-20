# The projects page: favorites, activity, cards

The page people open first. Today it's an alphabetical list of names;
it should show at a glance which projects matter to the person and where
something is going on.

**Status:** open.

**Agent:** suits a cheaper model following this spec and the checklist
in `AGENTS.md`. The client column of the activity time (below) touches
visibility: have its tests reviewed.

**Depends on:** bookmarks (`feed.md`, merged). Nothing else.

**Touches:** `biwak/projects/` (models, views, api, operations),
`biwak/activity/operations.py` (`record()`), `biwak/accounts/models.py`
(one field), `projects/project_list.html`, `fairy_tasks`, `cli/biwak_cli/commands.py`. Not the project page
(`glance.md` changes that).

## Favorites are bookmarked projects

Decided 2026-11-20: no separate favorite. A bookmarked project
(`Bookmark(user, project)`, `feed.md`) is a favorite: the person's
bookmarked projects come first on the projects page, with the filled
bookmark icon, in the chosen order among themselves. The bookmark
button sits on each card, so favoriting doesn't need opening the
project (htmx, swapping the button like on the project page).

## Ordering: by activity or by name

Decided 2026-11-20: by activity by default, with a switch to
alphabetical, remembered per person.

- **Stored activity time**, because computing it per request from the
  events is too slow with many projects. `Project.last_activity_at` and
  `Project.last_client_activity_at`, both nullable, indexed.
- `record()` (`biwak/activity/operations.py`) updates them in the same
  transaction: `last_activity_at` for every event of the project;
  `last_client_activity_at` only for events of items visible to clients
  at that moment (`item.is_client_visible`), not for project events
  (joining, members) or internal items. One `UPDATE … WHERE pk=` per
  event, no extra query.
- **Clients** are sorted and shown by `last_client_activity_at`, so
  internal work doesn't reorder or date their projects. Staff by
  `last_activity_at`.
- **Drift:** an item switched to internal later keeps having counted for
  clients. `fairy_tasks` recomputes both columns from the events every
  night (events of trashed items and, for the client column, of items
  not visible to clients now don't count). A data migration fills them
  once the same way. Projects without events sort last, by name.
- **The switch:** "Activity" and "A–Z" as two buttons in the page
  header. Choosing posts to `/projects/order/` (operation
  `set_project_order(user, order)`), stored in `User.project_order`
  (`activity` or `name`, default `activity`). Not a query parameter
  that saves on GET.
- Archived projects (`?archived=1`) stay alphabetical, as a plain list
  as today, without cards.

## Cards

A responsive grid of cards instead of the list group (one column on
phones, two on tablets, three on wide screens), favorites first.

Each card, and nothing more (the card must stay small):

- The name (the link to the project), the lock icon for limited
  projects, the bookmark button.
- The description's first line as plain text, one line, cut with an
  ellipsis (`|excerpt`, `glance.md`; if `glance.md` isn't merged yet,
  add the filter as that spec describes).
- A "Clients" badge if the project has client members (staff only; a
  client knows already).
- The last activity as a relative time ("3 hours ago"), from the column
  matching the person; nothing if there was none.
- Counts, each only when not zero: open to-dos assigned to the person,
  overdue ones among them (in the danger color). Counted in one query
  for all cards (`Item.objects.visible_to(user)` grouped by project),
  never per card.

The admins' section "Limited projects you're not a member of" stays a
plain list below.

## API and CLI

- `GET /api/v1/projects/` takes `order` (`activity` or `name`, default
  the person's setting) and returns `is_bookmarked` and `last_activity_at`
  (the column matching the person) with each project, favorites first.
  The bookmark endpoints exist already (`feed.md`).
- `biwak projects [--order activity|name]` marks favorites with `*` and
  shows the last activity. Bump the CLI version.

## Done when

- Favorites first, in both orders; bookmarking from a card.
- `record()` updates the columns, the client column only for events of
  visible items; tests for an internal to-do changing nothing for a
  client, a project event changing only the staff column, the nightly
  recomputation and the data migration.
- A client's cards show the client column's time and counts only of
  what they see; staff see the badge, clients don't.
- The switch stored per person; the API and the CLI with `order`.
- The page with 200 projects in a fixed, small number of queries
  (`assertNumQueries`).
