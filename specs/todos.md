# To-dos: assignees, recurrence, board view, by due date

Builds on `core.md` and `access.md`.

**Status:** assignees, the board view, moving several to-dos at once and
adding to-dos inline are built (core, 2026-11-20). Stage 1 (schedules
and recurrence) and stage 2 (the list by due date, the iCal feed) are
built (2026-11-20).

**Agent:** both stages suit a cheaper model following this spec and the
checklist in `AGENTS.md`.

## Built

- **Assignees:** any number, staff and clients (clients only on visible
  to-dos, `assignable_people()`); completing completes for everybody and
  records who did it; assigning subscribes the assignee. Notifying them
  is `notifications.md`.
- **Board view:** a list's groups as columns, ungrouped to-dos in a first
  column shown only when there are any; a per-list setting (list or
  board) with `?view=` to switch; dragging between columns is the same
  operation as in the list (`move_todos()`).
- **Adding inline:** "Add a to-do" opens a form in place with title,
  notes, assignees and due date; Ctrl+Enter adds and starts the next
  one, Escape or a click elsewhere closes (`frontend/add-todo.js`).
- **Moving several at once:** clicking grips selects to-dos, dragging one
  moves them all; "Move to…" on the to-do's page for the keyboard.

## Stage 1: schedules and recurring to-dos

### Schedules

A small module of its own, `biwak/schedules.py`, used here and by
check-ins (`checkins.md`):

- A rule as an RRULE string (`python-dateutil`), validated on save.
- `next_date(rule, after, tz)`: the next date of the rule after a date,
  in the installation's time zone (`TIME_ZONE`); check-ins add a time of
  day.
- Presets for the forms, each with a human description: every weekday,
  every week on a chosen day, every two weeks, every month on the same
  day, the first (or last) weekday of the month, every three months,
  every year. Plus "custom": the RRULE typed in, for agents and power
  users.
- `describe(rule)`: a short English text ("every Monday", "the first
  Monday of every month") for pages and the API.

### Recurring to-dos

- **Model:** `Todo.recurrence` (the RRULE, empty for none),
  `recurrence_ends_on` (date, optional), `recurrence_count` (how many are
  left, optional), `previous` (the to-do it was created from).
- **Completing** a recurring to-do creates the next one in the same list
  and group, at the end, with the same title, notes, assignees and
  subscribers and the same rule, due on the rule's next date after
  today (decided 2026-11-20), or after the due date when it's completed
  early (decided at the merge, 2026-11-20: a weekly to-do due Friday and
  done on Wednesday is next due the Friday after, not the same Friday). Never a stack of open copies. Through
  `complete()`, in the same transaction, with its own `created` event.
- Comments and attachments stay with the completed to-do; the new one
  links to it ("Previous: completed on 3 March by Ada").
- **Ending:** an end date (no next one after it), a count (each next one
  has one less; none at zero), or removing the rule. Reopening the
  completed to-do doesn't remove the next one already created.
- **Form:** on the to-do's page and in the inline form, a "Repeat"
  select with the presets, "custom", and the end options.

### API and CLI

`recurrence`, `recurrence_description`, `recurrence_ends_on`,
`recurrence_count` and `previous_id` on `TodoOut`, writable in
create and patch. `biwak todo add|edit --repeat RULE` (a preset name or
an RRULE).

### Decisions made while building stage 1

All proposed by the building agent, 2026-11-20; change them here if wrong.

- **Presets count from the anchor date:** a to-do's due date, today when it
  has none. "Every week" is the due date's weekday, "every month" its day
  of the month, "the first/last weekday of the month" its weekday (the
  first or last Monday, not the first working day; the last working day
  is a custom rule, `FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1`).
  The stored rule is the plain RRULE, it doesn't follow later changes of
  the due date.
- **Short months and leap days:** the 29th to 31st of the month and 29
  February fall on the last day of shorter months instead of skipping
  them (`BYMONTHDAY=28,29,30,31;BYSETPOS=-1`).
- **Rules** have no `DTSTART`, `COUNT` or `UNTIL` (ends are the to-do's end
  date and count), nothing shorter than daily, and must produce a date.
  `next_date()` takes an optional `anchor` so "every two weeks" keeps its
  phase.
- **Count** is how many more to-dos get created after this one: 2 makes
  two more, the last has 0. Both end options are optional and removed
  together with the rule.
- **One series:** completing a to-do that already has a next one (not in
  the trash) creates none, so reopening and completing again never makes
  a branch.
- **Next to-do:** created by the original creator, with the "created"
  event by whoever completed it; assignees who are inactive or can't see
  it any more are left out.
- **Form:** the "Repeat" select, a field for the custom rule, the end date
  and "repeats left"; a missing "Repeat" field on a posted form removes
  the rule.
- **API:** `recurrence` accepts a preset name (counted from the due date
  sent, or the stored one) or an RRULE; `null` or `""` removes it.
  `previous_id` is hidden when the to-do is visible to clients and the
  previous one isn't (moved since), for staff too: the API doesn't know
  who asks. The CLI has `--repeat` only; end date and count are
  API-only for now.
- **Form and rules for another weekday (fixed 2026-11-20):** the form
  shows a preset only when it gives exactly the stored rule counted from
  the due date (`schedules.preset_for`), else "custom", so saving the
  form with only the title changed keeps a rule set through the API or
  the CLI for another weekday or day (it became `BYDAY=FR` before).

### Done when (stage 1)

Tests: month ends (31st, every month), leap years (29 February every
year), the last weekday of the month, time zone and daylight saving
changes around midnight, completing the last occurrence (count and end
date), reopening, the next one's assignees and subscribers, a client
completing a recurring visible to-do.

## Stage 2: the list by due date

Instead of a calendar: open to-dos by due date, grouped into overdue,
today, this week (until Sunday), later and no date.

- `/todos/` across all projects the person can see, `/projects/<pk>/todos/`
  per project; "My to-dos" (`/todos/?assignee=me`) in the navigation.
- Filters as query parameters, the form submitting with GET: project,
  assignee (anybody, me, a person, nobody), list, open or completed
  (completed: the latest first, paginated), visible to clients or not.
- Each row: the to-do with its checkbox (completing works here too),
  project, list, assignees, due date, the client badge.
- Through `Item.objects.visible_to()` like everything else.

### iCal feed

- Per person, their assigned open to-dos with a due date as all-day
  events (`icalendar` package), at `/calendar/<token>.ics`.
- The token is secret, shown on `/accounts/calendar/` with "Copy" and
  "Make a new link" (the old one stops working). Model:
  `CalendarToken(user, token unique, created_at)`.
- No login needed for the feed URL; it shows only what the person can
  see now. Inactive people's feeds are empty.

### API and CLI

`GET /api/v1/todos/?…` with the same filters and grouping key per to-do,
cursor-paginated. `biwak todos --mine|--project ID|--due …` across
projects (the existing `biwak todos LIST` stays).

### Decisions made while building stage 2

All proposed by the building agent, 2026-11-20; change them here if wrong.

- **Left out of the list** (and the API and the feed): to-dos of archived
  projects and of archived lists, besides trashed ones.
- **This week** runs until Sunday, in the installation's time zone: on
  a Sunday it's empty, everything after today is "later".
- **Filters:** unknown values (a project the person can't open, a
  non-existent person) show an error and no to-dos, never a silent
  "everything". Assignee choices list people only for staff; clients get
  "anybody", "me" and "nobody". The visibility filter is staff only.
  `?state=completed` (latest first, 50 per page) replaces the sections.
- **Completing in place** posts to the same toggle as the list's page and
  comes back to the filtered list (`next`, same site only).
- **Navigation:** "My to-dos" in the top bar; "Calendar" (the feed link)
  in the person's menu; the project page links to its to-dos by due date.
- **Feed:** a plain all-day event per open assigned to-do with a due
  date: title, link, "project / list" as the description, no notes (the
  URL travels through calendar servers); `UID` `todo-ID@biwak`; not
  marked busy. Not in the audit log either: the token is a secret.
  The link is created and renewed on the page with a POST.
- **API:** `GET /api/v1/todos/` takes `project_id`, `list_id`, `assignee`
  (`me`, `nobody`, an ID), `completed`, `visible_to_clients` (ignored for
  clients), `due_group` and the cursor; each to-do carries `due_group`,
  `project_name` and `list_title`. Open ones are ordered by due date (to-dos
  without one last), completed ones latest first.
- **CLI:** `biwak todos` without LIST takes `--mine`, `--project ID`,
  `--due GROUP` and `--completed`; it shows the first 200.

### Done when (stage 2)

Pages, filters, API, CLI, the feed. Tests: the grouping around midnight
and week ends (time zone), filters, a client seeing only visible to-dos,
the feed with a revoked token (404) and for a person who lost access.

## Stage 3: long lists of completed to-dos

Decided 2026-11-20, a worry rather than an observed problem: lists used
for years collect hundreds of completed to-dos. Today the list page
shows the latest 20 in a collapsed "Completed" section and nothing
beyond.

- The section stays collapsed and says how many there are ("Completed
  (142)"), counted in the same query as the open ones.
- Opening it shows the latest 20; "Show more" loads the next 50 with
  htmx below them (cursor on `(completed_at, pk)`, like the feed's), as
  long as there are more.
- The board view never shows completed to-dos in its columns; the
  section stays below the board.
- The API's list of a list's to-dos already filters by completion; add
  the cursor if it lacks one.

**Agent:** a cheaper model. **Touches:** `todolist()` in
`biwak/items/views.py`, `items/todolist.html`, a small view for the
next page.

**Status:** built 2026-11-20.

Decisions made while building (proposed by the building agent; change
them here if wrong):

- The cursor is `?before=<completed_at ISO>,<pk>` on
  `/lists/<pk>/completed/`, which returns an HTML fragment (the next 50
  and a new "Show more" button, or none at the end); a malformed cursor
  is a 404. The same fragment renders the first 20.
- The count is its own `COUNT` query, not folded into the open ones'
  query; trashed to-dos aren't counted.
- The completed section sits below the board and the list alike; the
  board's columns only ever had open to-dos.
- The API (`lists/{id}/todos/completed/`) already had a cursor; API and
  CLI are unchanged.

### Done when (stage 3)

The count, paging through 120 completed to-dos without gaps or
duplicates (same `completed_at`), a client seeing only visible to-dos
and counts (clients only see visible lists, so all of its to-dos; test
it anyway).
