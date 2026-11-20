# To-dos: assignees, recurrence, board view, by due date

Builds on `core.md` and `access.md`.

**Status:** assignees, the board view, moving several to-dos at once and
adding to-dos inline are built (core, 2026-11-20). Stage 1 (schedules
and recurrence) and stage 2 (the list by due date, the iCal feed) are
open.

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
  today (decided 2026-11-20). Never a stack of open copies. Through
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

### Done when (stage 2)

Pages, filters, API, CLI, the feed. Tests: the grouping around midnight
and week ends (time zone), filters, a client seeing only visible to-dos,
the feed with a revoked token (404) and for a person who lost access.
