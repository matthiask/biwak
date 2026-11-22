# Activity feed, item history, bookmarks, links

**Status:** built (2026-11-20; links on projects only since 2026-11-21).
The project page keeps its short list of the latest 20 events
(`activity/_events.html`) with a link to the feed.

## Activity feed

From the events (`biwak/activity/`, `notifications.md`);
`biwak/activity/feed.py`, `views.py`.

- **Pages:** `/feed/` (everything the person can see, in the
  navigation), `/projects/<pk>/feed/`. What someone did is the activity
  with the person filter (`/feed/?person=<pk>`); their last 5 entries are
  on their page (`people.md`). There is no person feed page anymore
  (decided 2026-11-22: `/people/<pk>/feed/` is a 404, no redirect).
- **Grouped by day** (in `TIME_ZONE`), newest first. Consecutive events
  by the same person with the same action in the same list or project
  merge into one entry ("Ada completed 5 to-dos in Website relaunch",
  "items" for mixed kinds), the single items indented below it. "Within
  an hour" means each event at most an hour after the next older one of
  the entry (chains merge), never across midnight. A page ends between
  entries (decided 2026-11-22, replacing "a page boundary can split an
  entry"): after 50 events or later, looking ahead up to another 50 for
  a place where no entry, conversation or pair cancelling out is split
  (`feed._edge()`); only a merge reaching further is still split.
- **Conversations, nothing collapses** (decided 2026-11-21): comments
  on the same item, by anyone, each within an hour of the one before and
  on the same day, become one entry, "Conversation on Order the tent",
  with each comment indented below it (who, the excerpt, the time),
  oldest first. Other events in between don't break it up: it sits at the
  place of its newest comment (`feed.conversations()`). One comment alone
  stays an ordinary event. The feed has no `<details>`. Grouping works on
  the events the viewer may see, so a client's conversation only has the
  comments they may see; it needs no queries of its own.
- **Filters** as query parameters: kind of item, person (a combobox),
  action, visible to clients.
- **No client badge on entries** (decided 2026-11-21): calmer; the item's
  page shows it, and the filter finds what clients see.
- **Visibility:** every entry through `Event.objects.visible_to()`: a
  client sees only events of the time the item was visible to them, of
  items they see now (`access.md`), not the creation, renaming or
  assigning of a to-do while it was in an internal list. Events of
  trashed items are hidden; of items deleted for good, gone.
- **Paginated** by time with a cursor (`?before=<microseconds since the
  epoch>,<id>` of a page's last event, 400 if malformed), 50 events a
  page, on the index `(-created_at, -id)` (about 1 ms per page on 240,000
  events, checked with `EXPLAIN` for staff, clients and per project).
- **Rendering** per action in one template (`activity/_event.html`) with
  the event's `data` (title at the time, assignees, where it moved);
  later parts add their actions there.

Decisions (2026-11-20 unless dated):

- **The person filter** lists the people the viewer shares a project
  with as members (`people_visible_to()`) and ignores anybody else, so
  it doesn't tell whether a person exists. "My activity" in the "Me" menu
  is the activity filtered by oneself (`/feed/?person=<me>`), shown
  where the filter takes oneself (`in_person_filter` in
  `templatetags/biwak.py`; decided 2026-11-22, it was a person feed
  page).
- **Names link to the person's page** (decided 2026-11-22, they linked
  to the person feed): the actor of every entry and the people an event
  names ("assigned Bob to …", "shared … with Bob, Cleo"), in the feed,
  Home and the project page, the to-do's timeline and the history, where
  the viewer may open that page (`known_people()`), else plain text
  (`{% person_link %}`, `people.linked_name()`; `feed.attach()` links
  the named people as `event.assignee_links`).
- **Moves between lists** (decided 2026-11-21): a client sees the target
  list ("moved … to Plans") when that list is visible to them now,
  checked when the feed, a mail or the API is shown, not when recorded,
  so a list made internal later disappears from the event. The event
  stores the list's ID (`to_id`) next to its title;
  `feed.add_target_lists()` resolves a page of events in one query and
  shows the list's current title. Events without the ID stay staff-only
  (staff see the title at the time). The source list is visible anyway,
  since the to-do is. In the API a client's `data` has `to` and `to_id`
  only for a visible list.
- **Moves between groups** (a board column) are a `moved` event with the
  group and the list ("Ada moved 'Order the tent' to Done"), for
  everybody who sees the to-do, in mails too. The same person moving the
  same to-do within 10 minutes updates that event, like edits, so
  dragging back and forth is one event with the last group. Reordering
  within a group is no event; moving it out of every group reads "moved …
  out of its group" (decided 2026-11-21).
- **Completing and reopening back and forth** (decided 2026-11-21,
  replacing deleting the earlier event within ten minutes): every
  completing and reopening is recorded. Where it's shown it makes sense
  of it (`timeline.cancelled()`): a person's consecutive completing and
  reopening of an item (other events in between don't break it up,
  another person's completing or reopening does) is its net change, the
  last one, or nothing when the to-do is back where it started. Moves
  too (decision B, decided 2026-11-22): a person's consecutive moves of
  a to-do into other columns or lists are the last one, or nothing when
  it's back where it was, in its list and its column
  (`timeline.moved_back()`, from the moves' `group_was` and `to_was`; a
  move into another list ends the column moves before it, see
  `timeline.md`; older moves without them show as they are;
  the feed and the timeline only, not the lantern and mails). Another
  person's completing, reopening or move breaks it up in the activity
  filtered by a person (and their page's entries) too, where that person's events are left out (`feed._others()`, fixed
  2026-11-22): it shows the person's events as the whole feed does. In the feed (and the project page's latest events) each within an hour of the
  one before and on the same day, like merging; the to-do's timeline
  does the same within its lines (`combine()`, `timeline.md`); the
  lantern and the mails: `notifications.md`. The API lists single
  events, all of them.

**API** (`biwak/activity/api.py`): single events, not merged entries.
`GET /api/v1/feed/` with `project_id`, `person_id`, `kind`, `action`,
`visible_to_clients`, `since` (a date) and ninja's cursor (`next` is the
URL of the next page); `projects/{id}/feed/` and `people/{id}/feed/`
with the same filters (the project's takes `person_id`, the person's
`project_id`; a person outside the project is a 404). **CLI:** `biwak
feed [--project] [--person] [--kind] [--action] [--since] [--limit]` (50
by default, follows the cursor).

## Item history

The audit log (`biwak/audit/`) records every change with who made it; a
page per item condenses it (`biwak/activity/history.py`, like
Governance's history): `/items/<pk>/history/` and `GET
/api/v1/items/{id}/history/`, newest first, complete, for every kind of
item; every item's page links to it in its "More" menu, for staff
(decided 2026-11-22, not a button of its own), and the palette offers it.

- Read from `LoggedAction` rows of the item's tables (`items_item`, its
  detail table, `items_todo_assignees`) by primary key; the person from
  the audit's user name (`audit_user_id()`), otherwise that name (a job).
- Tracked: the title, the list or folder ("another folder" when the
  viewer can't see it), the effective visibility, the status; notes,
  group, start and due dates, completing and reopening and the assignees
  of to-dos; descriptions of lists, content of messages and docs; the
  content of check-in answers, and the schedule, first date, time of day,
  pausing and people asked of questions. Texts as a line diff
  (`difflib`) with one line of context. Positions and timestamps are
  ignored.
- **Staff only** (decided 2026-11-20; 403 for clients, 404 for what they
  can't see): old versions of texts can hold what was internal at the
  time, also on items clients see now.
- The effective visibility is shown, not the switch: a to-do moved into
  a visible list shows "Visible to clients: no, yes". Lists the viewer
  can't see read "another list".
- Only the item's own rows: comments have their place on the page,
  files' versions are `files.md`'s, the to-do's timeline (`timeline.md`)
  shows the events between comments. Events say what happened, the
  history the details.

## Bookmarks

`biwak/bookmarks/` (shared with links; both audited).

- `Bookmark(user, item null, project null, created_at)`, one of the two
  set, unique per person and target; private.
- A bookmark button (`{% bookmark_button obj %}`, `{% load bookmarks %}`;
  icons `bookmark` and `bookmark-fill`) on every item's and project's
  page; pages of new kinds add it themselves. `POST
  /items/<pk>/bookmark/` and `/projects/<pk>/bookmark/` (`bookmark=1`
  adds, otherwise removes).
- `/bookmarks/` (in the navigation): bookmarked projects first, then the
  items grouped by project, the project with the newest bookmark first,
  each item with its current title and kind (decided 2026-11-21: by
  project, not by kind: one looks for "that thing in project X"). Bookmarks of what the person can't
  see anymore are hidden, not deleted, and come back when they see it
  again.
- API: `GET /bookmarks/`, `PUT`/`DELETE` `items/{id}/bookmark/` and
  `projects/{id}/bookmark/`; CLI `biwak bookmarks`, `biwak bookmark
  add|remove [--project] ID`.

## Links

Links to outside tools on a project: Figma files, repositories and
issues, Google Drive documents, staging and production sites, a project
in a time tracking tool. **On projects only** (decided 2026-11-21): items
have Markdown texts where a link is clickable in context, so a link block
there only duplicated it.

- **Adding** from the project page's section and from the palette on
  project pages ("Add a link", a modal; confirmed 2026-11-21).
- `Link(project, url, title, kind, position, visible_to_clients,
  created_by, created_at)`. Only `http` and `https`; the title defaults
  to the host.
- **Kind** from the URL's host by a small table in `biwak/links.py`
  (figma.com, github.com, gitlab.com, docs.google.com and
  drive.google.com, everything else a plain link), each with an icon
  (Figma has none in Bootstrap Icons: the palette stands in; Google
  Drive uses the Google icon). No tool is hard-coded into the core;
  integrations fetching live data (oEmbed, an issue's state) only later
  and where useful.
- **On the project page** a section "Links" after "Docs and files" in
  the left column (`bookmarks/_links.html`, `{% show_links project %}`):
  an `h2.h5` with a quiet "Add a link" button (a modal,
  `project_link_new`), the links as a list group (handle for staff, kind
  icon, client badge, edit as a modal, delete), "No links yet." when
  empty. Dragging: `frontend/sortable-order.js`, `…/links/order/`.
- **Who:** any staff member sees and changes the links of the projects
  they see; clients see those switched visible (internal by default,
  decided 2026-11-20; `Link.objects.visible_to()`).
- Links and bookmarks record no events and don't appear in the feed.
- API: `GET`/`POST projects/{id}/links/` (in order), `PATCH`/`DELETE
  links/{id}/`, `PUT projects/{id}/links/order/` (all IDs);
  `visible_to_clients` is the link's own switch. CLI: `biwak links
  PROJECT`, `biwak link add PROJECT URL [--title] [--clients]`, `biwak
  link delete LINK`. `MINIMUM` 0.30.0, since older CLIs read `item_id`.
