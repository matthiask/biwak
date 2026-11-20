# Activity feed, item history, bookmarks, links

**Status:** open. The project page shows its latest 20 events
(`activity/_events.html`), nothing more.

**Agent:** suits a cheaper model following this spec and the checklist
in `AGENTS.md`.

**Depends on:** the core only. Items of later parts (messages, files,
check-ins) show up in the feed as soon as they record events.

## Activity feed

From the events (`biwak/activity/`, `notifications.md`):

- **Pages:** `/feed/` (everything the person can see, in the
  navigation), `/projects/<pk>/feed/` (the project page keeps its short
  version with a link), `/people/<pk>/feed/` (what someone did, within
  what the viewer can see).
- **Grouped by day** (in `TIME_ZONE`), newest first. Consecutive events
  by the same person with the same action in the same list or project
  within an hour are merged into one entry ("Ada completed 5 to-dos in
  Website relaunch", expandable to the single to-dos).
- **Filters** as query parameters: kind of item, person, action, visible
  to clients.
- **Visibility:** every entry through `Event.objects.visible_to()`; a
  client's feed only shows what they can see now. Events of trashed
  items are hidden; of items deleted for good, gone.
- **Paginated** by time with a cursor (`?before=<timestamp,id>`), 50
  events a page, fast on hundreds of thousands of events: check the
  query plan uses the `(project, -created_at)` index, add one on
  `(-created_at)` if needed.
- Rendering per action in one template (`activity/_event.html`) with the
  event's `data` (title at the time, assignees, where it moved), so
  later parts only add their actions there.

## Item history

The audit log (`biwak/audit/`, a database trigger on the main tables,
copied from Governance) records every change with who made it. Like
Governance's history (`~/projects/sites/governance/governance/history/`,
read its `audit.py` first), a page per item condenses it into something
readable:

- `/items/<pk>/history/`, linked from the to-do's (and later every
  item's) page: who changed the title, the notes, the assignees, the due
  date, the group or list and the visibility, and when, with the old and
  new values (texts as a diff, `difflib`).
- Read from `LoggedAction` rows of the item's tables (`items_item`, its
  detail table, `items_todo_assignees`) by primary key; people from the
  audit's user name (`audit_user_id()`).
- Events say what happened; the history shows the details. Only for
  people who can see the item now (the item through `item_for()`).

## Bookmarks

- `Bookmark(user, item null, project null, created_at)`, one of the two
  set, unique per person and target; private.
- A bookmark button (an icon, `bookmark` and `bookmark-fill`) on every
  item's and project's page; `/bookmarks/`, newest first, with the
  item's current title, kind and project. Bookmarks of items the person
  can't see any more are hidden, not deleted.

## Links

Links to outside tools on a project or on any item: Figma files,
repositories and issues, Google Drive documents, staging and production
sites, a project in a time tracking or accounting tool.

- `Link(project, item null, url, title, kind, position,
  visible_to_clients, created_by, created_at)`.
- **Kind** from the URL's host by a small table in `biwak/links.py`
  (figma.com: Figma, github.com: GitHub, gitlab.com: GitLab,
  docs.google.com and drive.google.com: Google Drive, everything else:
  link), each with an icon.
- **Shown** prominently at the top of the project page, in order
  (draggable for staff), and on items under their title. Staff add,
  edit, reorder and delete links; clients see those visible to clients
  (default: internal, decided 2026-11-20; a link on a visible item is
  still internal unless switched).
- Later and only where useful: integrations per kind fetching live data
  (title and preview by oEmbed, an issue's state). No tool is
  hard-coded into the core.

## API and CLI

`GET /api/v1/feed/` (with the filters, cursor-paginated; also per
project and person), `GET /api/v1/items/{id}/history/`, bookmarks (list,
add, remove), links (list, create, update, delete, reorder). `biwak feed
[--project ID] [--since DATE]`, `biwak bookmarks`, `biwak links PROJECT`.

## Done when

Pages, API and CLI for all of the above. Tests: merging (and not merging
across lists, people or hours), the day grouping around midnight,
filters, a client's feed without internal events, events of trashed
items hidden, the history of a to-do with title, notes, assignee and
visibility changes, bookmarks of items that became invisible, links'
visibility.
