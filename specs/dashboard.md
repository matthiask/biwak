# Home: what needs me, and where things are going on

The idea (2026-11-21): `/` becomes a dashboard, "Home", and the projects
page moves to `/projects/`. Home shows bookmarked projects, recent
updates, to-dos due soon or overdue, and links to useful functionality.

**Status:** built 2026-11-21 (branch `home`), the questions answered the
same day (recorded in the sections). `biwak/projects/home.py`,
`templates/projects/home.html`; the tests in `biwak/projects/test_home.py`,
a browser test in `biwak/test_e2e.py` (`HomeTest`). Decisions on the way:
- The unread rows keep their link to the item and carry
  `data-lantern-read` with the lantern's `/lantern/<notification>/`, which
  `frontend/lantern.js` posts to when the link is followed (the lantern's
  entries work the same; `lantern_open` answers POST only, so the link
  can't point at it). `lantern.unread_by_item()` finds the notifications.
- "Due" and "Waiting on others" use the sections of `due.sections()`
  (Overdue, Today, This week, Next week; decided 2026-11-21, the same
  groups as the to-dos page, `todos.md`); "All N to-dos" shows the number of all my
  open to-dos when there are more than the rows shown.
- Recent updates take the newest 50 events of the last 7 days from the two
  sources, merge them into entries and show the first 10.
- "Keyboard shortcuts" in the links card is a link opening the help
  dialog (`data-shortcuts-open`, `frontend/shortcuts.js`; decided
  2026-11-21); without JavaScript (or with shortcuts off) the hint with
  `?` shows instead.
- No "New project" in the links card (decided 2026-11-21: people
  should check the existing projects first; it's on the projects list),
  only in the empty state for someone in no project yet.

**Agent:** a cheaper model following this spec and the checklist in
`AGENTS.md`. Every section shows items, so the visibility tests matter
most: have them reviewed.

**Depends on:** `ui-round-5.md` (the "assigned by" filter, for "Waiting
on others") and the links part of `feed.md` (the project page's links,
so nothing here points at item links), both merged; "Reading by acting"
in `lantern.md` (completing a to-do on Home reads its notifications).

**Touches:**
- `biwak/projects/urls.py` (`/` and `/projects/`), the navigation in
  `base.html`, the palette's actions and shortcuts (`biwak/palette/`);
- a new view and template (`biwak/home/` or in `biwak/projects/`),
  reusing `items/_todo.html`'s row, the projects page's card,
  `activity/_entries.html` and `checkins_due`;
- `frontend/filters.js` only if the remembered order of the projects
  page has to move with it (it's stored per path).

## Why

Today the first page is the list of projects. To know what's on, a
person opens "My to-dos" (what's due), the feed (what happened), the
lantern (what's for them) and their projects one by one. The dashboard
answers "what needs me today, and where is something going on" on one
page, and leads to the pages that have the rest. It shows little of
each, newest or most urgent first, and always links to the full page.

## The name and where it is

Decided 2026-11-21: the page is "Home" (its title and the palette's "Go
home"; "Dashboard" sounds like charts). The brand ("Biwak") in the top
bar links to it; no entry of its own in the top bar, which stays
"Projects", "To-dos", "Activity", "People", "Bookmarks". The shortcut is
`g h`, next to `g p`, `g t`, `g f` and `g b`. Below, "the dashboard" and
"Home" are the same page.

## Principles

- **Only what's for this person, and only when there is some.** A
  section with nothing in it is left out, except the to-dos (an empty
  "Due" says "Nothing due this week.", which is good news worth saying).
- **Short:** each section shows a few rows (the counts below) and
  links to the full page ("All 14 to-dos", "All activity"). Nothing
  here is only on the dashboard.
- **The same rows as elsewhere:** the to-do row with its checkbox
  (completing works in place), the projects page's cards, the feed's
  entries. No new kind of row.
- **Everything through `Item.objects.visible_to(user)` and
  `Project.objects.accessible_to(user)`;** archived projects and lists
  are left out, as on "My to-dos" (`biwak.items.due.todos`).
- **A fixed, small number of queries,** whatever the number of
  projects (`assertNumQueries`, as the projects page).
- **Not live** (like the feed and the project page, `lantern.md`):
  the lantern tells what's new; reloading shows it.

## The sections

In this order on phones (one column). On wide screens two columns: the
main column (to-dos, check-ins, waiting on others, recent updates) and
a narrow one (projects, bookmarks, links).

### 1. Due: my to-dos (everyone)

- Open to-dos assigned to me, overdue or due within the next 7 days
  (decided 2026-11-21: 7 days rather than the end of this week, so a
  Friday still shows next week's): overdue, today, the days after (the
  sections of `biwak.items.due`, with their headings and badges), up to
  10 rows, the most urgent first.
- Below: "All my to-dos" (`/todos/?assignee=me&grouping=due`), with
  the number when there are more than shown.
- Empty: "Nothing due this week." (still links to all my to-dos).
- To-dos without a date don't show here: they're not urgent.

### 2. Check-ins waiting for my answer (only when there are some)

- The questions I haven't answered yet, as on the project page
  (`checkins_due`), across all projects, each with its project.

### 3. Waiting on others (staff, only when there are some)

- To-dos I assigned to somebody else (not to me), in the same window as
  "Due" (decided 2026-11-21): overdue or due within the next 7 days, up
  to 10, the most urgent first, each with its assignees. "Assigned by"
  from `ui-round-5.md`. Link: "All to-dos I assigned"
  (`/todos/?assignee=&assigned_by=me&grouping=due`).

### 4. Recent updates (everyone)

- The newest feed entries (`activity/_entries.html`, grouped as on the
  feed, conversations included), up to 10, from the last 7 days, from
  two sources together (decided 2026-11-21):
  - **my bookmarked projects:** everything that happens in them,
    completed to-dos and answered check-ins included;
  - **what concerns me, in any project:** events that mention me or
    assign me (the ones whose notification for me is a mention or an
    assignment).
  Without bookmarked projects only the second. My own actions show too
  (decided 2026-11-21: the timeline can hold context I contributed to,
  like my comment in a conversation).
- Clients: what the feed shows them, by the same rules (`access.md`).
- Updates that are in the lantern too stay here (decided 2026-11-21:
  the dashboard is the overview, the lantern the inbox).
- Link: "All activity" (`/feed/`).
- Empty after the filters: left out.

### 5. Projects (everyone)

- My bookmarked projects as the projects page's cards (counts of my
  open and overdue to-dos, last activity), in the bookmarks' order.
- Without bookmarks: the 6 projects with the most recent activity that
  I'm a member of, with a short hint: "Bookmark projects to keep them
  here." (decided 2026-11-21).
- Link: "All projects" (`/projects/`).
- Nobody in any project yet: "You're not in a project yet.", with
  "New project" for those who may create one.
- Clients get Home too, also with a single project (decided
  2026-11-21): its to-dos and updates are useful, and the project is
  one click away.

### 6. Bookmarks (only when there are some)

- My bookmarked items (not projects), up to 5, newest bookmark first,
  with their kind's icon and project. Link: "All bookmarks".

### 7. Links to useful functionality (everyone, short)

Plain links in a card, each only for those who can use it (decided
2026-11-21, nothing more):
- "To-dos I assigned" (staff);
- "Search" with the shortcut (Ctrl+K), "Keyboard shortcuts" (`?`);
- "Subscribe to your to-dos in a calendar" (the iCal feed's page,
  `calendar_link`, `todos.md`);
- "Notification settings" (`settings_notifications`);
- "API tokens and the CLI" (staff).

## Shared with the lantern

Things on the dashboard can be in the lantern too: a to-do due that
somebody commented on, an update in recent updates, a bookmarked item.

**Nothing has to be dealt with twice** (decided 2026-11-21, user). The
dashboard has nothing of its own to tick off, dismiss or mark as seen:
its rows go away when what they show is done (a to-do completed, a
check-in answered, a bookmark removed, an update aged out), never by
being looked at. What can be marked read is the lantern's, and it is
one state on the server for both views; the browser doesn't need to
sync it.

Decided 2026-11-21: Home shows notifications only as the lantern's
unread mark on its rows, without a section of their own ("Mentioning
you" would copy the lantern; mentions and assignments are in recent
updates already).

- **One state:** what the lantern has, `Notification.read_at` (and
  `marked_unread_at`), and `Bookmark`. The dashboard keeps no state of
  its own ("seen on the dashboard" doesn't exist).
- **Unread shows:** a row (to-do, update, bookmark, check-in) whose item
  has unread notifications for me gets the lantern's unread mark, the
  same style as in the lantern's menu.
- **Opening reads, as in the lantern:** such a row's link goes through
  `/lantern/<notification>/` (`views.lantern_open`), which reads the
  item's notifications and opens it at the comment, exactly like
  clicking the entry in the lantern. Rows without unread notifications
  link to the item directly. This extends `lantern.md`'s "reading only
  through the lantern" to the dashboard (the lantern's entries shown on
  another page); the feed, lists and mails still read nothing.
- **Acting reads, looking doesn't:** completing a to-do or anything
  else `lantern.md` counts as a strong signal ("Reading by acting",
  decided 2026-11-21) reads the item's notifications, on the dashboard
  as everywhere. Loading the dashboard or bookmarking reads nothing.
- **Bookmarks** are the lantern's "Bookmarked" and the dashboard's
  bookmarks (section 6) alike: bookmarking or removing the bookmark in
  one shows in the other on the next load.
- **The lantern's dot** in the navigation follows from the same state:
  after opening an entry from the dashboard the next page shows the
  count without it (live, the lantern's websocket tells open tabs as it
  does after reading in the lantern, `biwak:lantern`).
- **Tests:** opening from the dashboard reads in the lantern (and keeps
  it out of the mail, `send_mails`), reading in the lantern removes the
  mark on the dashboard, marking unread brings it back, a client's
  notifications follow the visibility rules on both.

## The projects page moves

- `/projects/` is the projects page as it is now (cards, order,
  archived via `?archived=1`, the admins' limited projects). The URL
  name `projects` stays and points there; the dashboard gets
  `dashboard` at `/`.
- The navigation's "Projects" goes to `/projects/`; the brand ("Biwak")
  goes to the dashboard.
- Old links to `/?archived=1` redirect to `/projects/?archived=1`.
- The palette: "Go to projects" (`g p`) stays; "Go home" (`g h`) is
  new.
- The remembered order of the projects page is stored per path by
  `frontend/filters.js`; at the new path it starts fresh (no users yet,
  `no-users-yet`), nothing to migrate.

## API and CLI

The dashboard puts together what the API and the CLI have already: to-dos
by due date (`assignee=me`, `biwak todos --mine --by-due`), the feed,
bookmarks, projects, and the check-ins waiting for an answer
(`GET /api/v1/me/checkins/due/`, `biwak checkin due`). No endpoint of
its own.

## Done when

- `/` is the dashboard, `/projects/` the projects page; the
  navigation, the palette and old `?archived=1` links lead there.
- Each section shows what this spec says, only under its conditions,
  for staff and clients (Django tests per section and condition: a
  client never sees internal to-dos, events or projects; an archived
  project shows nowhere).
- Completing a to-do on the dashboard works in place (browser test).
- The page in a fixed number of queries with 200 projects.
- Screenshots at 1200 and 390 px: a busy staff person, a client, a new
  person without projects, looked at.
