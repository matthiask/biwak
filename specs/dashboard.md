# The dashboard: what needs me, and where things are going on

The idea (2026-11-21): `/` becomes a dashboard, the projects page moves
to `/projects/`. The dashboard shows bookmarked projects, recent
updates, to-dos due soon or overdue, and links to useful functionality.

**Status:** draft (2026-11-21), the questions at the end wait for
answers. Not built.

**Agent:** a cheaper model following this spec and the checklist in
`AGENTS.md`, once the questions are answered. Every section shows items,
so the visibility tests matter most: have them reviewed.

**Depends on:** `ui-round-5.md` (the "assigned by" filter, for "Waiting
on others") and the links part of `feed.md` (the project page's links,
so nothing here points at item links), both merged.

**Touches:**
- `biwak/projects/urls.py` (`/` and `/projects/`), the navigation in
  `base.html`, the palette's actions and shortcuts (`biwak/palette/`);
- a new view and template (`biwak/dashboard/` or in `biwak/projects/`),
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

- Open to-dos assigned to me, due before the end of the next 7 days:
  overdue, today, this week (the sections of `biwak.items.due`, with
  their headings and badges), up to 10 rows, the most urgent first.
- Below: "All my to-dos" (`/todos/?assignee=me&grouping=due`), with
  the number when there are more than shown.
- Empty: "Nothing due this week." (still links to all my to-dos).
- To-dos without a date don't show here: they're not urgent.

### 2. Check-ins waiting for my answer (only when there are some)

- The questions I haven't answered yet, as on the project page
  (`checkins_due`), across all projects, each with its project.

### 3. Waiting on others (staff, only when there are some)

- To-dos I assigned to somebody else (not to me) that are overdue,
  up to 5, each with its assignees. "Assigned by" from
  `ui-round-5.md`. Link: "All to-dos I assigned"
  (`/todos/?assignee=&assigned_by=me&grouping=due`).
- Only overdue ones: due soon is the assignee's business, overdue is
  where a nudge helps.

### 4. Recent updates (everyone)

- The newest feed entries (`activity/_entries.html`, grouped as on the
  feed, conversations included), up to 10, from the last 7 days, in my
  bookmarked projects; without bookmarks, in the projects I'm a member
  of. Not my own actions.
- Clients: what the feed shows them, by the same rules (`access.md`).
- Link: "All activity" (`/feed/`).
- Empty after the filters: left out.

### 5. Projects (everyone)

- My bookmarked projects as the projects page's cards (counts of my
  open and overdue to-dos, last activity), in the bookmarks' order.
- Without bookmarks: the 6 projects with the most recent activity that
  I'm a member of, with a short hint: "Bookmark projects to keep them
  here."
- Link: "All projects" (`/projects/`).
- Nobody in any project yet: "You're not in a project yet.", with
  "New project" for those who may create one.

### 6. Bookmarks (only when there are some)

- My bookmarked items (not projects), up to 5, newest bookmark first,
  with their kind's icon and project. Link: "All bookmarks".

### 7. Links to useful functionality (everyone, short)

Plain links in a card, each only for those who can use it:
- "New project" (who may create one: the page's one primary action);
- "To-dos I assigned" (staff);
- "Search" with the shortcut (Ctrl+K), "Keyboard shortcuts" (`?`);
- "Subscribe to your to-dos in a calendar" (the iCal feed's page,
  `calendar_link`, `todos.md`);
- "Notification settings" (`settings_notifications`);
- "API tokens and the CLI" (staff).

## The projects page moves

- `/projects/` is the projects page as it is now (cards, order,
  archived via `?archived=1`, the admins' limited projects). The URL
  name `projects` stays and points there; the dashboard gets
  `dashboard` at `/`.
- The navigation's "Projects" goes to `/projects/`; the brand ("Biwak")
  goes to the dashboard.
- Old links to `/?archived=1` redirect to `/projects/?archived=1`.
- The palette: "Go to projects" (`g p`) stays; "Go to the dashboard"
  is new (question 3).
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

## Questions

Proposals in the sections above; answers go into the sections and the
entry leaves this list.

1. **The page's name and title:** "Dashboard", "Home", or "Today"?
   (Proposed: "Home" as the page's title and in the palette, since
   "Dashboard" sounds like charts.)
2. **A navigation entry?** The brand links to it already. Proposed: no
   extra entry; "Projects", "To-dos", "Activity", "People",
   "Bookmarks" stay as they are.
3. **A shortcut:** `g h` ("home") for the dashboard, next to `g p`,
   `g t`, `g f` and `g b`?
4. **Due window:** 7 days ahead and up to 10 rows, as proposed, or the
   end of this week (as the "this week" section is now)?
5. **Recent updates:** from bookmarked projects (falling back to my
   projects), as proposed, or from all projects I see? For staff in
   all-access projects "all" could be a lot.
6. **Not my own actions** in recent updates: right, or show everything
   as the feed does?
7. **Projects without bookmarks:** the 6 most recently active as
   proposed, or all my projects when there are few (say up to 6) and
   only then the most active?
8. **Clients with exactly one project:** the dashboard too (proposed:
   yes, the same page; its to-dos and updates are still useful), or
   straight to that project?
9. **Mentions:** a section "Mentioning you" duplicates the lantern.
   Proposed: none; the lantern is where things for me are.
10. **"Waiting on others":** only overdue (proposed), or due today too?
11. **Links (section 7):** anything to add or drop? A link to the
    person's own activity ("My activity")?
