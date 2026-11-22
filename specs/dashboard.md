# Home: what needs me, and where things are going on

`/` is "Home" (decided 2026-11-21; "Dashboard" sounds like charts), the
projects page is `/projects/`. Home answers "what needs me today, and
where is something going on" on one page and leads to the pages that
have the rest.

**Status:** built 2026-11-21: `biwak/projects/home.py` (URL name
`dashboard`), `templates/projects/home.html`.

## Principles

- **Only what's for this person, and only when there is some.** An
  empty section is left out, except the to-dos ("Nothing due this
  week." is good news worth saying).
- **Short:** a few rows each, always linking to the full page. Nothing
  is only on Home.
- **The same rows as elsewhere:** the to-do row (completing works in
  place), the projects page's cards, the feed's entries.
- **Everything through `Item.objects.visible_to(user)` and
  `Project.objects.accessible_to(user)`;** archived projects and lists
  left out, as on the to-dos page.
- **A fixed, small number of queries** whatever the number of projects.
- **Not live:** the lantern tells what's new; reloading shows it.

## Where

The brand ("Biwak") in the top bar links Home; the top bar's entries
stay "Projects", "To-dos", "Activity", "People", "Bookmarks". `g h` and
the palette's "Go home". Old links to `/?archived=1` redirect to
`/projects/?archived=1`.

## The sections

One column on phones; on wide screens a main column (1–4) and a narrow
one (5–7).

1. **Due** (everyone): my open to-dos overdue or due within the next 7
   days (decided 2026-11-21: 7 days, so a Friday still shows next
   week's), in the sections of `items.due.sections()`, up to 10, most
   urgent first; "All my to-dos" with the number when there are more.
   No to-dos without a date.
2. **Check-ins waiting for my answer** (`checkins_due`, across
   projects).
3. **Waiting on others** (staff): to-dos I assigned to somebody else,
   in the same window, up to 10, with their assignees; "All to-dos I
   assigned". Unlike the to-dos page's "assigned by me" without those
   I'm assigned to as well: they're in the first section already
   (decided 2026-11-22).
4. **Recent updates** (everyone): up to 10 feed entries
   (`activity/_entries.html`, conversations included) of the last 7
   days from two sources (decided 2026-11-21): everything in my
   bookmarked projects, and events that mention or assign me in any
   project. My own actions show too (context I contributed to). Clients
   by the feed's rules. Taken from the newest 50 events.
5. **Projects:** my bookmarked projects as cards; without bookmarks the
   6 most recently active I'm a member of, with "Bookmark projects to
   keep them here."; nobody in a project: "You're not in a project
   yet." with "New project" for those who may. Clients get Home too,
   also with a single project.
6. **Bookmarks:** up to 5 bookmarked items, newest first.
7. **Useful links**, each only for who can use it: to-dos I assigned
   (staff), search (Ctrl+K), keyboard shortcuts (opens the `?` dialog,
   `data-shortcuts-open`), help, the calendar subscription, notification
   settings, API tokens and the CLI (staff). No "New project" here
   (decided 2026-11-21: people should check the existing projects
   first).

## Shared with the lantern

**Nothing has to be dealt with twice** (decided 2026-11-21). Home has
nothing of its own to tick off or mark as seen: its rows go when what
they show is done (completed, answered, bookmark removed, aged out),
never by being looked at. Notifications show only as the lantern's
unread mark on rows, without a section of their own (decided
2026-11-21: "Mentioning you" would copy the lantern).

- **One state:** `Notification.read_at` (and `marked_unread_at`) and
  `Bookmark`; no "seen on Home".
- **Opening reads, as in the lantern:** a row whose item has unread
  notifications for me carries the unread mark and
  `data-lantern-read` (`/lantern/<notification>/`, POST only), which
  `frontend/lantern.js` posts when the link is followed
  (`lantern.unread_by_item()`). The feed, lists and mails still read
  nothing.
- **Acting reads, looking doesn't** ("Reading by acting", `lantern.md`):
  completing a to-do on Home reads its notifications; loading Home or
  bookmarking reads nothing.

## API and CLI

Nothing of its own: to-dos by due date, the feed, bookmarks, projects
and `GET /api/v1/me/checkins/due/` (`biwak checkin due`) have it all.
